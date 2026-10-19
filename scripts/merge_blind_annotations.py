"""
把母語者填好的ambiguity_gold_benchmark_v1_blind.jsonl(chosen_candidate
欄位)寫回ambiguity_gold_benchmark_v1.jsonl的gold_reading/gold_source/
native_verified欄位。

用法:
  python3 scripts/merge_blind_annotations.py

  只處理chosen_candidate非空的列; 沒填的列保持gold_reading=null、
  native_verified=false, 不會假裝標註已完成。若chosen_candidate的值
  不在該列的candidates清單裡(可能是抄寫打字錯誤), 會直接報錯中止,
  不會靜默寫入不存在的讀音。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SOURCE_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1.jsonl"
)
BLIND_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1_blind.jsonl"
)


def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def merge(source_rows: list[dict], blind_rows: list[dict]) -> tuple[list[dict], int]:
    chosen_by_id = {
        r["id"]: r["chosen_candidate"] for r in blind_rows if r.get("chosen_candidate")
    }
    merged_count = 0
    for row in source_rows:
        chosen = chosen_by_id.get(row["id"])
        if chosen is None:
            continue
        if chosen not in row["candidates"]:
            raise ValueError(
                f"{row['id']}: chosen_candidate={chosen!r} 不在candidates"
                f"{row['candidates']}裡, 可能是標註時抄錯字, 請檢查blind檔案"
            )
        row["gold_reading"] = chosen
        row["gold_source"] = "native_speaker_blind_annotation"
        row["native_verified"] = True
        merged_count += 1
    return source_rows, merged_count


def main() -> None:
    source_rows = load_jsonl(SOURCE_PATH)
    blind_rows = load_jsonl(BLIND_PATH)
    merged_rows, merged_count = merge(source_rows, blind_rows)
    with open(SOURCE_PATH, "w", encoding="utf-8") as f:
        for r in merged_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"merged {merged_count} annotated rows into {SOURCE_PATH}")


if __name__ == "__main__":
    main()
