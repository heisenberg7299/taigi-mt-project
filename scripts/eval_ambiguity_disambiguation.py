"""
比較"first"(取CSV第一筆) vs "majority"(取CSV出現次數最多)兩種多音字消歧
策略, 對照tw_hokkien_tts_pipeline/tests/data/ambiguity_gold_benchmark_v1.jsonl
的母語者驗證讀音(gold_reading)算準確率。

用法:
  python3 scripts/eval_ambiguity_disambiguation.py

background:
  這份benchmark目前(建立時)的gold_reading/native_verified全部是null/false
  ——只有first_choice/majority_choice兩個演算法候選、沒有正確答案, 純粹是
  Stage 1(first vs majority比較)的產物, 用來讓母語者標註用的。native_verified
  的欄位要由人工(不是Claude自己)填寫gold_reading後才有意義, 這支腳本設計成
  可以在標註尚未完成時就先跑(會誠實回報「還有幾筆待標註」, 不會假裝
  部分標註的樣本代表全部)。

  這是回答「論文式的『常用讀音優先』(majority)到底有沒有比『任選一個』
  (first)更接近真實讀音」這個問題的最終量尺——first/majority「選了不同
  答案」不等於「選對了」, 見ambiguity_gold_benchmark_v1.jsonl建立時的
  分析討論, accuracy才是最終要看的數字。
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


def load_benchmark(path: str = BENCHMARK_PATH) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def score(rows: list[dict]) -> dict:
    excluded = [r for r in rows if r.get("excluded_from_evaluation")]
    eligible = [r for r in rows if not r.get("excluded_from_evaluation")]
    verified = [r for r in eligible if r.get("native_verified") and r.get("gold_reading")]

    result = {
        "total_rows": len(rows),
        "excluded_rows": len(excluded),
        "eligible_rows": len(eligible),
        "verified_rows": len(verified),
        "pending_rows": len(eligible) - len(verified),
    }

    if not verified:
        result["note"] = (
            "目前0筆有native_verified=true且gold_reading非空——這份benchmark"
            "還沒有任何一筆完成母語者標註, accuracy無法計算(不是0%, 是尚未量測)。"
            "先完成標註再重跑這支腳本。"
        )
        return result

    first_correct = sum(1 for r in verified if r["first_choice"] == r["gold_reading"])
    majority_correct = sum(1 for r in verified if r["majority_choice"] == r["gold_reading"])

    result["first_accuracy"] = round(first_correct / len(verified), 3)
    result["majority_accuracy"] = round(majority_correct / len(verified), 3)
    result["first_correct"] = first_correct
    result["majority_correct"] = majority_correct
    return result


def main() -> None:
    rows = load_benchmark()
    result = score(rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
