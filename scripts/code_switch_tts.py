"""
中台混讀TTS原型：對「不會念的字」不要靜默丟棄，也不要硬用台語腔去唸，
改成該段落切換成中文語音（macOS內建`say`指令），跟台語語音（neurlang VITS）
拼接成一句完整的音檔。

背景：Protected Token pipeline證實可以在「翻譯文字」層面保留住「盤尼西林」
這種詞不被模型吃掉，但即使文字保留了，neurlang VITS還是會用台語腔去唸這幾個
字（pygoruut把所有漢字都轉成台語音標，沒有機制判斷「這個詞其實該用中文唸」）。
這支腳本補上音訊層的中台混讀。

作法很陽春：把句子按「哪些片段要用中文念」手動切段，中文片段用macOS `say`
（zh_TW語音）合成，台語片段用neurlang VITS合成，兩者都是22050Hz直接接起來。
這只是證明「聽起來可不可行」的原型，不是正式的自動判斷系統——真正要用，
還需要：
1. 自動判斷「這個詞該不該中文唸」（哪些詞觸發：不在教育部辭典、pygoruut
   轉換失敗、或是特定領域詞白名單）
2. 兩種語音銜接處的自然度處理（音量/語速對齊，這裡完全沒做）

執行：python scripts/code_switch_tts.py
"""
import os
import subprocess

import numpy as np
import soundfile as sf

MODEL_DIR = "models/neurlang-vits-suisiann"
MANDARIN_VOICE = "Meijia"
OUT_DIR = "/tmp/code_switch_test"


def synth_hokkien(syn, text):
    if not text:
        return np.array([], dtype=np.float32)
    wav = syn.tts(text)
    return np.array(wav, dtype=np.float32)


def synth_mandarin(text, tmp_path="/tmp/_mandarin_seg.aiff"):
    if not text:
        return np.array([], dtype=np.float32)
    subprocess.run(["say", "-v", MANDARIN_VOICE, "-o", tmp_path, text], check=True)
    data, sr = sf.read(tmp_path)
    assert sr == 22050, f"取樣率不是22050，要resample：{sr}"
    return data.astype(np.float32)


def silence(seconds=0.15, sr=22050):
    return np.zeros(int(seconds * sr), dtype=np.float32)


def build_mixed_audio(syn, segments):
    """segments: [(lang, text), ...]，lang是'nan'或'zh'"""
    parts = []
    for lang, text in segments:
        if lang == "nan":
            parts.append(synth_hokkien(syn, text))
        elif lang == "zh":
            parts.append(synth_mandarin(text))
        else:
            raise ValueError(lang)
        parts.append(silence(0.1))
    return np.concatenate(parts) if parts else np.array([], dtype=np.float32)


if __name__ == "__main__":
    from TTS.utils.synthesizer import Synthesizer

    os.makedirs(OUT_DIR, exist_ok=True)
    print("載入 neurlang VITS...")
    syn = Synthesizer(
        tts_checkpoint=os.path.join(MODEL_DIR, "best_model.pth"),
        tts_config_path=os.path.join(MODEL_DIR, "config.json"),
    )

    test_cases = {
        "01_penicillin_全台語腔（對照組，念錯）": [("nan", "你對盤尼西林敢會過敏？")],
        "02_penicillin_中台混讀": [
            ("nan", "你對"), ("zh", "盤尼西林"), ("nan", "敢會過敏？"),
        ],
        "03_insulin_全台語腔（對照組）": [("nan", "阿媽，你這罐胰島素愛囥冰箱冷凍。")],
        "04_insulin_中台混讀": [
            ("nan", "阿媽，你這罐"), ("zh", "胰島素"), ("nan", "愛囥冰箱冷凍。"),
        ],
    }

    for name, segments in test_cases.items():
        audio = build_mixed_audio(syn, segments)
        out_path = os.path.join(OUT_DIR, f"{name}.wav")
        sf.write(out_path, audio, samplerate=22050)
        print(f"{name} -> {out_path}")

    print(f"\n完成，全部在 {OUT_DIR}")
