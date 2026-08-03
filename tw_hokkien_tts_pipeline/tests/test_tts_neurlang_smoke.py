"""
NeurlangTTSBackend 真實 smoke test：實際載入模型、實際跑推論、實際檢查
輸出的 wav 檔案品質，不是mock。

跟 test_pipeline.py 裡7項針對mock流程的測試不同，這個檔案需要：
  - 已下載好的 models/neurlang-vits-suisiann/ 權重
  - venv 是 transformers<5 (coqui-tts的要求)

兩者缺一都會直接 skip（不是fail），所以在沒有這些依賴的環境(例如一般CI)
執行 `pytest tests/` 一樣會全過，只是這個檔案的測試顯示skipped，不會讓
既有7項回歸測試連帶被擋下來。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tw_hokkien_tts_pipeline.config import PipelineConfig
from tw_hokkien_tts_pipeline.pipeline import Pipeline
from tw_hokkien_tts_pipeline.tts import NeurlangTTSBackend

_MODEL_DIR = NeurlangTTSBackend._DEFAULT_MODEL_DIR
_MODEL_AVAILABLE = (_MODEL_DIR / "best_model.pth").exists() and (_MODEL_DIR / "config.json").exists()

coqui_tts = pytest.importorskip(
    "TTS.utils.synthesizer",
    reason="coqui-tts 未安裝或 transformers 版本不對 (neurlang需要 <5)",
)

pytestmark = pytest.mark.skipif(
    not _MODEL_AVAILABLE,
    reason=f"找不到neurlang模型權重: {_MODEL_DIR}，先準備好權重才能跑這個smoke test",
)


def test_neurlang_backend_produces_real_audio(tmp_path: Path):
    config = PipelineConfig(
        output_dir=tmp_path,
        tts_backend="neurlang",
    )
    pipeline = Pipeline(
        config=config,
        drug_lexicon={"盤尼西林": "puân-nî-se-lîm"},
    )
    result = pipeline.run("請記得在晚餐後服用盤尼西林。", out_filename="output_neurlang.wav")
    tts = result.tts

    # 1. 確實是neurlang在跑, 不是偷偷fallback回mock
    assert tts.backend_name == "neurlang"
    assert tts.text_format == "hanji"
    # 實際送進模型的應該是台語漢字(含還原後的藥名), 不是台羅或含佔位符
    assert "DRUGA" not in tts.text
    assert "盤尼西林" in tts.text

    # 2. wav檔案確實產生
    assert tts.wav_path.exists()
    assert tts.wav_path.name == "output_neurlang.wav"

    # 3. 時長合理 (這句約15字, 不應該是0.1秒或超過30秒)
    assert tts.duration_sec is not None
    assert 0.5 < tts.duration_sec < 30.0

    # 4. 非靜音比例達標 (不是mock beep、不是幾乎全靜音的失敗案例)
    #    參考 scripts/tts_benchmark/metrics.py 的門檻: 正常語音約46-52%非靜音,
    #    這裡用比較寬鬆的下限(20%)當smoke test, 不追求精確品質判定
    assert tts.non_silence_ratio is not None
    assert tts.non_silence_ratio > 0.2

    # 5. sample rate / 聲道 / waveform 正常, 沒有 NaN 或全零訊號
    #    (NeurlangTTSBackend.synthesize 本身已經對全零/NaN做檢查會raise,
    #    這裡再直接讀檔驗證一次, 確保寫出來的檔案本身也沒問題)
    from tw_hokkien_tts_pipeline.audio_metrics import read_wav_metrics

    metrics = read_wav_metrics(tts.wav_path)
    assert metrics.sample_rate > 0
    assert metrics.channels == 1
    assert not metrics.has_nan
    assert not metrics.is_all_zero

    # 6. debug trace 有記錄完整的TTS層資訊
    debug_dict = result.to_debug_dict()
    assert debug_dict["tts"]["backend"] == "neurlang"
    assert debug_dict["tts"]["model_id"] == NeurlangTTSBackend.model_id
    assert debug_dict["tts"]["inference_sec"] is not None
    assert debug_dict["tts"]["duration_sec"] is not None
    assert debug_dict["tts"]["non_silence_ratio"] is not None

    # 7. Protected Token文字保留成功(藥名漢字確實在最終文字裡)，
    #    但neurlang不消費人工校正過的台羅讀音，發音不能宣稱受保護
    assert result.protected_text_preserved is True
    assert result.protected_pronunciation_enforced is False
    assert debug_dict["protected_text_preserved"] is True
    assert debug_dict["protected_pronunciation_enforced"] is False


def test_neurlang_backend_raises_on_missing_model(tmp_path: Path):
    """模型路徑不存在時應該清楚報錯, 不能偷偷fallback成mock。"""
    backend = NeurlangTTSBackend(model_dir=tmp_path / "does_not_exist")
    from tw_hokkien_tts_pipeline.tts import TTSInput

    with pytest.raises(FileNotFoundError):
        backend.synthesize(
            TTSInput(hanji_text="你好", tailo_text="lí-hó"),
            tmp_path / "should_not_be_created.wav",
        )
    assert not (tmp_path / "should_not_be_created.wav").exists()
