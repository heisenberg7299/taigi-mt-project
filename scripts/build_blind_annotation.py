"""
從ambiguity_gold_benchmark_v1.jsonl產生「盲測版」標註檔案給母語者用。

目的:
  避免讓標註者看到first_choice/majority_choice, 以免錨定偏誤——標註者
  應該純粹依照句子語境, 從candidates(已打亂順序)裡選一個讀音, 而不是
  被演算法的選擇引導。

  這份blind annotation的結果有雙重用途(roadmap Stage 3更新後的定位):
  1. 評估first-entry / dictionary-majority兩個baseline的真實準確率。
  2. 成為未來Stage 4 contextual disambiguator的訓練/評估gold data
     (sentence + target + candidates → 正確讀音的分類問題), 而不是
     只拿來證明majority能不能當最終方法。

用法:
  python3 scripts/build_blind_annotation.py
  產生 tw_hokkien_tts_pipeline/tests/data/ambiguity_gold_benchmark_v1_blind.jsonl

  母語者只需要填每一列的"chosen_candidate"(從candidates裡選一個字串
  照抄貼上), 可選填"annotator_notes"。標註完成後執行
  scripts/merge_blind_annotations.py 把結果寫回
  ambiguity_gold_benchmark_v1.jsonl的gold_reading欄位。
"""

from __future__ import annotations

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SOURCE_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1.jsonl"
)
BLIND_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1_blind.jsonl"
)

# 固定seed, 讓每次重新產生盲測檔案時候選順序都可重現, 但候選順序本身
# 跟CSV/first_choice/majority_choice的順序無關(已打亂), 標註者看不出
# 演算法的選擇
_SHUFFLE_SEED = 2024


def load_source(path: str = SOURCE_PATH) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_blind_rows(rows: list[dict]) -> list[dict]:
    rng = random.Random(_SHUFFLE_SEED)
    blind_rows = []
    for row in rows:
        candidates = list(row["candidates"])
        rng.shuffle(candidates)
        sentence = row["sentence"]
        surface = row["surface"]
        blind_rows.append({
            "id": row["id"],
            "sentence": sentence,
            "sentence_zh": row["sentence_zh"],
            "target": surface,
            "target_char_index": sentence.find(surface),
            "candidates": candidates,
            "chosen_candidate": None,
            "annotator_notes": None,
        })
    return blind_rows


def main() -> None:
    rows = load_source()
    blind_rows = build_blind_rows(rows)
    with open(BLIND_PATH, "w", encoding="utf-8") as f:
        for r in blind_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(blind_rows)} rows to {BLIND_PATH}")


if __name__ == "__main__":
    main()
