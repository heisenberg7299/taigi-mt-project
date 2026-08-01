"""
把 data/human_review/*.jsonl（驗證平台收到的所有測試者回覆）統整成報告，
隨時可以重跑，反映當下最新的回饋狀況。跟 export_verified.py 不同：
export_verified.py 是產生訓練用的乾淨語料，這支是給人看的統計摘要，
包含品質警訊（判錯但沒改字、多人意見不一致）方便追蹤資料到底可不可信。

執行：python scripts/summarize_feedback.py
"""
import json
import os
import glob
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REVIEW_DIR = os.path.join(ROOT, "data", "human_review")
OUT = os.path.join(ROOT, "reports", "feedback_summary.md")


def load_tokens():
    path = os.path.join(REVIEW_DIR, "_tokens.json")
    if not os.path.exists(path):
        return {}
    return json.load(open(path))


def main():
    tokens = load_tokens()
    files = sorted(glob.glob(os.path.join(REVIEW_DIR, "*.jsonl")))

    all_reviews = []
    per_tester = defaultdict(list)
    by_sentence = defaultdict(list)

    for f in files:
        key = os.path.basename(f)[:-6]
        name = tokens.get(key, {}).get("name", key)
        for line in open(f):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            r["_display_name"] = name
            all_reviews.append(r)
            per_tester[name].append(r)
            by_sentence[r["id"]].append(r)

    total = len(all_reviews)
    verdict_counts = {"correct": 0, "needs_edit": 0, "wrong": 0}
    unedited_wrong_or_edit = 0
    fluency_scores, adequacy_scores = [], []
    cat_verdict = defaultdict(lambda: {"correct": 0, "needs_edit": 0, "wrong": 0})

    for r in all_reviews:
        v = r.get("verdict")
        if v in verdict_counts:
            verdict_counts[v] += 1
            cat_verdict[r.get("category", "unknown")][v] += 1
        if v in ("wrong", "needs_edit") and r.get("corrected_nan_han") == r.get("candidate"):
            unedited_wrong_or_edit += 1
        if r.get("fluency") is not None:
            fluency_scores.append(r["fluency"])
        if r.get("adequacy") is not None:
            adequacy_scores.append(r["adequacy"])

    multi_rater = {sid: rs for sid, rs in by_sentence.items() if len(rs) > 1}
    conflicts = []
    for sid, rs in multi_rater.items():
        answers = set(r.get("corrected_nan_han") for r in rs)
        if len(answers) > 1:
            conflicts.append((sid, rs))

    lines = []
    lines.append("# 驗證平台回饋統整報告\n")
    lines.append(f"（此報告由 `scripts/summarize_feedback.py` 自動產生，可隨時重跑更新）\n")
    lines.append(f"## 總覽\n")
    lines.append(f"- 總回覆數：{total}")
    lines.append(f"- 測試者：{len(per_tester)} 位（{', '.join(f'{n}×{len(rs)}' for n, rs in sorted(per_tester.items(), key=lambda x:-len(x[1])))}）")
    lines.append(f"- 判定分布：✅正確 {verdict_counts['correct']} · ✏️需修改 {verdict_counts['needs_edit']} · ❌錯誤 {verdict_counts['wrong']}")
    if fluency_scores:
        lines.append(f"- 平均流暢度：{sum(fluency_scores)/len(fluency_scores):.2f} / 5（{len(fluency_scores)}筆有評分）")
    if adequacy_scores:
        lines.append(f"- 平均保真度：{sum(adequacy_scores)/len(adequacy_scores):.2f} / 5（{len(adequacy_scores)}筆有評分）")
    lines.append("")

    lines.append("## ⚠ 資料品質警訊\n")
    lines.append(
        f"- **{unedited_wrong_or_edit} 筆**判定「需修改」或「錯誤」，但修改欄位跟AI原始候選一字不差"
        f"（等於沒有實際提供正確答案，只有『這句有問題』的訊號，不知道問題在哪、正確答案是什麼）"
    )
    if conflicts:
        lines.append(f"- **{len(conflicts)} 句**有多位測試者意見不一致（答案不同），列在下面，需要人工判斷採用哪個")
    else:
        lines.append("- 目前沒有句子被多人測過，還無法看跨測試者的一致性")
    lines.append("")

    lines.append("## 各分類判定分布\n")
    lines.append("| 分類 | 正確 | 需修改 | 錯誤 |")
    lines.append("|---|---|---|---|")
    for cat, vc in sorted(cat_verdict.items()):
        lines.append(f"| {cat} | {vc['correct']} | {vc['needs_edit']} | {vc['wrong']} |")
    lines.append("")

    if conflicts:
        lines.append("## 多人意見不一致的句子\n")
        for sid, rs in conflicts:
            lines.append(f"### `{sid}`：{rs[0]['zh']}")
            lines.append(f"AI候選：「{rs[0]['candidate']}」\n")
            for r in rs:
                lines.append(f"- {r['_display_name']}（{r['verdict']}）：「{r.get('corrected_nan_han')}」" + (f" 備註：{r['note']}" if r.get('note') else ""))
            lines.append("")

    lines.append("## 有填備註的回覆（通常是最有資訊量的）\n")
    noted = [r for r in all_reviews if r.get("note")]
    if noted:
        for r in noted:
            lines.append(f"- `{r['id']}` [{r['_display_name']}] 「{r['zh']}」→「{r.get('corrected_nan_han')}」　備註：{r['note']}")
    else:
        lines.append("（目前沒有測試者填備註）")
    lines.append("")

    with open(OUT, "w") as f:
        f.write("\n".join(lines))

    print(f"寫入 {OUT}")
    print(f"總回覆數 {total}，{len(per_tester)} 位測試者，{unedited_wrong_or_edit} 筆判錯/需修改但沒實際改字，{len(conflicts)} 句多人意見不一致")


if __name__ == "__main__":
    main()
