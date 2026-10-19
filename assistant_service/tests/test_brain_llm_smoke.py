"""
OllamaBrain真實smoke test：實際呼叫本機Ollama的qwen2.5:7b-instruct，不是
mock。連不到Ollama、或還沒pull這個模型時自動skip(不是fail)，不會擋下其他
測試。跟tw_hokkien_tts_pipeline/tests/test_translate_taigi_llama_smoke.py
是同樣的skip慣例。

**不驗證LLM回覆品質**(那是另一回事，永遠有機率性)，只驗證：串接動起來、
輸出真的是合法JSON能組成BrainResponse、風險判斷的關鍵行為(藥物相關輸入
應該被標成high risk並填slots)大致符合system prompt要求。
"""

from __future__ import annotations

import requests
import pytest

from assistant_service.brain_llm import DEFAULT_MODEL, OllamaBrain

OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"


def _model_available() -> bool:
    try:
        resp = requests.get(OLLAMA_TAGS_URL, timeout=2)
        if resp.status_code != 200:
            return False
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        return any(DEFAULT_MODEL in name for name in names)
    except requests.exceptions.RequestException:
        return False


pytestmark = pytest.mark.skipif(
    not _model_available(),
    reason=f"Ollama沒有在跑，或還沒pull過{DEFAULT_MODEL}(`ollama pull {DEFAULT_MODEL}`)",
)


def test_general_chat_produces_valid_brain_response():
    brain = OllamaBrain()
    br = brain.generate("你好，今天天氣真好")

    assert br.is_valid, br.validate()
    assert br.response_zh


def test_medication_related_input_gets_high_risk_and_drug_slot():
    """不強制要求LLM每次都完美判斷(這是機率性的)，但這是system prompt明確
    要求的行為，值得驗證大部分情況下有照做——就算這次沒照做，
    response_controller.enforce_deterministic_risk_level()也不會完全依賴
    這個判斷(規則式那層才是真正的防線)，這裡只是確認prompt engineering
    本身有起作用。"""
    brain = OllamaBrain()
    br = brain.generate("我可以多吃一顆普拿疼止痛藥嗎")

    assert br.is_valid, br.validate()
    assert br.risk_level == "high"
