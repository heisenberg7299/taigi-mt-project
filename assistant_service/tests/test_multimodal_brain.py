"""
multimodal_brain.classify()測試：語音+視覺訊號統一分類邏輯。用假brain
(duck-typed，只要有.generate())讓LLM路徑決定性，不需要真的連Ollama；
規則式快速路徑用真的voice_io_event_detector套件(這台環境已經透過.pth
裝好，見assistant_service/README.md)。
"""

from __future__ import annotations

import pytest

from assistant_service.brain_response import BrainResponse
from assistant_service.multimodal_brain import classify


class _FakeBrain:
    def __init__(self):
        self.calls: list[str] = []

    def generate(self, text: str, request_id: str | None = None) -> BrainResponse:
        self.calls.append(text)
        return BrainResponse(
            request_id=request_id or "fake", intent="general_chat", risk_level="low",
            language="zh-TW", response_zh=f"回覆：{text}",
        )


def test_voice_only_matching_rule_uses_fast_path_without_calling_llm():
    brain = _FakeBrain()
    br, path = classify(voice_text="我想要喝水", brain=brain)

    assert path == "rule_based_fast_path"
    assert br.intent == "water_request"
    assert brain.calls == []  # LLM完全沒被呼叫


def test_voice_only_no_rule_match_falls_through_to_llm():
    brain = _FakeBrain()
    br, path = classify(voice_text="今天天氣真好", brain=brain)

    assert path == "llm_multimodal"
    assert brain.calls == ["使用者說的話：今天天氣真好"]


def test_vision_only_always_uses_llm_not_a_lookup_table():
    """視覺訊號不管內容是什麼都要送進LLM分類，不能直接查表決定最終回覆
    ——這是這次要求的重點：視覺辨識也要依靠LLM分類。"""
    brain = _FakeBrain()
    br, path = classify(vision_description="使用者的手靠近嘴巴/臉部，可能想喝水", brain=brain)

    assert path == "llm_multimodal"
    assert brain.calls == ["鏡頭觀察到的畫面：使用者的手靠近嘴巴/臉部，可能想喝水"]


def test_voice_and_vision_together_always_uses_llm_even_if_voice_matches_rule():
    """語音+視覺同時出現時，就算語音對得到規則式關鍵字，也不能只看語音就
    走快速路徑決定——視覺訊號可能提供衝突或補充資訊，必須讓LLM綜合判斷。"""
    brain = _FakeBrain()
    br, path = classify(voice_text="我想要喝水", vision_description="使用者的手舉高過肩膀", brain=brain)

    assert path == "llm_multimodal"
    assert brain.calls == ["使用者說的話：我想要喝水\n鏡頭觀察到的畫面：使用者的手舉高過肩膀"]


def test_neither_voice_nor_vision_raises_value_error():
    with pytest.raises(ValueError):
        classify(brain=_FakeBrain())


def test_request_id_is_passed_through_to_brain_response():
    brain = _FakeBrain()
    br, _ = classify(voice_text="今天天氣真好", request_id="req_custom", brain=brain)
    assert br.request_id == "req_custom"
