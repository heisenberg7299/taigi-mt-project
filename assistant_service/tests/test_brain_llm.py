"""
OllamaBrain單元測試：用假的requests.post讓結果決定性，不需要真的連Ollama。
真實呼叫的smoke test在test_brain_llm_smoke.py(需要真的pull過qwen2.5:7b
-instruct才會跑，沒有就skip)。
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from assistant_service.brain_llm import OllamaBrain, OllamaBrainError
from assistant_service.medical_kb import KnowledgeEntry


def _fake_response(content_dict: dict | str):
    content = content_dict if isinstance(content_dict, str) else json.dumps(content_dict, ensure_ascii=False)

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": content}}

    return _Resp()


def test_generate_parses_valid_json_into_brain_response():
    brain = OllamaBrain()
    llm_output = {
        "intent": "medication_question",
        "risk_level": "high",
        "response_zh": "這個問題我會轉達給護理人員確認。",
        "slots": {"drug": "普拿疼", "dose": None, "time": None, "person": None, "negation": False},
        "action": "speak",
    }
    with patch("requests.post", return_value=_fake_response(llm_output)):
        br = brain.generate("我可以多吃一顆普拿疼嗎", request_id="req_llm_1")

    assert br.request_id == "req_llm_1"
    assert br.intent == "medication_question"
    assert br.risk_level == "high"
    assert br.slots["drug"] == "普拿疼"
    assert br.is_valid


def test_generate_defaults_priority_high_for_high_risk():
    llm_output = {
        "intent": "medication_question", "risk_level": "high",
        "response_zh": "測試", "slots": {}, "action": "speak",
    }
    with patch("requests.post", return_value=_fake_response(llm_output)):
        br = OllamaBrain().generate("test")
    assert br.priority == 80


def test_generate_defaults_priority_lower_for_low_risk():
    llm_output = {
        "intent": "general_chat", "risk_level": "low",
        "response_zh": "測試", "slots": {}, "action": "speak",
    }
    with patch("requests.post", return_value=_fake_response(llm_output)):
        br = OllamaBrain().generate("test")
    assert br.priority == 50


def test_generate_auto_creates_request_id_when_not_given():
    llm_output = {"intent": "x", "risk_level": "low", "response_zh": "測試", "slots": {}, "action": "speak"}
    with patch("requests.post", return_value=_fake_response(llm_output)):
        br = OllamaBrain().generate("test")
    assert br.request_id  # 非空


def test_malformed_json_output_does_not_crash_and_produces_invalid_brain_response():
    """LLM輸出不是合法JSON時(理論上format=json會避免，但防禦性處理)，不應該
    raise例外，應該回傳一個validate()會失敗的BrainResponse，讓Response
    Controller走status=rejected的fail-safe路徑，而不是讓整個request死掉。"""
    with patch("requests.post", return_value=_fake_response("這不是JSON，模型亂輸出了")):
        br = OllamaBrain().generate("test")
    assert not br.is_valid


def test_json_embedded_in_extra_text_is_still_extracted():
    """就算模型多輸出了JSON以外的文字(例如解釋)，只要裡面包含合法JSON物件，
    仍然要能抽取出來，不能直接放棄。"""
    llm_output = {"intent": "x", "risk_level": "low", "response_zh": "測試", "slots": {}, "action": "speak"}
    wrapped = f"這是我的回答：\n{json.dumps(llm_output, ensure_ascii=False)}\n以上。"
    with patch("requests.post", return_value=_fake_response(wrapped)):
        br = OllamaBrain().generate("test")
    assert br.is_valid
    assert br.response_zh == "測試"


def test_connection_error_raises_ollama_brain_error_with_actionable_message():
    import requests

    with patch("requests.post", side_effect=requests.exceptions.ConnectionError()):
        with pytest.raises(OllamaBrainError, match="ollama serve"):
            OllamaBrain().generate("test")


class _FakeKB:
    """假知識庫，回傳固定結果，不用真的建SQLite——測試只在乎`generate()`
    有沒有正確把查到的entries用在prompt跟evidence_ids上，不在乎SQL比對
    邏輯本身(那是medical_kb.py自己測試的範圍，見test_medical_kb.py)。"""

    def __init__(self, entries: list[KnowledgeEntry]):
        self._entries = entries
        self.last_query: str | None = None

    def search(self, query: str, limit: int = 3) -> list[KnowledgeEntry]:
        self.last_query = query
        return self._entries


def test_kb_match_populates_evidence_ids_regardless_of_llm_output():
    """2026-09-10新增(RAG)：查到知識庫條目時，evidence_ids要填實際查到的
    entry id，而且**不能被LLM自己輸出的JSON覆蓋**——這個欄位的真實性不該
    讓LLM自己決定。"""
    entry = KnowledgeEntry(id="kb:1", question="血壓正常值是多少", answer="收縮壓小於120", category="高血壓")
    llm_output = {
        "intent": "medication_question", "risk_level": "low", "response_zh": "測試",
        "slots": {}, "action": "speak",
        "evidence_ids": ["llm自己亂填的id"],  # LLM輸出的evidence_ids應該被忽略
    }
    with patch("requests.post", return_value=_fake_response(llm_output)):
        br = OllamaBrain(kb=_FakeKB([entry])).generate("血壓正常值")

    assert br.evidence_ids == ["kb:1"]


def test_kb_match_injects_reference_context_as_extra_system_message():
    """查到知識庫條目時，要多加一則system訊息把參考資料傳給LLM，且要明確
    要求LLM仍然遵守JSON schema跟風險判斷原則(不能因為有參考資料就放寬
    「不自己編造醫療建議」的要求)——見_build_kb_context()的設計理由。"""
    entry = KnowledgeEntry(id="kb:1", question="血壓正常值是多少", answer="收縮壓小於120", category="高血壓")
    llm_output = {"intent": "x", "risk_level": "low", "response_zh": "測試", "slots": {}, "action": "speak"}

    captured_body = {}

    def _capture_post(url, json, timeout):
        captured_body.update(json)
        return _fake_response(llm_output)

    with patch("requests.post", side_effect=_capture_post):
        OllamaBrain(kb=_FakeKB([entry])).generate("血壓正常值是多少")

    messages = captured_body["messages"]
    assert len(messages) == 3  # system prompt + KB context + user message
    assert "血壓正常值是多少" in messages[1]["content"]
    assert "收縮壓小於120" in messages[1]["content"]
    assert "不自己編造醫療建議" in messages[1]["content"] or "不要跟這些內容矛盾" in messages[1]["content"]
    assert messages[-1]["role"] == "user"


def test_no_kb_match_keeps_original_two_message_prompt_and_empty_evidence():
    """沒查到任何知識庫條目時，prompt結構要跟RAG功能加入之前完全一樣
    (只有system prompt+user message兩則)，evidence_ids是空list——確保
    這個功能是純粹的加分項，沒有查到東西時不會影響原本的行為。"""
    llm_output = {"intent": "general_chat", "risk_level": "low", "response_zh": "測試", "slots": {}, "action": "speak"}

    captured_body = {}

    def _capture_post(url, json, timeout):
        captured_body.update(json)
        return _fake_response(llm_output)

    with patch("requests.post", side_effect=_capture_post):
        br = OllamaBrain(kb=_FakeKB([])).generate("今天天氣如何")

    assert len(captured_body["messages"]) == 2
    assert br.evidence_ids == []
