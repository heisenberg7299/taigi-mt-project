"""
把「整句語境」跟「candidate讀音」分開合成再接起來, 繞過ChhoeTaigi詞庫
24%詞條缺調號數字、導致整句沒辦法用同一個backend一次合成的問題(見
synthesize_blind_audio_sentence.py的說明與失敗紀錄, 0/24列成功)。

## 做法

  1. 句子前後文(目標字/詞以外的部分)用NeurlangTTSBackend合成——這個
     backend吃漢字, 內建phonemizer自己決定發音, 完全不需要查詞庫調號,
     所以不受詞庫缺調號問題影響。
  2. 目標字/詞的candidate讀音沿用synthesize_blind_audio.py已經合成好的
     mms-tts-nan音檔(這些是唯一能保證「使用者指定的那個候選讀音」的
     backend, 因為neurlang不接受指定讀音, 見tts.py的說明)。
  3. 前文 + candidate音檔 + 後文, 用soundfile讀出來, 統一resample成
     neurlang的sample rate後直接串接(中間插入短暫靜音), 存成新的音檔。

## 已知的不完美之處(誠實列出, 不是隱藏)

  - 兩個backend是分開合成的, 銜接處沒有真正的語音連貫性(韻律、語速、
    音色不會自然過渡), 聽起來會有明顯的拼接感, 不是天然一句話的語調。
  - neurlang的phonemizer自己決定了前後文其他字的發音, 這些發音沒有
    被本專案的詞庫/pronunciation_overrides.py驗證過, 跟目標字候選讀音
    的可信度不是同一個等級。
  - 只能涵蓋16/24列(candidate本身缺調號的8列, 這裡一樣沒辦法做,
    因為mms-tts-nan候選音檔根本合成不出來)。

## 音量標準化(2026-08-27修正, 第一輪16列的音檔沒有這個修正)

第一版拼接直接把兩個backend的原始振幅接在一起, 沒注意到兩個TTS系統
輸出的音量天差地遠：neurlang輸出的前後文平均峰值接近1.0(滿量), 但
mms-tts-nan輸出的candidate讀音平均峰值只有約0.20, RMS大概小聲11.7dB
——也就是母語者最需要專心聽、用來判斷答案的那一小段, 音量遠比前後文
小聲, 這是母語者實際回報「要注意的那個字太小聲了」才發現的真實bug,
不是猜測。修正方式：每一段(前文/candidate/後文)接起來前, 各自獨立做
peak normalization到同一個目標峰值(_TARGET_PEAK), 確保candidate不會
被前後文蓋過去。第一輪已經收到的11筆母語者回覆是在音量不平衡的版本
上做的判斷, 這點必須誠實揭露, 不能假裝那些答案是在音量正常的條件下
產生的。

這是在「完全沒有語境」跟「等詞庫資料修好才能做」之間的折衷方案, 品質
落點需要母語者實際聽過才能判斷夠不夠用。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.tts import NeurlangTTSBackend, TTSInput  # noqa: E402

SOURCE_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1.jsonl"
)
CANDIDATE_AUDIO_DIR = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_audio"
)
CANDIDATE_MANIFEST_PATH = os.path.join(CANDIDATE_AUDIO_DIR, "manifest_blind.jsonl")
OUT_DIR = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_audio_spliced"
)
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest_blind.jsonl")

_PAUSE_SEC = 0.25
_NEURLANG_SR = 22050  # 固定值, 見models/neurlang-vits-suisiann/config.json
_TARGET_PEAK = 0.9  # 留一點headroom, 避免resample/串接後意外超過滿量


def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def peak_normalize(audio, target_peak: float = _TARGET_PEAK):
    import numpy as np

    peak = float(np.max(np.abs(audio)))
    if peak < 1e-8:
        return audio  # 静音片段, 不放大(放大只會放大雜訊/量化誤差)
    return audio * (target_peak / peak)


def main() -> None:
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    source_rows = {r["id"]: r for r in load_jsonl(SOURCE_PATH)}
    candidate_manifest = load_jsonl(CANDIDATE_MANIFEST_PATH)

    os.makedirs(OUT_DIR, exist_ok=True)
    backend = NeurlangTTSBackend()

    manifest_rows = []

    for cand_row in candidate_manifest:
        row = source_rows[cand_row["id"]]
        sentence = row["sentence"]
        surface = row["surface"]
        idx = cand_row["target_char_index"]
        prefix_text = sentence[:idx]
        suffix_text = sentence[idx + len(surface) :]

        print(f"=== {row['id']} {surface!r} ===")
        print(f"  前文: {prefix_text!r}  後文: {suffix_text!r}")

        prefix_audio = None
        if prefix_text.strip():
            prefix_wav = os.path.join(OUT_DIR, f"{row['id']}_prefix.wav")
            backend.synthesize(
                TTSInput(hanji_text=prefix_text, tailo_text=""),
                __import__("pathlib").Path(prefix_wav),
            )
            prefix_audio, prefix_sr = sf.read(prefix_wav)
            assert prefix_sr == _NEURLANG_SR
            prefix_audio = peak_normalize(prefix_audio)

        suffix_audio = None
        if suffix_text.strip():
            suffix_wav = os.path.join(OUT_DIR, f"{row['id']}_suffix.wav")
            backend.synthesize(
                TTSInput(hanji_text=suffix_text, tailo_text=""),
                __import__("pathlib").Path(suffix_wav),
            )
            suffix_audio, suffix_sr = sf.read(suffix_wav)
            assert suffix_sr == _NEURLANG_SR
            suffix_audio = peak_normalize(suffix_audio)

        pause = np.zeros(int(_PAUSE_SEC * _NEURLANG_SR))

        entries = []
        for entry in cand_row["entries"]:
            cand_wav_path = os.path.join(CANDIDATE_AUDIO_DIR, entry["audio_file"])
            cand_audio, cand_sr = sf.read(cand_wav_path)
            if cand_sr != _NEURLANG_SR:
                cand_audio = resample_poly(cand_audio, _NEURLANG_SR, cand_sr)
            cand_audio = peak_normalize(cand_audio)

            pieces = []
            if prefix_audio is not None:
                pieces += [prefix_audio, pause]
            pieces.append(cand_audio)
            if suffix_audio is not None:
                pieces += [pause, suffix_audio]
            spliced = np.concatenate(pieces)

            out_filename = f"{row['id']}_{entry['candidate']}_spliced.wav"
            out_path = os.path.join(OUT_DIR, out_filename)
            sf.write(out_path, spliced, samplerate=_NEURLANG_SR)

            entries.append(
                {
                    "candidate": entry["candidate"],
                    "audio_file": out_filename,
                    "nasalization_dropped": entry["nasalization_dropped"],
                }
            )
            print(f"    {entry['candidate']} -> {out_filename}")

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
    print(f"完成 {len(manifest_rows)} 列拼接語音, manifest: {MANIFEST_PATH}")
    print(f"音檔目錄: {OUT_DIR}")


if __name__ == "__main__":
    main()
