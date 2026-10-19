"""從音檔本身抽取韻律(prosody)指標，用來量化比較真實錄音跟TTS合成
輸出的差異——不是猜測，是實測數據。

## 背景

`reports/moe_corpus_taigi_analysis.md`的分析都是文字/音素層面(拿台羅
數字調當ground truth比對IPA)，沒有動到音檔本身。這個模組是第一次直接
分析音檔的聲學特徵：初步測試(1個問句+1個敘述句樣本)發現TTS合成的音高
標準差(34.5Hz)只有真實錄音(97.6Hz)的1/3左右，但那只是n=1的觀察，
使用者要求先建立完整的prosody baseline、擴大到50-100句確認問題是不是
真的一致存在，再決定要不要根據這個做微調。

## 五個指標

- **F0 range / F0 std / F0 mean**：基頻(音高)的範圍、標準差、平均值，
  用`librosa.pyin`抓，只計算有聲(voiced)片段的數值。標準差是「表現力」
  的量化指標——越低代表音高變化越少、聽起來越平板。
- **voiced_ratio**：有聲音框佔全部音框的比例(不是佔靜音，是佔整個
  分析窗格)。
- **pause相關(num_pauses/total_pause_sec/pause_ratio)**：用
  `librosa.effects.split`抓出「非靜音」的時間區段，區段之間(不含開頭
  結尾)的間隔就是內部停頓；用來量化「停頓次數/總停頓時長/停頓佔整句
  比例」。

**這個模組只負責量測，不負責判斷「多少才算好」**——沒有客觀的「正確」
數值，只能拿真實錄音當對照組，看TTS合成輸出跟這個對照組差多少。
"""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np


@dataclass
class ProsodyMetrics:
    duration_sec: float
    f0_min: float | None
    f0_max: float | None
    f0_range: float | None
    f0_std: float | None
    f0_mean: float | None
    voiced_ratio: float
    num_pauses: int
    total_pause_sec: float
    pause_ratio: float


def extract_prosody_metrics(y: np.ndarray, sr: int, top_db: float = 30.0) -> ProsodyMetrics:
    """從waveform(`y`, float array)+取樣率(`sr`)抽取prosody指標。

    `top_db`是`librosa.effects.split`判斷「靜音」的門檻(相對於全音檔
    最大音量低多少dB算靜音)，預設30dB是librosa的常見預設值，沒有針對
    這批語料特別調過。
    """
    duration_sec = len(y) / sr

    f0, voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr
    )
    voiced_f0 = f0[~np.isnan(f0)]
    if len(voiced_f0) >= 2:
        f0_min = float(np.min(voiced_f0))
        f0_max = float(np.max(voiced_f0))
        f0_range = f0_max - f0_min
        f0_std = float(np.std(voiced_f0))
        f0_mean = float(np.mean(voiced_f0))
    else:
        f0_min = f0_max = f0_range = f0_std = f0_mean = None

    voiced_ratio = float(np.sum(~np.isnan(f0)) / len(f0)) if len(f0) > 0 else 0.0

    intervals = librosa.effects.split(y, top_db=top_db)
    num_pauses = max(0, len(intervals) - 1)
    total_pause_sec = 0.0
    for i in range(len(intervals) - 1):
        gap_samples = intervals[i + 1][0] - intervals[i][1]
        total_pause_sec += gap_samples / sr
    pause_ratio = total_pause_sec / duration_sec if duration_sec > 0 else 0.0

    return ProsodyMetrics(
        duration_sec=duration_sec,
        f0_min=f0_min,
        f0_max=f0_max,
        f0_range=f0_range,
        f0_std=f0_std,
        f0_mean=f0_mean,
        voiced_ratio=voiced_ratio,
        num_pauses=num_pauses,
        total_pause_sec=total_pause_sec,
        pause_ratio=pause_ratio,
    )


def load_and_extract(path: str, top_db: float = 30.0) -> ProsodyMetrics:
    y, sr = librosa.load(path, sr=None)
    return extract_prosody_metrics(y, sr, top_db=top_db)


def effective_voiced_duration_sec(y: np.ndarray, sr: int, top_db: float = 30.0) -> float:
    """去掉開頭/結尾的靜音後的「有效內容」時長，不是整個wav檔案長度。

    用`librosa.effects.trim`(只去頭尾，不像`extract_prosody_metrics`用的
    `effects.split`會把整段切成很多段)——真實錄音跟合成音檔在開頭/結尾
    留白習慣可能不一樣，直接比較整檔長度(`duration_sec`)可能把這種
    「留白差異」誤算成「講話速度差異」，這裡單獨算出「trim掉頭尾靜音
    後還剩多久」，排除這個干擾因素。
    """
    y_trimmed, _ = librosa.effects.trim(y, top_db=top_db)
    return len(y_trimmed) / sr


def per_char_duration_sec(y: np.ndarray, sr: int, char_count: int, top_db: float = 30.0) -> float | None:
    """去頭尾靜音後的有效時長，除以字數，得到「平均每個字花多少秒」。

    `char_count`由呼叫端算好傳進來(通常是去除標點後的漢字數)，這個函式
    不處理文字，只負責時長計算。`char_count<=0`回傳None(避免除以0)。
    """
    if char_count <= 0:
        return None
    return effective_voiced_duration_sec(y, sr, top_db=top_db) / char_count
