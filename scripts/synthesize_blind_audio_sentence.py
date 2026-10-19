"""
跟synthesize_blind_audio.py不同: 那支腳本只合成「單一candidate讀音」
孤立的一小段音, 母語者反應「只說一個字根本聽不懂」——脫離句子語境,
沒辦法判斷哪個讀音才符合這句話的意思, 這正好違背了整個disambiguation
benchmark的初衷(要看上下文才能選)。

這支腳本改成合成「整句」: 用RealSegmentationBackend把整句斷詞、查
台羅讀音, 只把目標字/詞那一格換成每個candidate, 其餘字詞維持斷詞結果
不變, 合成完整句子的語音, 讓母語者聽整句的語境去判斷。

## 為什麼有些列會被跳過

除了synthesize_blind_audio.py已知的「candidate本身缺調號」問題之外,
這支腳本多一個限制: 句子裡目標字以外的其他詞, 也必須全部能查到台羅讀音
且能轉成POJ, 才能合成完整句子。如果句子裡有OOV(查無讀音)或讀音本身
缺調號的其他詞, 整句就沒辦法合成, 這種列會被跳過並印出原因, 不會用
猜的讀音填空。
"""

from __future__ import annotations

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.segment import RealSegmentationBackend  # noqa: E402
from tw_hokkien_tts_pipeline.tailo_to_poj import tailo_word_to_poj  # noqa: E402

SOURCE_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1.jsonl"
)
OUT_DIR = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_audio_sentence"
)
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest_blind.jsonl")

MODEL_ID = "facebook/mms-tts-nan"
_SHUFFLE_SEED = 2024

# 跟scripts/safety_checks.py的PUNCTUATION_SAFE_TO_DROP保持一致, 這些字元
# 合成時直接跳過(不送進TTS), 不是遺漏, 是刻意排除
PUNCTUATION_SAFE_TO_DROP = set("。，、；：？！「」『』（）,.;:!?()— -\n\t ")


def load_rows(path: str = SOURCE_PATH) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _find_target_word_index(words, target_surface: str, target_char_index: int) -> int | None:
    """在斷詞結果裡找目標字/詞所在的word index, 用字元offset比對, 不是只比對
    surface(避免句子裡同一個字出現兩次時選錯位置)。"""
    offset = 0
    best_idx = None
    for i, w in enumerate(words):
        if w.surface == target_surface and offset == target_char_index:
            return i
        if w.surface == target_surface and best_idx is None:
            best_idx = i  # 位置對不上時的備援: 用第一個surface相符的
        offset += len(w.surface)
    return best_idx


def build_sentence_poj(words, target_index: int, candidate_tailo: str) -> str | list[str]:
    """回傳整句的POJ字串(空白分隔各詞), 或是一個list[str]表示哪些詞造成失敗
    (查無讀音/缺調號), 用回傳型別區分成功/失敗, 呼叫端自行判斷。"""
    problems = []
    poj_tokens = []
    for i, w in enumerate(words):
        tailo = candidate_tailo if i == target_index else w.tailo
        if tailo is None:
            if all(ch in PUNCTUATION_SAFE_TO_DROP for ch in w.surface):
                continue  # 標點, 直接跳過不送進TTS
            problems.append(f"{w.surface!r}查無讀音(OOV)")
            continue
        try:
            poj_tokens.append(tailo_word_to_poj(tailo))
        except ValueError:
            problems.append(f"{w.surface!r}讀音{tailo!r}缺調號數字")
    if problems:
        return problems
    return " ".join(poj_tokens)


def main() -> None:
    import soundfile as sf
    import torch
    from transformers import AutoTokenizer, VitsModel

    rows = load_rows()

    print(f"載入 {MODEL_ID} ...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = VitsModel.from_pretrained(MODEL_ID)
    model.eval()
    sample_rate = model.config.sampling_rate
    vocab = tokenizer.get_vocab()

    backend = RealSegmentationBackend(strategy="majority")

    os.makedirs(OUT_DIR, exist_ok=True)
    rng = random.Random(_SHUFFLE_SEED)
    manifest_rows = []
    skipped = []

    for row in rows:
        seg = backend.segment(row["sentence"])
        target_index = _find_target_word_index(
            seg.words, row["surface"], row["target_char_index"]
            if "target_char_index" in row
            else row["sentence"].find(row["surface"]),
        )
        if target_index is None:
            skipped.append((row["surface"], "斷詞結果裡找不到目標字/詞"))
            continue

        # 先確認每個candidate能不能轉成POJ(跟原本synthesize_blind_audio.py
        # 一樣的檢查), 缺調號的candidate本身就無法合成, 不重複造輪子
        entries = []
        row_ok = True
        row_problems = None
        for cand in row["candidates"]:
            try:
                cand_poj_check = tailo_word_to_poj(cand)
            except ValueError:
                row_ok = False
                row_problems = f"candidate {cand!r} 本身缺調號"
                break
            sentence_poj_or_problems = build_sentence_poj(seg.words, target_index, cand)
            if isinstance(sentence_poj_or_problems, list):
                row_ok = False
                row_problems = f"candidate {cand!r}: 句子其他詞有問題 -> {sentence_poj_or_problems}"
                break
            entries.append((cand, sentence_poj_or_problems))

        if not row_ok:
            skipped.append((row["surface"], row_problems))
            print(f"跳過 {row['surface']}: {row_problems}")
            continue

        manifest_entries = []
        for cand, sentence_poj in entries:
            dropped = sorted({ch for ch in sentence_poj if ch not in vocab and ch != " "})
            with torch.no_grad():
                inputs = tokenizer(sentence_poj, return_tensors="pt")
                output = model(**inputs).waveform

            wav_filename = f"{row['id']}_{cand}.wav"
            wav_path = os.path.join(OUT_DIR, wav_filename)
            sf.write(wav_path, output.squeeze().numpy(), samplerate=sample_rate)

            manifest_entries.append(
                {
                    "candidate": cand,
                    "sentence_poj_used_for_synthesis": sentence_poj,
                    "audio_file": wav_filename,
                    "nasalization_dropped": bool(dropped),
                }
            )
            print(
                f"  {row['surface']} / {cand} -> {sentence_poj!r} -> {wav_filename}"
                f"{' (鼻化音已丟失)' if dropped else ''}"
            )

        rng.shuffle(manifest_entries)
        manifest_rows.append(
            {
                "id": row["id"],
                "sentence": row["sentence"],
                "sentence_zh": row["sentence_zh"],
                "target": row["surface"],
                "entries": manifest_entries,
                "chosen_audio_file": None,
                "annotator_notes": None,
            }
        )

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        for r in manifest_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print()
    print(f"完整句子成功合成的列: {len(manifest_rows)}/{len(rows)}")
    print(f"跳過的列: {len(skipped)}")
    for surface, reason in skipped:
        print(f"  {surface}: {reason}")
    print(f"manifest: {MANIFEST_PATH}")
    print(f"音檔目錄: {OUT_DIR}")


if __name__ == "__main__":
    main()
