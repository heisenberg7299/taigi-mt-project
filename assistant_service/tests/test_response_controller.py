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


def test_invalid_brain_response_is_rejected_not_abstained():
    """JSON格式本身就有問題(不是翻譯安全問題)，應該回傳rejected，跟
    abstained(翻譯/安全層面的問題)區分開來。"""
    guard = ProtectedTokenGuard()
    controller = ResponseController(
        guard=guard, translation_backend=_FakeBackend({}),
        renderer=StructuredMedicalRenderer(), tts_router=_FakeTTSRouter(),
    )
    br = BrainResponse.from_dict({"request_id": "", "intent": "x", "risk_level": "bogus", "response_zh": "test"})
    result = controller.handle(br)

    assert result.status == "rejected"
    assert len(result.errors) >= 1


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
