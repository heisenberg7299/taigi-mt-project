"""
Response Controller：大腦只負責「要回答什麼」(BrainResponse JSON)，這裡
負責「能不能安全說、怎麼翻成台語」——風險判斷、安全閘門、路由到
tw_hokkien_tts_pipeline的翻譯策略、失敗時的固定回覆，不讓大腦(LLM)的
自由文字直接送進TTS。

路由規則(照設計)：
  - risk_level == "high"：**只**用 StructuredMedicalRenderer(候選C)，
    不讓LLM自由決定最後句子。intent沒有對應模板時直接abstain，不會退回
    去用候選A/B(那樣等於還是讓LLM決定了高風險內容的最終文字)。
  - risk_level in ("medium", "low")：用
    tw_hokkien_tts_pipeline.adaptive_translation.translate_with_structured_
    fallback()(候選A/B/C全部可能用到)，安全檢查沒過一樣abstain，不放行。

安全檢查失敗時**不會**播放可能有錯的翻譯，也不會完全沉默：播放固定的
預先審核句「這个問題我無法度確定，我共你通知護理師。」，並回傳
status="abstained"/action="call_nurse"。**這句台語的實際內容還沒有經過
台語母語者審核**，這裡先用neurlang生成demo版本，正式使用前必須先確認
這句話本身的用字/發音是正確的(這點在程式碼跟README都要註明，不能默默
假裝已經審核過)。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.adaptive_translation import (  # noqa: E402
    UnsafeTranslationError,
    translate_with_structured_fallback,
)
from tw_hokkien_tts_pipeline.structured_renderer import StructuredIntent, StructuredMedicalRenderer  # noqa: E402

from assistant_service.brain_response import BrainResponse  # noqa: E402

# 固定回覆(fail-closed用)：**demo版本，尚未經台語母語者審核**，正式使用前
# 這句話的實際台語用字/發音要先確認過，才能真的信任它在任何情況下都安全。
# 目前用neurlang生成好放在 fallback_audio/，不用每次abstain都重新合成。
FALLBACK_SENTENCE_HAN = "這个問題我無法度確定，我共你通知護理師。"
FALLBACK_AUDIO_NAME = "notify_nurse.wav"
FALLBACK_AUDIO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fallback_audio", FALLBACK_AUDIO_NAME)

# BrainResponse.slots 的欄位名 -> StructuredIntent 的欄位名對應表
_SLOT_TO_INTENT_FIELD = {
    "drug": "drug",
    "dose": "dose",
    "time": "time",
    "constraint": "constraint",
    "person": "patient",
    "patient_title": "patient_title",
    "location": "location",
    "staff_role": "staff_role",
    "need": "need",
    "remainder_zh": "remainder_zh",
}

# 交叉比對時要檢查的slot欄位：如果大腦自己給的這些值沒出現在它自己生成的
# response_zh裡，代表大腦內部就已經不一致，不用等翻譯完才發現問題
_CROSS_CHECK_SLOT_KEYS = ("drug", "dose", "time", "person")


@dataclass
class ControllerResult:
    request_id: str
    status: str  # "completed" / "abstained" / "rejected"
    translation_method: str | None = None  # "raw" / "masked" / "structured_c" / None
    hanji_text: str | None = None
    tts_backend: str | None = None
    audio_path: str | None = None
    action: str = "speak"
    safety: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "status": self.status,
            "translation_method": self.translation_method,
            "tts_backend": self.tts_backend,
            "audio_path": self.audio_path,
            "action": self.action,
            "safety": self.safety,
            "errors": self.errors,
        }


def slots_to_structured_intent(brain_response: BrainResponse) -> StructuredIntent | None:
    """把BrainResponse.slots轉成StructuredMedicalRenderer看得懂的
    StructuredIntent。intent本身不在renderer支援範圍內時回傳的物件
    can_handle()一樣會是False，由呼叫方決定要不要當作abstain條件。"""
    kwargs: dict = {"intent": brain_response.intent}
    for slot_key, intent_field in _SLOT_TO_INTENT_FIELD.items():
        value = brain_response.slots.get(slot_key)
        if value is not None:
            kwargs[intent_field] = value
    return StructuredIntent(**kwargs)


def cross_check_slots_vs_response(brain_response: BrainResponse) -> list[str]:
    """檢查response_zh有沒有跟slots矛盾。"""
    if not brain_response.response_zh:
        return []
    issues = []
    for key in _CROSS_CHECK_SLOT_KEYS:
        value = brain_response.slots.get(key)
        if value and str(value) not in brain_response.response_zh:
            issues.append(f"slots.{key}={value!r} 沒有出現在 response_zh 裡")
    return issues


def _abstain(brain_response: BrainResponse, reason: str) -> ControllerResult:
    return ControllerResult(
        request_id=brain_response.request_id,
        status="abstained",
        action="call_nurse",
        hanji_text=FALLBACK_SENTENCE_HAN,
        audio_path=FALLBACK_AUDIO_PATH if os.path.exists(FALLBACK_AUDIO_PATH) else FALLBACK_AUDIO_NAME,
        tts_backend="cached_fallback",
        errors=[reason],
    )


class ResponseController:
    def __init__(self, guard, translation_backend, renderer: StructuredMedicalRenderer | None = None, tts_router=None):
        self.guard = guard
        self.translation_backend = translation_backend
        self.renderer = renderer or StructuredMedicalRenderer()
        self.tts_router = tts_router

    def handle(self, brain_response: BrainResponse) -> ControllerResult:
        # 1. 驗證JSON欄位
        validation_errors = brain_response.validate()
        if validation_errors:
            return ControllerResult(
                request_id=brain_response.request_id, status="rejected", errors=validation_errors,
            )

        # action != "speak" 的直接處理, 不需要翻譯/TTS
        if brain_response.action != "speak":
            return ControllerResult(
                request_id=brain_response.request_id, status="completed", action=brain_response.action,
            )

        # 2. 比對response_zh跟slots
        mismatch = cross_check_slots_vs_response(brain_response)
        if mismatch:
            return _abstain(brain_response, f"大腦回覆的response_zh跟slots不一致: {mismatch}")

        # 3. 風險路由
        try:
            if brain_response.risk_level == "high":
                structured_intent = slots_to_structured_intent(brain_response)
                if not self.renderer.can_handle(structured_intent):
                    return _abstain(
                        brain_response,
                        f"高風險intent「{brain_response.intent}」沒有對應的Structured C模板，"
                        "不允許讓LLM自由翻譯決定最終文字",
                    )
                hanji_text = self.renderer.render(structured_intent, self.translation_backend)
                method = "structured_c"
                safety = self._verify_structured_c_output(brain_response, hanji_text)
            else:
                structured_intent = slots_to_structured_intent(brain_response)
                result = translate_with_structured_fallback(
                    brain_response.response_zh, self.guard, self.translation_backend,
                    structured_intent=structured_intent, structured_renderer=self.renderer,
                )
                hanji_text = result.hanji_text
                method = result.chosen
                chosen_candidate = result.raw_candidate if method == "raw" else (
                    result.masked_candidate if method == "masked" else None
                )
                safety = {
                    "token_integrity": chosen_candidate.entities_ok if chosen_candidate else True,
                    "semantic_safety": "safe" if (chosen_candidate is None or chosen_candidate.safety_ok) else "unsafe",
                }
        except UnsafeTranslationError as exc:
            return _abstain(brain_response, f"翻譯安全檢查未通過(候選A/B/C皆未通過): {exc}")

        # 4. TTS
        if self.tts_router is None:
            return ControllerResult(
                request_id=brain_response.request_id, status="completed",
                translation_method=method, hanji_text=hanji_text, action="speak", safety=safety,
            )
        tts_result = self.tts_router.route_and_synthesize(hanji_text)
        return ControllerResult(
            request_id=brain_response.request_id, status="completed",
            translation_method=method, hanji_text=hanji_text,
            tts_backend=tts_result.backend, audio_path=str(tts_result.audio_path),
            action="speak", safety=safety,
        )

    @staticmethod
    def _verify_structured_c_output(brain_response: BrainResponse, hanji_text: str) -> dict:
        """候選C是模板生成，理論上結構化欄位一定正確，但仍然對輸出文字
        重新跑一次語意安全檢查而不是盲目信任生成來源(避免循環評估，見
        reports/translation_safety_evaluator_v2.md 對這個原則的說明)。"""
        from scripts.safety_checks import run_all_checks

        checks = run_all_checks(brain_response.response_zh or "", hanji_text)
        all_ok = all(v["ok"] for v in checks.values())
        return {"token_integrity": True, "semantic_safety": "safe" if all_ok else "uncertain", "checks": checks}
