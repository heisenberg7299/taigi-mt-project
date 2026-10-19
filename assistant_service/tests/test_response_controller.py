"""
Response Controller測試，用假backend+假TTS router讓結果決定性，不需要
Ollama或TTS process在跑。涵蓋第一個里程碑手動驗證過的4種情境：high risk
用candidate C成功、low risk用adaptive翻譯成功、high risk沒有對應模板時
abstain、slots跟response_zh矛盾時abstain。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from assistant_service.brain_response import BrainResponse
from assistant_service.response_controller import FALLBACK_SENTENCE_HAN, ResponseController
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard
from tw_hokkien_tts_pipeline.structured_renderer import StructuredMedicalRenderer
from tw_hokkien_tts_pipeline.translate import TranslationBackend, TranslationResult


class _FakeBackend(TranslationBackend):
    name = "fake"

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def translate(self, zh_text: str) -> TranslationResult:
        return TranslationResult(
            source_text=zh_text, translated_text=self.mapping.get(zh_text, zh_text), backend_name=self.name,
        )


@dataclass
class _FakeTTSResult:
    backend: str
    audio_path: Path


class _FakeTTSRouter:
    def __init__(self):
        self.calls: list[str] = []

    def route_and_synthesize(self, text: str) -> _FakeTTSResult:
        self.calls.append(text)
        return _FakeTTSResult(backend="fake_tts", audio_path=Path(f"/fake/{text}.wav"))


def _make_controller(mapping: dict[str, str], drug_lexicon=None) -> tuple[ResponseController, _FakeTTSRouter]:
    guard = ProtectedTokenGuard(drug_lexicon=drug_lexicon or {})
    backend = _FakeBackend(mapping)
    renderer = StructuredMedicalRenderer()
    tts_router = _FakeTTSRouter()
    controller = ResponseController(guard=guard, translation_backend=backend, renderer=renderer, tts_router=tts_router)
    return controller, tts_router


# ---------- BrainResponse 驗證 ----------

def test_brain_response_validate_rejects_bad_risk_level():
    br = BrainResponse.from_dict({
        "request_id": "r1", "intent": "x", "risk_level": "extreme", "response_zh": "測試",
    })
    errors = br.validate()
    assert any("risk_level" in e for e in errors)


def test_brain_response_validate_requires_response_zh_when_speaking():
    br = BrainResponse.from_dict({
        "request_id": "r1", "intent": "x", "risk_level": "low", "response_zh": None, "action": "speak",
    })
    assert any("response_zh" in e for e in br.validate())


# ---------- Response Controller: 四種情境 ----------

def test_high_risk_uses_structured_c_when_intent_supported():
    """對應使用者提供的範例JSON：high risk + medication_reminder，應該走
    candidate C，不讓LLM決定最終文字(mapping裡故意不放對應的翻譯，證明
    真的沒有呼叫翻譯backend去生成關鍵句子)。"""
    controller, tts_router = _make_controller(mapping={})
    br = BrainResponse.from_dict({
        "request_id": "req_001", "intent": "medication_reminder", "risk_level": "high",
        "language": "zh-TW", "response_zh": "請記得在晚餐後服用盤尼西林。",
        "slots": {"drug": "盤尼西林", "time": "晚餐後", "dose": None, "person": None, "negation": False},
        "action": "speak", "evidence_ids": [], "priority": 80,
    })
    result = controller.handle(br)

    assert result.status == "completed"
    assert result.translation_method == "structured_c"
    assert "盤尼西林" in result.hanji_text
    assert result.safety["token_integrity"] is True
    assert len(tts_router.calls) == 1


def test_low_risk_uses_adaptive_translation():
    controller, tts_router = _make_controller(mapping={
        "今天天氣很好，要不要出去走走？": "今仔日天氣真好，欲毋欲出去行行咧？",
    })
    br = BrainResponse.from_dict({
        "request_id": "req_002", "intent": "general_chat", "risk_level": "low",
        "response_zh": "今天天氣很好，要不要出去走走？", "slots": {}, "action": "speak", "priority": 10,
    })
    result = controller.handle(br)

    assert result.status == "completed"
    assert result.translation_method == "raw"
    assert len(tts_router.calls) == 1


def test_high_risk_without_supported_intent_abstains_and_does_not_call_tts():
    """高風險但沒有對應的Structured C模板時，不能退回去用候選A/B讓LLM
    自由決定，必須直接abstain。"""
    controller, tts_router = _make_controller(mapping={
        "病人主訴胸痛，需要立刻評估。": "患者主訴胸坎疼，愛隨評估。",
    })
    br = BrainResponse.from_dict({
        "request_id": "req_003", "intent": "chest_pain_emergency", "risk_level": "high",
        "response_zh": "病人主訴胸痛，需要立刻評估。", "slots": {}, "action": "speak", "priority": 100,
    })
    result = controller.handle(br)

    assert result.status == "abstained"
    assert result.action == "call_nurse"
    assert result.hanji_text == FALLBACK_SENTENCE_HAN
    assert len(tts_router.calls) == 0  # 不應該呼叫TTS去合成任何候選內容


def test_slots_response_mismatch_abstains_before_translation():
    """大腦自己給的slots.drug跟自己生成的response_zh對不上，應該在翻譯
    之前就被攔下來，不應該去呼叫翻譯backend。"""
    call_log = []

    class _TrackingBackend(TranslationBackend):
        name = "tracking"

        def translate(self, zh_text):
            call_log.append(zh_text)
            return TranslationResult(source_text=zh_text, translated_text=zh_text, backend_name=self.name)

    guard = ProtectedTokenGuard()
    controller = ResponseController(
        guard=guard, translation_backend=_TrackingBackend(),
        renderer=StructuredMedicalRenderer(), tts_router=_FakeTTSRouter(),
    )
    br = BrainResponse.from_dict({
        "request_id": "req_004", "intent": "medication_reminder", "risk_level": "high",
        "response_zh": "請記得吃藥。",
        "slots": {"drug": "普拿疼", "time": None, "dose": None, "person": None, "negation": False},
        "action": "speak", "priority": 80,
    })
    result = controller.handle(br)

    assert result.status == "abstained"
    assert "slots" in result.errors[0]
    assert call_log == []  # 翻譯backend完全沒被呼叫過


def test_invalid_brain_response_is_rejected_but_still_gets_fail_safe_response():
    """JSON格式本身就有問題(不是翻譯安全問題)，status要回傳rejected跟
    abstained(翻譯/安全層面的問題)區分開來——但兩者都必須有實際的語音
    回應+通知護理師，不能因為是「格式錯誤」這種問題就默默跳過、什麼反應
    都沒有(這是修正過的行為, 原本rejected不會有任何fallback audio)。"""
    guard = ProtectedTokenGuard()
    controller = ResponseController(
        guard=guard, translation_backend=_FakeBackend({}),
        renderer=StructuredMedicalRenderer(), tts_router=_FakeTTSRouter(),
    )
    br = BrainResponse.from_dict({"request_id": "", "intent": "x", "risk_level": "bogus", "response_zh": "test"})
    result = controller.handle(br)

    assert result.status == "rejected"
    assert len(result.errors) >= 1
    # 修正後：格式錯誤也要有語音+通知護理師的反應，不能靜默
    assert result.action == "call_nurse"
    assert result.audio_path is not None
    assert result.hanji_text is not None


def test_missing_required_keys_does_not_crash_from_dict():
    """BrainResponse.from_dict()完全缺少request_id/intent/risk_level這些
    key時(不只是值不合法，是key根本不存在)不應該raise例外——這是LLM輸出
    格式不完整時真的會發生的情境，不能讓程式在validate()有機會執行之前
    就先crash掉。"""
    br = BrainResponse.from_dict({"response_zh": "測試"})  # 完全沒有request_id/intent/risk_level
    assert br.request_id == ""
    assert br.intent == ""
    errors = br.validate()
    assert len(errors) >= 1  # risk_level=""不合法, 應該被validate()抓到


def test_risk_level_is_force_escalated_when_slots_contain_drug():
    """大腦自己標risk_level=low, 但slots裡有drug欄位, 規則式邏輯應該
    強制升級成high, 走Structured C而不是讓LLM自由翻譯決定藥物相關內容。"""
    controller, tts_router = _make_controller(mapping={})
    br = BrainResponse.from_dict({
        "request_id": "req_escalate", "intent": "medication_reminder",
        "risk_level": "low",  # 大腦自己標成low, 但不應該被信任
        "response_zh": "請記得在晚餐後服用盤尼西林。",
        "slots": {"drug": "盤尼西林", "time": "晚餐後", "dose": None, "person": None, "negation": False},
        "action": "speak", "priority": 10,
    })
    result = controller.handle(br)

    assert result.status == "completed"
    assert result.translation_method == "structured_c"  # 證明真的被拉到high了
    assert "盤尼西林" in result.hanji_text


def test_risk_level_never_downgraded_from_high():
    """大腦標risk_level=high且沒有對應模板時, 就算slots/intent看起來
    毫無風險也不能被降級放行——high永遠維持high。"""
    controller, tts_router = _make_controller(mapping={
        "今天天氣真好。": "今仔日天氣真好。",
    })
    br = BrainResponse.from_dict({
        "request_id": "req_stay_high", "intent": "small_talk", "risk_level": "high",
        "response_zh": "今天天氣真好。", "slots": {}, "action": "speak", "priority": 10,
    })
    result = controller.handle(br)

    # small_talk不在StructuredMedicalRenderer支援範圍內, high risk應該
    # 直接abstain, 不會退回去用candidate A/B
    assert result.status == "abstained"
    assert len(tts_router.calls) == 0


def test_post_translation_mismatch_abstains_even_when_protected_token_does_not_catch_it():
    """關鍵情境：slots.person這個人名沒有登記在Protected Token的
    person_names保護詞庫裡(guard根本不知道要保護它)，所以adaptive A/B
    機制自己的entities_ok檢查不會發現人名被翻譯弄丟了(candidate A會被
    判定"通過")——這正是為什麼還需要獨立的「翻譯後對slots再檢查一次」
    這一層，不能只依賴Protected Token自己的entity檢查，兩者是不同的
    安全機制，各自涵蓋不了對方的盲區。intent/slots故意都不含drug/dose/
    negation，確保effective_risk_level維持low、真的走candidate A/B。"""
    controller, tts_router = _make_controller(
        mapping={"林小華的家人來看他了。": "個的人來看伊矣。"},  # 翻譯把人名弄丟了
        drug_lexicon={},
    )
    br = BrainResponse.from_dict({
        "request_id": "req_post_check", "intent": "family_notice", "risk_level": "low",
        "response_zh": "林小華的家人來看他了。",
        "slots": {"drug": None, "dose": None, "time": None, "person": "林小華", "negation": False},
        "action": "speak", "priority": 50,
    })
    result = controller.handle(br)

    assert result.status == "abstained"
    assert any("翻譯後" in e for e in result.errors)
    assert len(tts_router.calls) == 0  # 翻譯後才發現問題, 不應該還去呼叫TTS


def test_non_speak_action_bypasses_translation_and_tts():
    guard = ProtectedTokenGuard()
    tts_router = _FakeTTSRouter()
    controller = ResponseController(
        guard=guard, translation_backend=_FakeBackend({}),
        renderer=StructuredMedicalRenderer(), tts_router=tts_router,
    )
    br = BrainResponse.from_dict({
        "request_id": "req_005", "intent": "x", "risk_level": "low",
        "response_zh": None, "action": "call_nurse", "priority": 90,
    })
    result = controller.handle(br)

    assert result.status == "completed"
    assert result.action == "call_nurse"
    assert len(tts_router.calls) == 0
