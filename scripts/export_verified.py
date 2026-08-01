"""
把 data/human_review/*.jsonl（驗證平台上母語者的回覆）匯總成
data/processed/verified.jsonl，格式符合 data/schema.md。

規則：
- verdict == "correct" 或 "needs_edit" 且有填 corrected_nan_han -> 收進去，verified=true
- verdict == "wrong" 且沒有修改版本 -> 不收（沒有可用答案）
- 同一句如果有多位測試者，且答案不一致 -> 全部列出，標記 needs_review，不自動選一個

執行：python scripts/export_verified.py
"""
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REVIEW_DIR = os.path.join(ROOT, "data", "human_review")
TEST_SET = os.path.join(ROOT, "tests", "test_set_200.jsonl")
OUT = os.path.join(ROOT, "data", "processed", "verified.jsonl")


def main():
    test_set = {json.loads(l)["id"]: json.loads(l) for l in open(TEST_SET)}

    by_id = defaultdict(list)
    if os.path.isdir(REVIEW_DIR):
        for fname in os.listdir(REVIEW_DIR):
            if not fname.endswith(".jsonl"):
                continue
            with open(os.path.join(REVIEW_DIR, fname)) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    by_id[r["id"]].append(r)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    n_written, n_conflict, n_skipped = 0, 0, 0

    with open(OUT, "w") as fout:
        for id_, reviews in sorted(by_id.items()):
            usable = [
                r for r in reviews
                if r.get("verdict") in ("correct", "needs_edit") and r.get("corrected_nan_han")
            ]
            if not usable:
                n_skipped += 1
                continue

            answers = sorted(set(r["corrected_nan_han"] for r in usable))
            base = test_set.get(id_, {})
            row = {
                "id": id_,
                "zh": base.get("zh") or usable[0]["zh"],
                "nan_han": answers[0],
                "tailo": None,
                "intent": None,
                "domain": base.get("category", "unknown"),
                "source": "human_review",
                "license": "project_internal",
                "verified": True,
            }
            if len(answers) > 1:
                row["needs_review"] = True
                row["alternative_answers"] = answers[1:]
                n_conflict += 1
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            n_written += 1

    print(f"寫入 {n_written} 筆到 {OUT}")
    print(f"  其中 {n_conflict} 筆測試者答案不一致，已標記 needs_review，需要人工再確認")
    print(f"  {n_skipped} 句沒有可用的人工校對答案（尚未測試，或全部判定錯誤但沒填修改版本）")


if __name__ == "__main__":
    main()
