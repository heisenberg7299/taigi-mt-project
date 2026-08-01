"""
階段3：把 safety_checks.py 的四層檢查套用在 Baseline 2（Taigi-Llama）的200句輸出上，
量化「多少句會被安全檢查層攔下來」，並寫報告。

執行：python scripts/run_stage3_checks.py
"""
import json
import os
from safety_checks import run_all_checks, ALL_CHECKS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "tests", "baseline_taigi_llama.jsonl")
OUT_JSONL = os.path.join(ROOT, "tests", "stage3_check_results.jsonl")
OUT_REPORT = os.path.join(ROOT, "reports", "stage3_safety_checks.md")


def main():
    rows = [json.loads(l) for l in open(BASELINE)]
    fail_counts = {name: 0 for name, _ in ALL_CHECKS}
    fail_examples = {name: [] for name, _ in ALL_CHECKS}
    out_rows = []

    for r in rows:
        zh = r["zh"]
        nan = r["baseline_taigi_llama_han"]
        results = run_all_checks(zh, nan)
        out_rows.append({"id": r["id"], "zh": zh, "nan": nan, "checks": results})
        for name, res in results.items():
            if not res["ok"]:
                fail_counts[name] += 1
                if len(fail_examples[name]) < 5:
                    fail_examples[name].append((r["id"], zh, nan, res["reason"]))

    with open(OUT_JSONL, "w") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    lines = []
    lines.append("# 階段3：安全檢查層套用結果（對 Baseline 2 / Taigi-Llama 輸出）\n")
    lines.append(f"日期：2026-08-01\n測試對象：`tests/baseline_taigi_llama.jsonl`（200句）\n")
    lines.append("## 各檢查層攔截統計\n")
    lines.append("| 檢查層 | 被攔下句數 | 攔截率 |")
    lines.append("|---|---|---|")
    for name, _ in ALL_CHECKS:
        n = fail_counts[name]
        lines.append(f"| {name} | {n}/200 | {n/200*100:.1f}% |")
    lines.append("")

    for name, _ in ALL_CHECKS:
        if not fail_examples[name]:
            continue
        lines.append(f"## {name} 攔截範例\n")
        for id_, zh, nan, reason in fail_examples[name]:
            lines.append(f"- `{id_}` 「{zh}」 -> 「{nan}」\n  理由：{reason}")
        lines.append("")

    lines.append("## 說明\n")
    lines.append(
        "這一層是規則式後處理檢查，不是翻譯本身。目的是把 Baseline 2 這種品質已經不錯、"
        "但仍會犯錯（尤其是數字唸法規則、罕見醫療詞）的模型輸出，攔下可疑句子讓母語者複核，"
        "而不是每句都要人工看過。`medical_terms` 檢查目前用簡單白名單比對，會有一些假警報"
        "（例如台語用詞跟白名單字面不同但語意正確），使用時應視為「值得複查」而非「一定錯」。"
    )

    with open(OUT_REPORT, "w") as f:
        f.write("\n".join(lines))

    print(f"完成，寫入 {OUT_JSONL} 和 {OUT_REPORT}")
    for name, _ in ALL_CHECKS:
        print(f"  {name}: {fail_counts[name]}/200 被攔下")


if __name__ == "__main__":
    main()
