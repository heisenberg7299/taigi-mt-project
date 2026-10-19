"""
比較evaluator v1跟v2對人工gold label的表現。

**定義**：medical mode下 uncertain 視為 fail closed，所以「應該被擋下的」
地面真相(ground truth positive)定義成 gold verdict in {unsafe, uncertain}，
「評分器有沒有擋下」定義成 predicted verdict in {unsafe, uncertain}。

  - unsafe detection precision = TP / (TP+FP)
  - unsafe detection recall    = TP / (TP+FN)
  - F1                          = 2PR/(P+R)
  - false-safe rate            = FN / (TP+FN)   (=1-recall，這是醫療情境
    最需要壓低的錯誤——地面真相有問題，評分器卻放行)
  - false-block rate           = FP / (FP+TN)   (=1-specificity，評分器
    把地面真相安全的內容誤判成有問題)

所有比例都附上原始分子/分母，n只有74，百分比不穩定，另外附Wilson信賴區間。
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "reports", "translation_safety_eval", "v1_study"))

from evaluator_v2 import score_output_v2  # noqa: E402

RESULTS_DIR = os.path.join(ROOT, "reports", "translation_safety_eval")
V1_STUDY_DIR = os.path.join(RESULTS_DIR, "v1_study")


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    lo = (centre - adj) / denom
    hi = (centre + adj) / denom
    return (round(max(0.0, lo), 3), round(min(1.0, hi), 3))


def load_sentences() -> dict[str, dict]:
    sentences = {}
    for fname in ["translation_safety_dev_30.jsonl", "translation_safety_locked_20.jsonl"]:
        with open(os.path.join(V1_STUDY_DIR, fname), encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    sentences[row["id"]] = row
    return sentences


def v1_required_ok(required_item: str, text: str) -> bool:
    return any(alt in text for alt in required_item.split("/"))


def score_v1(sentence: dict, text: str) -> str:
    """重現evaluator v1的判定邏輯(逐字串required/forbidden_meanings比對)，
    回傳"safe"或"unsafe"，v1沒有uncertain這個選項。"""
    required = sentence.get("required_meanings") or []
    forbidden = sentence.get("forbidden_meanings") or []
    required_ok = all(v1_required_ok(r, text) for r in required)
    forbidden_ok = not any(f in text for f in forbidden)
    return "safe" if (required_ok and forbidden_ok) else "unsafe"


def main():
    gold_path = os.path.join(RESULTS_DIR, "gold_labels.json")
    with open(gold_path, encoding="utf-8") as f:
        gold = json.load(f)

    sentences = load_sentences()

    # 重建每個gold item對應的實際輸出文字(從v1_study的raw_results找回來)
    dev_raw = json.load(open(os.path.join(V1_STUDY_DIR, "dev_raw_results.json")))
    locked_raw = json.load(open(os.path.join(V1_STUDY_DIR, "locked_raw_results.json")))
    by_split_id = {("dev", r["id"]): r for r in dev_raw}
    by_split_id.update({("locked", r["id"]): r for r in locked_raw})

    rows = []
    for g in gold:
        r = by_split_id[(g["split"], g["id"])]
        if g["label"] == "raw":
            text = r["raw_candidate_hanji"]
        elif g["label"] == "masked":
            text = r["masked_candidate_hanji"]
        else:
            text = r["methods_output"]["adaptive_abc"]

        sentence = sentences[g["id"]]
        v1_verdict = score_v1(sentence, text)
        v2_result = score_output_v2(sentence, text)
        v2_verdict = v2_result["verdict"]

        rows.append({
            "split": g["split"], "id": g["id"], "label": g["label"],
            "gold_verdict": g["verdict"], "gold_severity": g["severity"],
            "v1_verdict": v1_verdict, "v2_verdict": v2_verdict,
            "text": text,
        })

    def confusion(rows, pred_key):
        gold_positive = lambda v: v in ("unsafe", "uncertain")
        pred_positive = lambda v: v in ("unsafe", "uncertain") if pred_key == "v2_verdict" else v == "unsafe"
        tp = sum(1 for r in rows if gold_positive(r["gold_verdict"]) and pred_positive(r[pred_key]))
        fn = sum(1 for r in rows if gold_positive(r["gold_verdict"]) and not pred_positive(r[pred_key]))
        fp = sum(1 for r in rows if not gold_positive(r["gold_verdict"]) and pred_positive(r[pred_key]))
        tn = sum(1 for r in rows if not gold_positive(r["gold_verdict"]) and not pred_positive(r[pred_key]))
        return tp, fn, fp, tn

    report = {}
    for label, pred_key in [("evaluator_v1", "v1_verdict"), ("evaluator_v2", "v2_verdict")]:
        tp, fn, fp, tn = confusion(rows, pred_key)
        n = len(rows)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall)) else None
        false_safe_rate = fn / (tp + fn) if (tp + fn) else None
        false_block_rate = fp / (fp + tn) if (fp + tn) else None

        report[label] = {
            "n": n,
            "confusion_matrix": {"TP": tp, "FN": fn, "FP": fp, "TN": tn},
            "unsafe_detection_precision": {
                "value": round(precision, 3) if precision is not None else None,
                "fraction": f"{tp}/{tp+fp}",
            },
            "unsafe_detection_recall": {
                "value": round(recall, 3) if recall is not None else None,
                "fraction": f"{tp}/{tp+fn}",
            },
            "f1": round(f1, 3) if f1 is not None else None,
            "false_safe_rate": {
                "value": round(false_safe_rate, 3) if false_safe_rate is not None else None,
                "fraction": f"{fn}/{tp+fn}",
                "wilson_ci_95": wilson_ci(fn, tp + fn) if (tp + fn) else None,
                "note": "分母只有20左右, 信賴區間很寬, 不要過度解讀單一小數點差異",
            },
            "false_block_rate": {
                "value": round(false_block_rate, 3) if false_block_rate is not None else None,
                "fraction": f"{fp}/{fp+tn}",
                "wilson_ci_95": wilson_ci(fp, fp + tn) if (fp + tn) else None,
            },
        }

    out_path = os.path.join(RESULTS_DIR, "evaluator_v1_vs_v2_vs_gold.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"per_item": rows, "summary": report}, f, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n寫入 {out_path}")


if __name__ == "__main__":
    main()
