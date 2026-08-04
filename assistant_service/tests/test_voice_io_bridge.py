"""
測試voice_io_bridge：yuava22/Interactive-service-robots的規則式意圖判斷
(EventDecision)轉成BrainResponse的邏輯，以及轉出來的BrainResponse真的能
餵進ResponseController走完整條管線(不需要真的裝對方套件、不需要Whisper，
用跟test_response_controller.py一樣的假backend/假TTS router)。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assistant_service.response_controller import ResponseController
from assistant_service.speech_request_queue import (
    PRIORITY_COMPANION_CHAT,
    PRIORITY_GENERAL_SERVICE,
    PRIORITY_NURSE_ALERT,
)
from assistant_service.voice_io_bridge import event_decision_to_brain_response
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard
from tw_hokkien_tts_pipeline.structured_renderer import StructuredMedicalRenderer
from tw_hokkien_tts_pipeline.translate import TranslationBackend, TranslationResult


@dataclass(frozen=True)
class _FakeEventDecision:
    """跟voice_io_event_detector.intent_rules.EventDecision同樣的欄位形狀
    (event/reply_zh/reply_en)，不需要真的裝對方套件就能測轉換邏輯。"""

    event: str | None
    reply_zh: str
    reply_en: str


def test_water_request_maps_to_low_risk_speak_action():
    decision = _FakeEventDecision(
        event="WATER_REQUEST", reply_zh="我已通知護理人員協助送水，請稍等。", reply_en="...",
    )
    br = event_decision_to_brain_response(decision, request_id="req_water")

    assert br.request_id == "req_water"
    assert br.intent == "water_request"
    assert br.risk_level == "low"
    assert br.response_zh == decision.reply_zh
    assert br.action == "speak"
    assert br.slots == {}
    assert br.priority == PRIORITY_GENERAL_SERVICE
    assert br.is_valid


def test_toilet_request_maps_to_general_service_priority():
    decision = _FakeEventDecision(event="TOILET_REQUEST", reply_zh="我已通知護理人員協助如廁，請稍等。", reply_en="...")
    br = event_decision_to_brain_response(decision)

    assert br.intent == "toilet_request"
    assert br.priority == PRIORITY_GENERAL_SERVICE
    assert br.request_id  # 沒給request_id時應該自動產生一個非空的值


def test_help_request_gets_higher_priority_but_stays_low_risk():
    """求助事件優先權要比一般服務高(可能插播)，但risk_level仍是low——
    這句話翻譯內容不涉及藥物/醫囑，不需要走StructuredMedicalRenderer。
    priority(播放順序)跟risk_level(翻譯安全等級)是兩個獨立的維度。"""
    decision = _FakeEventDecision(event="HELP_REQUEST", reply_zh="我已通知護理人員，請保持冷靜，我會陪你。", reply_en="...")
    br = event_decision_to_brain_response(decision)

    assert br.intent == "help_request"
    assert br.priority == PRIORITY_NURSE_ALERT
    assert br.risk_level == "low"


def test_unclassified_event_maps_to_lowest_priority():
    decision = _FakeEventDecision(event=None, reply_zh="我有聽到，但我不太確定你的需求，可以再說一次嗎？", reply_en="...")
    br = event_decision_to_brain_response(decision)

    assert br.intent == "unclassified_request"
    assert br.priority == PRIORITY_COMPANION_CHAT


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


def test_water_request_brain_response_flows_through_response_controller():
    """轉出來的BrainResponse不只格式對，真的餵進ResponseController也要能
    完整跑完(low risk -> adaptive A/B，不會誤入Structured C，也不會被
    slots/response_zh交叉比對擋下來，因為slots是空的、沒有東西可以矛盾)。"""
    decision = _FakeEventDecision(
        event="WATER_REQUEST", reply_zh="我已通知護理人員協助送水，請稍等。", reply_en="...",
    )
    br = event_decision_to_brain_response(decision, request_id="req_water_e2e")

    guard = ProtectedTokenGuard()
    backend = _FakeBackend({decision.reply_zh: "我已經共護理人員通知欲送水矣，請小等一下。"})
    tts_router = _FakeTTSRouter()
    controller = ResponseController(
        guard=guard, translation_backend=backend, renderer=StructuredMedicalRenderer(), tts_router=tts_router,
    )

    result = controller.handle(br)

    assert result.status == "completed"
    assert result.translation_method in ("raw", "masked")  # 不是structured_c
    assert result.action == "speak"
    assert len(tts_router.calls) == 1
