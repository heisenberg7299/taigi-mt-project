"""duration_predictor_diagnostics.py測試：驗證直接探測duration predictor
輸出的邏輯不會crash、回傳的統計數據合理(見模組docstring的完整背景)。

需要真的coqui-tts+neurlang模型權重才會跑，這個模組的唯一功能就是跟
真實模型的內部結構(text_encoder/duration_predictor)互動，沒有可以
獨立測試的純邏輯部分，跟`test_tts_neurlang_smoke.py`同樣的慣例。
"""

from __future__ import annotations

import importlib.util

import pytest

_HAS_COQUI_TTS = importlib.util.find_spec("TTS") is not None
try:
    from tw_hokkien_tts_pipeline.tts import NeurlangTTSBackend

    _model_dir = NeurlangTTSBackend._DEFAULT_MODEL_DIR
    _MODEL_DIR_AVAILABLE = (_model_dir / "best_model.pth").exists() and (_model_dir / "config.json").exists()
except ImportError:
    _MODEL_DIR_AVAILABLE = False


@pytest.mark.skipif(
    not (_HAS_COQUI_TTS and _MODEL_DIR_AVAILABLE),
    reason="需要coqui-tts+neurlang模型權重都到位才會跑",
)
def test_probe_duration_predictor_returns_sane_stats_for_normal_model():
    from TTS.utils.synthesizer import Synthesizer
    from tw_hokkien_tts_pipeline.duration_predictor_diagnostics import probe_duration_predictor

    synth = Synthesizer(
        tts_checkpoint=str(NeurlangTTSBackend._DEFAULT_MODEL_DIR / "best_model.pth"),
        tts_config_path=str(NeurlangTTSBackend._DEFAULT_MODEL_DIR / "config.json"),
    )
    result = probe_duration_predictor(synth.tts_model, "你好")

    assert not result.has_nan
    assert not result.has_inf
    # 正常模型的duration predictor輸出，w(每個音素預測的frame數)應該是
    # 合理的正數範圍，不會是離譜的天文數字(對應之前實測到的崩潰checkpoint
    # 會產生的異常輸出)
    assert 0 < result.w_mean < 100
