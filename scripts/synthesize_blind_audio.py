"""
用facebook/mms-tts-nan (Facebook MMS計畫的Min Nan VITS TTS, CC-BY-NC-4.0)
把ambiguity_gold_benchmark_v1.jsonl裡每個candidate合成一段語音, 產生給
母語者用「聽的」盲測標註集。

## 為什麼選這個模型

見tw_hokkien_tts_pipeline/tailo_to_poj.py的討論——這個repo原本規劃用
SpeechT5 fine-tune合成, 但實測發現那個模型的tokenizer完全沒有數字token,
調號數字會被直接丟掉, 沒辦法用來區分不同candidate的讀音。mms-tts-nan
的tokenizer字彙表雖然也不是數字調號, 但涵蓋POJ重音符所需的字母組合,
只要用tailo_to_poj.py先轉換過, 調號資訊就能正確保留。

## 已知限制(已用真實tokenizer字彙表驗證過, 不是猜測)

  1. 鼻化符號ⁿ (U+207F) 不在這個模型的字彙表裡, 合成時會被靜默濾掉。
     受影響的candidate仍然會合成、仍然保留正確調號, 只是鼻化音這個線索
     消失了。這些candidate在manifest裡會標記"nasalization_note"。
  2. ChhoeTaigi詞庫來源資料裡, 有些candidate讀音本身就沒有調號數字
     (資料品質問題, 不是這個腳本造成的), 沒辦法轉換, 這些candidate
     所在的整列直接跳過, 不納入這次的語音盲測集(共8/24列受影響,
     見reports或執行這支腳本時印出的清單)。

## 輸出

  tw_hokkien_tts_pipeline/tests/data/ambiguity_gold_audio/
    <row_id>_<candidate>.wav          每個candidate一個音檔
    manifest_blind.jsonl              盲測用清單(candidates順序已打亂,
                                       不透露哪個是first_choice/majority_choice)
"""

from __future__ import annotations

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.tailo_to_poj import tailo_word_to_poj  # noqa: E402

SOURCE_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1.jsonl"
)
OUT_DIR = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_audio"
)
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest_blind.jsonl")

MODEL_ID = "facebook/mms-tts-nan"
_SHUFFLE_SEED = 2024


def load_rows(path: str = SOURCE_PATH) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def usable_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """回傳(全部candidate都能轉換的列, 至少一個candidate缺調號的列)。"""
    usable, blocked = [], []
    for row in rows:
        ok = True
        for cand in row["candidates"]:
            try:
                tailo_word_to_poj(cand)
            except ValueError:
                ok = False
                break
        (usable if ok else blocked).append(row)
    return usable, blocked


def main() -> None:
    import soundfile as sf
    import torch
    from transformers import AutoTokenizer, VitsModel

    rows = load_rows()
    usable, blocked = usable_rows(rows)
    print(f"可合成語音的列: {len(usable)}/{len(rows)}")
    print(f"至少一個candidate缺調號、跳過的列: {len(blocked)}")
    for r in blocked:
        print(f"  跳過: {r['surface']} {r['candidates']}")
    print()

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"載入 {MODEL_ID} ...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = VitsModel.from_pretrained(MODEL_ID)
    model.eval()
    sample_rate = model.config.sampling_rate
    vocab = tokenizer.get_vocab()

    rng = random.Random(_SHUFFLE_SEED)
    manifest_rows = []

    for row in usable:
        entries = []
        for cand in row["candidates"]:
            poj = tailo_word_to_poj(cand)
            dropped = sorted({ch for ch in poj if ch not in vocab and ch != "-"})

            with torch.no_grad():
                inputs = tokenizer(poj, return_tensors="pt")
                output = model(**inputs).waveform

            wav_filename = f"{row['id']}_{cand}.wav"
            wav_path = os.path.join(OUT_DIR, wav_filename)
            sf.write(wav_path, output.squeeze().numpy(), samplerate=sample_rate)

            entries.append(
                {
                    "candidate": cand,
                    "poj_used_for_synthesis": poj,
                    "audio_file": wav_filename,
                    "nasalization_dropped": bool(dropped),
                }
            )
            print(f"  {row['surface']} / {cand} -> {poj!r} -> {wav_filename}"
                  f"{' (鼻化音已丟失)' if dropped else ''}")

        rng.shuffle(entries)

        manifest_rows.append(
            {
                "id": row["id"],
                "sentence": row["sentence"],
                "sentence_zh": row["sentence_zh"],
                "target": row["surface"],
                "target_char_index": row["sentence"].find(row["surface"]),
                "entries": entries,
                "chosen_audio_file": None,
                "annotator_notes": None,
            }
        )

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        for r in manifest_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print()
    print(f"寫入 {len(manifest_rows)} 列 manifest 到 {MANIFEST_PATH}")
    print(f"音檔目錄: {OUT_DIR}")


if __name__ == "__main__":
    main()
