"""
讀取已寫出的 wav 檔、量測基本品質指標。

靜音振幅門檻(0.01)跟 scripts/tts_benchmark/metrics.py 用同一個值，避免repo內
兩套不同標準；這裡獨立成一個小模組而不是直接 import scripts/ 底下的版本，
是因為 tw_hokkien_tts_pipeline 設計成自己可以獨立安裝/測試，不依賴scripts/
的路徑結構。

直接讀寫出的 wav 檔案（而不是backend內部的記憶體陣列），是為了確保這裡量到
的數字反映「使用者實際會拿到的檔案」，同時可以抓到「檔案寫壞了」這類問題。
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

SILENCE_AMPLITUDE_THRESHOLD = 0.01


@dataclass
class WavMetrics:
    sample_rate: int
    channels: int
    duration_sec: float
    non_silence_ratio: float
    has_nan: bool
    is_all_zero: bool
    rms: float


def read_wav_metrics(path: str | Path) -> WavMetrics:
    import numpy as np

    with wave.open(str(path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    duration_sec = (n_frames / sample_rate) if sample_rate else 0.0

    if n_frames == 0:
        return WavMetrics(
            sample_rate=sample_rate, channels=channels, duration_sec=0.0,
            non_silence_ratio=0.0, has_nan=False, is_all_zero=True, rms=0.0,
        )

    if sampwidth == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    elif sampwidth == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float64) / 2147483648.0
    elif sampwidth == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128.0
    else:
        raise ValueError(f"不支援的取樣寬度: {sampwidth} bytes ({path})")

    has_nan = bool(np.isnan(samples).any())
    is_all_zero = bool(np.all(samples == 0))
    rms = float(np.sqrt(np.mean(samples ** 2))) if not has_nan else float("nan")
    non_silence_ratio = float(np.mean(np.abs(samples) >= SILENCE_AMPLITUDE_THRESHOLD))

    return WavMetrics(
        sample_rate=sample_rate,
        channels=channels,
        duration_sec=round(duration_sec, 3),
        non_silence_ratio=round(non_silence_ratio, 4),
        has_nan=has_nan,
        is_all_zero=is_all_zero,
        rms=round(rms, 5) if not has_nan else rms,
    )
