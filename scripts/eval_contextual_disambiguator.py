"""
Stage 5評估: 跑contextual_disambiguator.py的OllamaContextualDisambiguator
對ambiguity_gold_benchmark_v1.jsonl裡已驗證(native_verified=true)、
未被排除(excluded_from_evaluation)的列, 跟first/majority兩個baseline
一起比較準確率。

跟eval_ambiguity_disambiguation.py一樣的紀律: 只在native_verified且
gold_reading非空的列上算準確率, 不會因為樣本小就不報告, 但也不會
假裝這是統計上可靠的數字(見輸出的note)。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.contextual_disambiguator import (  # noqa: E402
    OllamaContextualDisambiguator,
)

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


def main() -> None:
    rows = load_jsonl(BENCHMARK_PATH)
    eligible = [r for r in rows if not r.get("excluded_from_evaluation")]
    verified = [r for r in eligible if r.get("native_verified") and r.get("gold_reading")]

    backend = OllamaContextualDisambiguator()

    results = []
    for row in verified:
        result = backend.disambiguate(row["sentence"], row["surface"], row["candidates"])
        results.append(
            {
                "surface": row["surface"],
                "gold": row["gold_reading"],
                "first_choice": row["first_choice"],
                "majority_choice": row["majority_choice"],
                "contextual_choice": result.chosen,
                "contextual_raw": result.raw_response,
                "contextual_error": result.error,
            }
        )

    first_correct = sum(1 for r in results if r["first_choice"] == r["gold"])
    majority_correct = sum(1 for r in results if r["majority_choice"] == r["gold"])
    contextual_correct = sum(1 for r in results if r["contextual_choice"] == r["gold"])
    contextual_no_answer = sum(1 for r in results if r["contextual_choice"] is None)

    n = len(results)
    print(f"{'字':6} {'gold':14} {'first':14} {'majority':14} {'contextual':14} 備註")
    for r in results:
        f_mark = "✓" if r["first_choice"] == r["gold"] else "✗"
        m_mark = "✓" if r["majority_choice"] == r["gold"] else "✗"
        c_mark = "✓" if r["contextual_choice"] == r["gold"] else ("✗" if r["contextual_choice"] else "無回應")
        note = r["contextual_error"] or ""
        print(
            f"{r['surface']:6} {r['gold']:14} {r['first_choice']+' '+f_mark:16} "
            f"{r['majority_choice']+' '+m_mark:16} "
            f"{(r['contextual_choice'] or '(none)')+' '+c_mark:16} {note}"
        )

    print()
    print(f"樣本數: {n} (跟Stage 3/4同一批12筆已驗證資料, 統計上仍然很小, 不是可靠結論)")
    print(f"first_accuracy:       {first_correct}/{n} = {first_correct/n:.3f}")
    print(f"majority_accuracy:    {majority_correct}/{n} = {majority_correct/n:.3f}")
    print(f"contextual_accuracy:  {contextual_correct}/{n} = {contextual_correct/n:.3f}")
    print(f"contextual_no_answer: {contextual_no_answer}/{n}")


if __name__ == "__main__":
    main()
