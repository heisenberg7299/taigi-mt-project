"""
一次性遷移腳本：把本機Flask版驗證平台累積的真實回覆(data/human_review/*.jsonl)
搬到新的靜態版(taigi-verify, GitHub Pages + Firestore)，一筆都不能少。

處理細節：
- 舊系統在「同名字接回進度」修好之前(PR #6)，同一個人可能因為重複輸入名字
  拿到好幾個不同token，回覆分散在好幾個檔案裡——遷移時依「顯示名稱」合併，
  同一句子如果被同一個人測過兩次，保留reviewed_at較新的那筆(後蓋前，
  跟正常Firestore寫入的行為一致)
- 每個人在新系統只給一個新token(taigi_tokens/{name})，所有回覆掛在
  同一個taigi_reviews/{token}/items/下

執行：python scripts/migrate_to_firestore.py
"""
import glob
import json
import os
import secrets

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REVIEW_DIR = os.path.join(ROOT, "data", "human_review")
PROJECT = "english-vocab-43160"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"


def to_firestore_fields(d):
    fields = {}
    for k, v in d.items():
        if v is None:
            fields[k] = {"nullValue": None}
        elif isinstance(v, bool):
            fields[k] = {"booleanValue": v}
        elif isinstance(v, int):
            fields[k] = {"integerValue": str(v)}
        elif isinstance(v, str):
            fields[k] = {"stringValue": v}
        else:
            fields[k] = {"stringValue": str(v)}
    return fields


def main():
    tokens_map = json.load(open(os.path.join(REVIEW_DIR, "_tokens.json")))

    by_name = {}
    for f in glob.glob(os.path.join(REVIEW_DIR, "*.jsonl")):
        key = os.path.basename(f)[:-6]
        name = tokens_map.get(key, {}).get("name", key)
        rows = [json.loads(l) for l in open(f)]
        by_name.setdefault(name, []).extend(rows)

    total_written = 0
    for name, rows in by_name.items():
        # 同一句子取reviewed_at較新的那筆
        latest_by_id = {}
        for r in rows:
            existing = latest_by_id.get(r["id"])
            if existing is None or r.get("reviewed_at", "") >= existing.get("reviewed_at", ""):
                latest_by_id[r["id"]] = r

        new_token = secrets.token_urlsafe(12)
        print(f"遷移 {name}：{len(latest_by_id)} 句 -> 新token {new_token}")

        # 1. taigi_tokens/{name}
        resp = requests.patch(
            f"{BASE}/taigi_tokens/{name}",
            json={"fields": to_firestore_fields({"token": new_token})},
        )
        resp.raise_for_status()

        # 2. taigi_reviews/{token} 父文件
        resp = requests.patch(
            f"{BASE}/taigi_reviews/{new_token}",
            json={"fields": to_firestore_fields({"name": name})},
        )
        resp.raise_for_status()

        # 3. 每句一筆 item
        for sentence_id, r in latest_by_id.items():
            payload = {
                "name": name,
                "zh": r.get("zh"),
                "category": r.get("category"),
                "candidate": r.get("candidate"),
                "verdict": r.get("verdict"),
                "note": r.get("note"),
                "migratedFrom": "flask_local",
            }
            if r.get("corrected_nan_han") is not None:
                payload["correctedNanHan"] = r["corrected_nan_han"]
            if r.get("fluency") is not None:
                payload["fluency"] = r["fluency"]
            if r.get("adequacy") is not None:
                payload["adequacy"] = r["adequacy"]

            resp = requests.patch(
                f"{BASE}/taigi_reviews/{new_token}/items/{sentence_id}",
                json={"fields": to_firestore_fields(payload)},
            )
            resp.raise_for_status()
            total_written += 1

    print(f"\n完成，共遷移 {len(by_name)} 位測試者、{total_written} 筆回覆")


if __name__ == "__main__":
    main()
