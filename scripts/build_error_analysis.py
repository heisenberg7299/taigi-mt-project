"""
階段4.5：錯誤分析。從驗證平台(Firestore)抓所有真實回覆，
分類成 error_type，產生 reports/errors.csv 供階段6決策參考。

分類優先順序（信心從高到低）：
1. 測試者備註明確提到發音/聽感問題 -> PRONUNCIATION（最可信，是人講的）
2. 有備註但不是講發音 -> STYLE
3. 命中safety_checks.py的具體檢查 -> 對應的error_type
4. 句子分類當弱訊號（例如numbers_id類 -> NUMBER）
5. 都沒有 -> UNKNOWN

注意：目前(2026-08-02)大部分分類是弱訊號，因為95%的「需修改/錯誤」判定
測試者沒有實際填修改後版本。這份分析的可信度會隨著驗證平台表單改進
（區分翻譯錯/發音錯）、資料量增加而提升，見 reports/stage4.5_error_analysis.md。

執行：python scripts/build_error_analysis.py
"""
import csv
import json
import os
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = "english-vocab-43160"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
CHECKS_PATH = os.path.join(ROOT, "tests", "stage3_check_results.jsonl")
OUT_CSV = os.path.join(ROOT, "reports", "errors.csv")

CATEGORY_TO_ERROR = {
    "medical": "MEDICAL_TERM", "negation_risk": "NEGATION",
    "numbers_id": "NUMBER", "code_mixing": "CODE_SWITCH",
}
PRONUNCIATION_KEYWORDS = ["音", "聽不", "流暢", "腔"]


def fetch_json(url):
    with urllib.request.urlopen(url) as resp:
        return json.load(resp)


def firestore_field(fields, key):
    v = fields.get(key, {})
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    return None


def fetch_all_reviews():
    tokens_data = fetch_json(f"{BASE}/taigi_tokens")
    token_to_name = {}
    for doc in tokens_data.get("documents", []):
        name = doc["name"].rsplit("/", 1)[-1]
        token = doc["fields"]["token"]["stringValue"]
        token_to_name[token] = name

    reviews = []
    for token, name in token_to_name.items():
        data = fetch_json(f"{BASE}/taigi_reviews/{token}/items")
        for doc in data.get("documents", []):
            item_id = doc["name"].rsplit("/", 1)[-1]
            f = doc["fields"]
            reviews.append({
                "id": item_id, "tester": name,
                "zh": firestore_field(f, "zh"),
                "category": firestore_field(f, "category"),
                "candidate": firestore_field(f, "candidate"),
                "verdict": firestore_field(f, "verdict"),
                "correctedNanHan": firestore_field(f, "correctedNanHan"),
                "note": firestore_field(f, "note"),
            })
    return reviews


def classify(r, failed_checks):
    note = r.get("note") or ""
    if any(kw in note for kw in PRONUNCIATION_KEYWORDS):
        return "PRONUNCIATION", "note_keyword"
    if note:
        return "STYLE", "note_other"
    if "negation" in failed_checks:
        return "NEGATION", "safety_check"
    if "number_consistency" in failed_checks:
        return "NUMBER", "safety_check"
    if "trap_words" in failed_checks:
        return "GRAMMAR", "safety_check"
    if "medical_terms" in failed_checks:
        return "MEDICAL_TERM", "safety_check"
    if r["category"] in CATEGORY_TO_ERROR:
        return CATEGORY_TO_ERROR[r["category"]], "category_weak_signal"
    return "UNKNOWN", "no_signal"


def main():
    reviews = fetch_all_reviews()
    checks = {json.loads(l)["id"]: json.loads(l)["checks"] for l in open(CHECKS_PATH)}

    rows = []
    for r in reviews:
        if r["verdict"] == "correct":
            continue
        failed_checks = [n for n, info in checks.get(r["id"], {}).items() if not info.get("ok", True)]
        error_type, source = classify(r, failed_checks)
        changed = bool(r.get("correctedNanHan")) and r.get("correctedNanHan") != r.get("candidate")
        rows.append({
            "id": r["id"], "tester": r["tester"], "category": r["category"], "verdict": r["verdict"],
            "error_type": error_type, "classification_source": source,
            "severity": "high" if r["verdict"] == "wrong" else "medium",
            "actually_edited": changed, "zh": r["zh"], "candidate": r["candidate"],
            "correctedNanHan": r.get("correctedNanHan"), "note": r.get("note"),
        })

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "id", "tester", "category", "verdict", "error_type", "classification_source",
            "severity", "actually_edited", "zh", "candidate", "correctedNanHan", "note",
        ])
        w.writeheader()
        for row in rows:
            w.writerow(row)

    total = len(rows)
    print(f"共 {len(reviews)} 筆回覆，{total} 筆判定需修改/錯誤 -> {OUT_CSV}\n")
    c = Counter(r["error_type"] for r in rows)
    print("=== 錯誤類型分布 ===")
    for et, n in c.most_common():
        print(f"  {et}: {n} ({n/total*100:.0f}%)")
    weak = sum(1 for r in rows if not r["actually_edited"])
    print(f"\n判定有問題但沒實際填修改版本: {weak}/{total} ({weak/total*100:.0f}%)")


if __name__ == "__main__":
    main()
