"""
把「聽音辨讀」網頁工具匯出的taigi_annotation_results.json(母語者實際聽
整句語境音檔後的選擇)寫回ambiguity_gold_benchmark_v1.jsonl。

跟merge_blind_annotations.py(文字盲測版, 未實際使用)不同, 這支對應的是
真正拿去給母語者用的語音版工具(scripts/synthesize_blind_audio_sentence.py
的後繼方案splice_context_audio.py + 網頁前端), 匯出格式是
{"exported_at": ..., "results": [{"id", "target", "sentence",
"chosen_candidate", "annotator_notes"}, ...]}。

## 設計原則

  - chosen_candidate為null的列(母語者沒有選、或聽不出來/句子看不懂)
    **不寫入gold_reading**, 維持null/native_verified=false, 不能把
    「沒有標註」誤植為「隨便選一個」。
  - 母語者的annotator_notes無論chosen_candidate是否為null都要保留,
    寫進新增的annotator_note欄位, 跟claude_note(我自己的非權威觀察)
    分開, 不能混為一談——這些備註本身就是重要的研究訊號(例如指出
    neurlang前後文發音錯誤、句子本身用詞過於生僻), 不是可有可無的
    附註。
  - chosen_candidate若不在該列的candidates清單裡(理論上網頁工具的
    選項本來就是從candidates產生, 不應該發生, 但仍保留防呆), 直接
    報錯中止, 不靜默寫入。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BENCHMARK_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1.jsonl"
)


def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def merge(source_rows: list[dict], results: list[dict]) -> tuple[list[dict], int, int]:
    results_by_id = {r["id"]: r for r in results}
    gold_filled = 0
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
        if chosen is None:
            continue
        if chosen not in row["candidates"]:
            raise ValueError(
                f"{row['id']}: chosen_candidate={chosen!r} 不在candidates"
                f"{row['candidates']}裡, 檢查匯出檔案是否被手動改過"
            )
        row["gold_reading"] = chosen
        row["gold_source"] = "native_speaker_audio_annotation"
        row["native_verified"] = True
        gold_filled += 1

    return source_rows, gold_filled, notes_filled


def main() -> None:
    if len(sys.argv) != 2:
        print("用法: python3 scripts/merge_audio_annotation_results.py <匯出的json路徑>")
        sys.exit(1)

    export_path = sys.argv[1]
    with open(export_path, encoding="utf-8") as f:
        export_data = json.load(f)

    source_rows = load_jsonl(BENCHMARK_PATH)
    merged_rows, gold_filled, notes_filled = merge(source_rows, export_data["results"])

    with open(BENCHMARK_PATH, "w", encoding="utf-8") as f:
        for r in merged_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"寫入 {gold_filled} 筆 gold_reading, {notes_filled} 筆 annotator_note")
    print(f"更新: {BENCHMARK_PATH}")


if __name__ == "__main__":
    main()
