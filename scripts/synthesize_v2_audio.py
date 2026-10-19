"""
Contextual Pronunciation Benchmark v2 (in-corpus)的音檔合成: 跟v1的
splice_context_audio.py同一套原則(candidate用mms-tts-nan、前後文用
neurlang、各段peak normalize到同一音量, 見該檔案docstring)。

## 修正記錄(2026-08-27): 拿掉了錯誤的「語境需要調號齊全」限制

第一版曾經在這裡加了一個貪婪擴張/裁切語境的邏輯, 理由是誤以為前後文
也需要跟candidate一樣通過ChhoeTaigi詞庫的調號完整性檢查——這是錯的。
NeurlangTTSBackend合成前後文時吃的是**原始漢字文字**, 靠它自己內建的
phonemizer直接從漢字推導發音, 完全不查詢我們的ChhoeTaigi詞庫, 詞庫
缺不缺調號跟它毫無關係。「詞庫24%缺調號」只影響candidate本身要不要
走tailo_word_to_poj轉換給mms-tts-nan合成, 不影響前後文。

第一版因為這個誤判, 把前後文貪婪裁切到只剩1-2個字(例如「[後]會」、
「[鈴仔]。」), 母語者實際聽了之後回報「無法念整句」——這不是單純的
語境長度取捨, 是實作錯誤。修正後跟v1完全一致: 直接用原句在目標字前後
的完整字串當前後文, 不做任何裁切。

## 修正記錄(2026-09-07): 裁切每段音檔內建的頭尾靜音

母語者回報「斷句都超奇怪的」、「三段之間有明顯停頓/像三句話拼起來」。
實測發現: neurlang把每段前後文都當成一句「完整的話」來合成, 句尾自帶
最長達0.52秒的收尾靜音; mms-tts-nan合成candidate時開頭也可能帶多達
0.25秒的靜音。這些內建靜音疊加上我們額外插入的_PAUSE_SEC=0.25秒停頓,
會讓候選字前後的實際空白長達0.7~1秒——這才是聽起來像「三句話分開念」
的真正原因, 不是拼接技術本身的問題。

修正方式: 新增trim_silence(), 對前文/candidate/後文三段各自裁切頭尾
低於閾值的靜音(留一點pad避免咬字被切掉), 裁完才做peak normalize跟
接上統一的_PAUSE_SEC停頓, 讓停頓長度可控、不再被每段內建的靜音放大。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.tailo_to_poj import tailo_word_to_poj  # noqa: E402
from tw_hokkien_tts_pipeline.tts import NeurlangTTSBackend, TTSInput  # noqa: E402

PENDING_PATH = "/Users/heisenberg/.claude/jobs/70b35ce2/tmp/v2_pending_rows.json"
OUT_DIR = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_audio_v2"
)
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest_blind.jsonl")

_NEURLANG_SR = 22050
_PAUSE_SEC = 0.2
_TARGET_PEAK = 0.9
_SILENCE_THRESHOLD_RATIO = 0.02
_SILENCE_PAD_SEC = 0.03


def peak_normalize(audio, target_peak: float = _TARGET_PEAK):
    peak = float(abs(audio).max())
    if peak < 1e-8:
        return audio
    return audio * (target_peak / peak)


def trim_silence(audio, sr, threshold_ratio: float = _SILENCE_THRESHOLD_RATIO, pad_sec: float = _SILENCE_PAD_SEC):
    """裁掉音檔頭尾低於閾值的靜音, 只留一點pad避免咬字被切掉。"""
    import numpy as np

    peak = float(np.abs(audio).max())
    if peak < 1e-8:
        return audio
    threshold = threshold_ratio * peak
    nonsilent = np.where(np.abs(audio) > threshold)[0]
    if len(nonsilent) == 0:
        return audio
    pad = int(pad_sec * sr)
    start = max(0, nonsilent[0] - pad)
    end = min(len(audio), nonsilent[-1] + pad)
    return audio[start:end]


def main() -> None:
    import numpy as np
    import soundfile as sf
    import torch
    from scipy.signal import resample_poly
    from transformers import AutoTokenizer, VitsModel

    with open(PENDING_PATH, encoding="utf-8") as f:
        rows = json.load(f)

    neurlang = NeurlangTTSBackend()

    print("載入 facebook/mms-tts-nan ...")
    tokenizer = AutoTokenizer.from_pretrained("facebook/mms-tts-nan")
    mms_model = VitsModel.from_pretrained("facebook/mms-tts-nan")
    mms_model.eval()
    mms_sr = mms_model.config.sampling_rate

    os.makedirs(OUT_DIR, exist_ok=True)
    manifest_rows = []

    for row in rows:
        sentence = row["sentence"]
        surface = row["surface"]
        idx = sentence.find(surface)
        prefix_text = sentence[:idx]
        suffix_text = sentence[idx + len(surface) :]

        print(f"=== {row['id']} [{surface}] ===")
        print(f"  前文: {prefix_text!r}  後文: {suffix_text!r}")

        prefix_audio = None
        if prefix_text.strip():
            p = os.path.join(OUT_DIR, f"{row['id']}_prefix.wav")
            neurlang.synthesize(TTSInput(hanji_text=prefix_text, tailo_text=""), __import__("pathlib").Path(p))
            prefix_audio, sr = sf.read(p)
            assert sr == _NEURLANG_SR
            prefix_audio = trim_silence(prefix_audio, sr)
            prefix_audio = peak_normalize(prefix_audio)

        suffix_audio = None
        if suffix_text.strip():
            p = os.path.join(OUT_DIR, f"{row['id']}_suffix.wav")
            neurlang.synthesize(TTSInput(hanji_text=suffix_text, tailo_text=""), __import__("pathlib").Path(p))
            suffix_audio, sr = sf.read(p)
            assert sr == _NEURLANG_SR
            suffix_audio = trim_silence(suffix_audio, sr)
            suffix_audio = peak_normalize(suffix_audio)

        pause = np.zeros(int(_PAUSE_SEC * _NEURLANG_SR))

        entries = []
        for cand in row["candidates"]:
            poj = tailo_word_to_poj(cand)
            with torch.no_grad():
                inputs = tokenizer(poj, return_tensors="pt")
                output = mms_model(**inputs).waveform
            cand_audio = output.squeeze().numpy()
            cand_audio = trim_silence(cand_audio, mms_sr)
            if mms_sr != _NEURLANG_SR:
                cand_audio = resample_poly(cand_audio, _NEURLANG_SR, mms_sr)
            cand_audio = peak_normalize(cand_audio)

            pieces = []
            if prefix_audio is not None:
                pieces += [prefix_audio, pause]
            pieces.append(cand_audio)
            if suffix_audio is not None:
                pieces += [pause, suffix_audio]
            spliced = np.concatenate(pieces)

            out_filename = f"{row['id']}_{cand}_spliced.wav"
            sf.write(os.path.join(OUT_DIR, out_filename), spliced, samplerate=_NEURLANG_SR)
            entries.append({"candidate": cand, "audio_file": out_filename})
            print(f"    {cand} -> {out_filename}")

        manifest_rows.append(
            {
                "id": row["id"],
                "sentence": sentence,
                "sentence_zh": row["sentence_zh"],
                "target": surface,
                "entries": entries,
                "chosen_audio_file": None,
                "annotator_notes": None,
            }
        )

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        for r in manifest_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print()
    print(f"完成 {len(manifest_rows)}/{len(rows)} 列")
    print(f"manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
