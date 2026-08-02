"""
自動判斷「這個詞台語講法成不成熟」，不成熟就切到中文語音、成熟就用台語語音，
分段合成後拼接成一句完整音檔。取代`code_switch_tts.py`原本手動指定分段的做法。

「成熟」的判斷原本設計用兩個訊號，實測後發現教育部辭典覆蓋率這個訊號
會誤殺一大堆完全正常的詞（見下方「踩過的坑」），**目前只用一個訊號**：

- pygoruut/neurlang的tokenizer能不能把這個詞完整轉成台語音標——見
  scripts/safety_checks.py::check_unconverted_characters，這是實測過
  「哪些字會被靜默丟棄」的機制，不是憑空猜的。轉不完整（有字元被丟棄）
  就標記成不成熟，改用中文語音（macOS內建`say`，zh_TW語音）合成，
  其餘詞維持台語語音（neurlang VITS）。

## 踩過的坑：教育部辭典覆蓋率不能當「這個詞能不能唸」的訊號

原本以為「詞不在教育部辭典裡」代表官方沒收錄公認台語講法、該判不成熟。
實測發現「需要」「過敏」這種完全正常、pygoruut能正確轉音標、neurlang
講得很順的詞，也不在教育部辭典裡——因為**教育部辭典收錄的是「有特殊
台語用字/讀音、值得特別收錄」的詞，不是「所有講得出來的詞」的完整
清單**。很多跟中文共用漢字、用文讀音的常見詞（尤其現代/書面語詞彙）
根本不會有獨立詞條，不是因為台語不會這樣講。這個訊號拿掉了，只留
pygoruut這個有直接驗證過的訊號。

限制（誠實記錄，不要覆蓋成看起來比實際成熟）：
- 用jieba斷詞，不是台語專用斷詞器，詞界不一定準，可能把成熟詞跟不成熟
  詞切在一起、或切錯位置
- pygoruut能轉出音標不等於「轉得對」，只能保證「有轉」，這個判斷只能
  抓「完全轉不出來」這種最嚴重的情況，抓不到「轉出來但唸得不夠道地」
  這種較輕微的問題
- 沒有做語速/音量/音高在銜接處的對齊，兩段語音接起來可能還是聽得出斷點

執行：python scripts/mature_word_code_switch.py
"""
import json
import os
import subprocess

import jieba
import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "models", "neurlang-vits-suisiann")
MANDARIN_VOICE = "Meijia"

PUNCT = set("。，、；：？！「」『』（）,.;:!?()— -\n\t ")


class MaturityJudge:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def is_mature(self, word):
        if word in PUNCT or not word.strip():
            return True  # 標點符號不用判斷，維持原本流程處理
        if all(ord(c) < 0x2E80 for c in word):
            return True  # 非中文字元（英數字等），不強制判斷，交給原本流程
        self.tokenizer.not_found_characters = []
        self.tokenizer.text_to_ids(word)
        dropped = [c for c in self.tokenizer.not_found_characters if c not in PUNCT]
        return len(dropped) == 0


def segment_and_classify(text, judge):
    words = list(jieba.cut(text))
    segments = []
    for w in words:
        lang = "nan" if judge.is_mature(w) else "zh"
        segments.append((lang, w))
    # 合併相鄰同語言的片段，減少不必要的切換次數
    merged = []
    for lang, w in segments:
        if merged and merged[-1][0] == lang:
            merged[-1] = (lang, merged[-1][1] + w)
        else:
            merged.append((lang, w))
    return merged


def synth_hokkien(syn, text):
    if not text.strip():
        return np.array([], dtype=np.float32)
    wav = syn.tts(text)
    return np.array(wav, dtype=np.float32)


def synth_mandarin(text, tmp_path="/tmp/_mature_mandarin_seg.aiff"):
    if not text.strip():
        return np.array([], dtype=np.float32)
    subprocess.run(["say", "-v", MANDARIN_VOICE, "-o", tmp_path, text], check=True)
    data, sr = sf.read(tmp_path)
    assert sr == 22050, f"取樣率不是22050：{sr}"
    return data.astype(np.float32)


def silence(seconds=0.12, sr=22050):
    return np.zeros(int(seconds * sr), dtype=np.float32)


def synthesize(syn, judge, text):
    segments = segment_and_classify(text, judge)
    parts = []
    for lang, seg_text in segments:
        if lang == "nan":
            parts.append(synth_hokkien(syn, seg_text))
        else:
            parts.append(synth_mandarin(seg_text))
        parts.append(silence())
    audio = np.concatenate(parts) if parts else np.array([], dtype=np.float32)
    return audio, segments


if __name__ == "__main__":
    from TTS.utils.synthesizer import Synthesizer

    out_dir = "/tmp/mature_word_test"
    os.makedirs(out_dir, exist_ok=True)

    print("載入 neurlang VITS...")
    syn = Synthesizer(
        tts_checkpoint=os.path.join(MODEL_DIR, "best_model.pth"),
        tts_config_path=os.path.join(MODEL_DIR, "config.json"),
    )
    judge = MaturityJudge(syn.tts_model.tokenizer)

    test_sentences = [
        "你對盤尼西林敢會過敏？",
        "護理站共你叫一台輪椅來予你去做電腦斷層掃描。",
        "阿媽，你這罐胰島素愛囥冰箱冷凍。",
        "我需要啉水。",
    ]

    for i, text in enumerate(test_sentences):
        audio, segments = synthesize(syn, judge, text)
        out_path = f"{out_dir}/{i:02d}.wav"
        sf.write(out_path, audio, samplerate=22050)
        seg_str = " | ".join(f"{lang}:{w}" for lang, w in segments)
        print(f"[{i:02d}] {text}\n  分段：{seg_str}\n  -> {out_path}\n")
