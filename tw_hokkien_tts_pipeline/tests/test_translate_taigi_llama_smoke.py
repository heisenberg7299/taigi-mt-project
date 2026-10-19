"""
TaigiLlamaTranslationBackend 真實 smoke test：實際呼叫本機Ollama跑翻譯,
不是mock。連不到Ollama時自動skip(不是fail), 不會擋下其他測試。

這裡只驗證「串接本身動起來、Protected Token沒有在真實LLM手上被弄壞、
安全檢查層有跑」，**不驗證翻譯品質**——品質問題見
reports/safety_critical_translation_failures.md，那是另一回事，這個
backend本身就明確定位成「只當baseline，不代表結果安全」(見docstring)。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from tw_hokkien_tts_pipeline.config import PipelineConfig
from tw_hokkien_tts_pipeline.pipeline import Pipeline

OLLAMA_URL = "http://localhost:11434/api/tags"


def _ollama_available() -> bool:
    try:
        resp = requests.get(OLLAMA_URL, timeout=2)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama沒有在跑(localhost:11434)，先執行 ollama serve 才能跑這個smoke test",
)


def test_taigi_llama_backend_translates_and_preserves_protected_tokens(tmp_path: Path):
    config = PipelineConfig(
        output_dir=tmp_path,
        translation_backend="taigi_llama",
        segmentation_backend="mock",
        tts_backend="mock",
    )
    pipeline = Pipeline(
        config=config,
        drug_lexicon={"盤尼西林": "puân-nî-se-lîm"},
    )
    result = pipeline.run("請記得在晚餐後服用盤尼西林。", out_filename="test_taigi_llama.wav")

    # 1. 確實是真實backend在跑, 不是mock
    assert result.translation.backend_name == "taigi-llama"
    assert result.translation.translated_text  # 不能是空字串

    # 2. Protected Token在真實LLM手上沒有被弄丟/複製 (這是接入真實翻譯後
    #    才需要驗證的, mock翻譯是決定性字典替換不會出這種問題)
    assert result.protected_token_integrity["ok"] is True
    assert result.protected_token_integrity["missing"] == []
    assert result.protected_token_integrity["duplicated"] == []

    # 3. 藥名文字確實還原回hanji_text, 沒有佔位符外漏
    assert "盤尼西林" in result.hanji_text
    assert "DRUGA" not in result.hanji_text

    # 4. 安全檢查層有跑並回傳結果 (不代表一定通過, 只驗證有跑)
    assert set(result.safety_checks.keys()) == {
        "negation", "number_consistency", "medical_terms", "length_anomaly", "trap_words",
    }

    # 5. debug trace有記錄
    debug_dict = result.to_debug_dict()
    assert debug_dict["translation_backend"] == "taigi-llama"
    assert debug_dict["protected_token_integrity"]["ok"] is True
