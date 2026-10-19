"""prosody_baseline.py測試：驗證韻律指標抽取邏輯(見模組docstring的
完整背景)。

用合成的正弦波+靜音片段測試機制本身(不需要真的語料庫音檔)；真實音檔
的smoke test見test_extract_prosody_metrics_on_real_corpus_audio(需要
本機有下載過的語料庫檔案，沒有就skip)。
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from tw_hokkien_tts_pipeline.prosody_baseline import (
    extract_prosody_metrics,
    effective_voiced_duration_sec,
    per_char_duration_sec,
)

SR = 16000


def _sine(freq: float, duration_sec: float, sr: int = SR, amplitude: float = 0.5) -> np.ndarray:
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _silence(duration_sec: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(sr * duration_sec), dtype=np.float32)


def test_duration_matches_waveform_length():
    y = _sine(150, 2.0)
    metrics = extract_prosody_metrics(y, SR)
    assert abs(metrics.duration_sec - 2.0) < 0.01


def test_constant_pitch_sine_wave_has_near_zero_f0_std():
    """單一頻率的正弦波，音高標準差應該接近0(沒有變化)——用來驗證
    「標準差=表現力」這個指標機制本身是通的。"""
    y = _sine(150, 1.5)
    metrics = extract_prosody_metrics(y, SR)
    assert metrics.f0_std is not None
    assert metrics.f0_std < 5.0  # 幾乎沒有變化


def test_no_internal_pause_when_audio_is_continuous():
    y = _sine(150, 1.0)
    metrics = extract_prosody_metrics(y, SR)
    assert metrics.num_pauses == 0
    assert metrics.total_pause_sec == 0.0


def test_detects_internal_pause_between_two_sound_segments():
    """兩段聲音中間夾一段明顯的靜音，應該被偵測成1個內部停頓。"""
    y = np.concatenate([_sine(150, 1.0), _silence(0.5), _sine(150, 1.0)])
    metrics = extract_prosody_metrics(y, SR)
    assert metrics.num_pauses == 1
    assert 0.3 < metrics.total_pause_sec < 0.7  # 抓到的停頓長度跟實際插入的0.5秒差不多
    assert 0 < metrics.pause_ratio < 1


def test_voiced_ratio_lower_when_half_the_audio_is_silence():
    y_all_voiced = _sine(150, 2.0)
    y_half_silence = np.concatenate([_sine(150, 1.0), _silence(1.0)])
    metrics_voiced = extract_prosody_metrics(y_all_voiced, SR)
    metrics_half = extract_prosody_metrics(y_half_silence, SR)
    assert metrics_half.voiced_ratio < metrics_voiced.voiced_ratio


def test_effective_voiced_duration_excludes_leading_and_trailing_silence():
    """開頭/結尾各加2秒靜音，去頭尾之後的有效時長應該只剩中間那1秒
    的聲音，不含前後的留白。"""
    y = np.concatenate([_silence(2.0), _sine(150, 1.0), _silence(2.0)])
    effective = effective_voiced_duration_sec(y, SR)
    assert 0.8 < effective < 1.5  # 允許trim邊界抓得不是剛好1.0秒的誤差


def test_per_char_duration_divides_effective_duration_by_char_count():
    y = np.concatenate([_silence(1.0), _sine(150, 2.0), _silence(1.0)])
    per_char = per_char_duration_sec(y, SR, char_count=4)
    effective = effective_voiced_duration_sec(y, SR)
    assert abs(per_char - effective / 4) < 0.01


def test_per_char_duration_returns_none_for_zero_char_count():
    y = _sine(150, 1.0)
    assert per_char_duration_sec(y, SR, char_count=0) is None


_REAL_AUDIO_PATH = (
    "/Users/heisenberg/Downloads/tat_moe_corpora_1mic_extracted/TAT-MOE-train-lavalier/"
    "TAT-MOE-train-lavalier/39700d452c77592c9710a4a34c6fe97d6150e26d550a5cfa553b0177d7b23e95-master/"
    "lavalier/TH_THF1001/A037-2.1.wav"
)


@pytest.mark.skipif(
    not os.path.exists(_REAL_AUDIO_PATH),
    reason="需要本機已下載TAT-MOE語料庫才會跑，這是唯一用真實音檔的測試",
)
def test_extract_prosody_metrics_on_real_corpus_audio():
    """真實smoke test：確認對真實錄音檔案抽取指標不會crash、數值落在
    合理範圍內(不驗證絕對數值，只驗證機制能跑、結果不是荒謬的)。"""
    import librosa

    from tw_hokkien_tts_pipeline.prosody_baseline import load_and_extract

    metrics = load_and_extract(_REAL_AUDIO_PATH)
    assert metrics.duration_sec > 0
    assert metrics.f0_mean is not None
    assert 50 < metrics.f0_mean < 500  # 人聲基頻合理範圍
    assert 0 <= metrics.voiced_ratio <= 1
