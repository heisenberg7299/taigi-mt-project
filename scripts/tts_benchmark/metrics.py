"""
統一的客觀量測，所有adapter產生的音檔都套同一套算法，
確保跨模型比較時用的是同一把尺（見 reports/stage4_tts_candidates.md
討論過的「不要每次重新發明評分標準」）。
"""
import numpy as np

SILENCE_AMPLITUDE_THRESHOLD = 0.01  # 低於這個振幅視為靜音
FAIL_SILENCE_RATIO = 0.75  # 高於這個靜音比例直接判定失敗
# 依據：實測正常語音（羅馬字/英文/漢字成功案例）靜音比例約46-52%，
# speecht5對漢字輸入失敗時是93-94%，兩者中間留足夠安全邊界。


def compute_audio_metrics(samples: np.ndarray, sample_rate: int, wall_clock_sec: float):
    duration_sec = len(samples) / sample_rate if sample_rate else 0.0
    if duration_sec == 0:
        return {
            "audio_duration_sec": 0.0,
            "rms": 0.0,
            "silence_ratio": 1.0,
            "effective_speech_sec": 0.0,
            "rtf": None,
        }
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    silence_ratio = float(np.mean(np.abs(samples) < SILENCE_AMPLITUDE_THRESHOLD))
    effective_speech_sec = duration_sec * (1 - silence_ratio)
    rtf = wall_clock_sec / duration_sec if duration_sec > 0 else None
    return {
        "audio_duration_sec": round(duration_sec, 3),
        "rms": round(rms, 5),
        "silence_ratio": round(silence_ratio, 4),
        "effective_speech_sec": round(effective_speech_sec, 3),
        "rtf": round(rtf, 3) if rtf is not None else None,
    }


def decide(generation_success: bool, metrics: dict, error: str = None):
    """自動判定能判定的部分（生成有沒有成功、靜音比例門檻），
    可懂度跟漏字率無法自動判斷，統一先標 pending_human_review，
    等母語者用驗證平台補評分。"""
    if not generation_success:
        return "fail_error"
    if metrics.get("silence_ratio", 1.0) > FAIL_SILENCE_RATIO:
        return "fail_silence"
    return "pending_human_review"
