"""
把「聽音辨讀 v2」網頁工具匯出的taigi_annotation_results_v2.json寫回
ambiguity_gold_benchmark_v2_in_corpus.jsonl。

跟v1版的merge_audio_annotation_results.py(scripts/)邏輯一致，額外多處理
v2新增的「都不對」/「無法判斷」escape hatch：

  - chosen_candidate有值：正常寫入gold_reading/gold_source/native_verified=True，
    跟v1完全一樣。
  - special_response為"none_correct"或"cannot_determine"：**不寫入
    gold_reading**(這兩個選項存在的目的就是避免逼母語者選一個不對的答案
    污染黃金資料)，改成標記excluded_from_evaluation=True + exclusion_reason，
    跟v1裡「行/寒/變款」三筆的處理方式一致——誠實記錄「這筆結構性無法用」，
    不是默默留著pending假裝之後會有答案。
  - 兩者都沒有(理論上匯出檔案裡每一列都該有其中一個，防呆用)：跳過不動，
    維持原本pending狀態。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BENCHMARK_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v2_in_corpus.jsonl"
)

_SPECIAL_REASON = {
    "none_correct": "母語者盲測：候選讀音都不符合這句話的語境(都不對)",
    "cannot_determine": "母語者盲測：無法判斷/聽不出候選讀音差異",
}


def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def merge(source_rows: list[dict], results: list[dict]) -> tuple[list[dict], int, int, int]:
    results_by_id = {r["id"]: r for r in results}
    gold_filled = 0
    excluded = 0
    notes_filled = 0

    for row in source_rows:
        result = results_by_id.get(row["id"])
        if result is None:
            continue

        row.setdefault("annotator_note", None)
        if result.get("annotator_notes"):
            row["annotator_note"] = result["annotator_notes"]
            notes_filled += 1

        chosen = result.get("chosen_candidate")
        special = result.get("special_response")

        if chosen is not None:
            if chosen not in row["candidates"]:
                raise ValueError(
                    f"{row['id']}: chosen_candidate={chosen!r} 不在candidates"
                    f"{row['candidates']}裡, 檢查匯出檔案是否被手動改過"
                )
            row["gold_reading"] = chosen
            row["gold_source"] = "native_speaker_audio_annotation_v2"
            row["native_verified"] = True
            gold_filled += 1
        elif special in _SPECIAL_REASON:
            row["excluded_from_evaluation"] = True
            row["exclusion_reason"] = _SPECIAL_REASON[special]
            excluded += 1
        # 兩者都沒有：不動，維持pending(理論上不該發生，但不強制中止)

    return source_rows, gold_filled, excluded, notes_filled


def main() -> None:
    if len(sys.argv) != 2:
        print("用法: python3 scripts/merge_v2_annotation_results.py <匯出的json路徑>")
        sys.exit(1)

    export_path = sys.argv[1]
    with open(export_path, encoding="utf-8") as f:
        export_data = json.load(f)

    source_rows = load_jsonl(BENCHMARK_PATH)
    merged_rows, gold_filled, excluded, notes_filled = merge(source_rows, export_data["results"])

    with open(BENCHMARK_PATH, "w", encoding="utf-8") as f:
        for r in merged_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"寫入 {gold_filled} 筆 gold_reading")
    print(f"標記 {excluded} 筆 excluded_from_evaluation(都不對/無法判斷)")
    print(f"寫入 {notes_filled} 筆 annotator_note")
    print(f"更新: {BENCHMARK_PATH}")


if __name__ == "__main__":
    main()
