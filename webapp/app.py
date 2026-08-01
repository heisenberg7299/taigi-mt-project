"""
台語翻譯候選答案 - 母語者驗證平台。

用途：讓測試者（台語母語者）逐句看「中文原句 -> Taigi-Llama候選台語翻譯」，
判定正確/需修改/錯誤，可直接編輯出正確版本，附上流暢度/保真度評分與備註。
結果存成每位測試者一份 JSONL，之後用 scripts/export_verified.py 匯總成
data/processed/verified.jsonl，作為訓練/評估用的第一批人工校對過語料。

執行：
  source ../venv/bin/activate  (若尚未啟用)
  pip install flask
  python app.py
  瀏覽器開 http://127.0.0.1:5001
"""
import json
import os
import random
import secrets
from datetime import datetime, timezone

from flask import Flask, request, redirect, url_for, render_template, jsonify, abort, make_response

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
REVIEW_DIR = os.path.join(ROOT, "data", "human_review")
AUDIO_DIR = os.path.join(TESTS, "audio")
ADMIN_KEY_PATH = os.path.join(REVIEW_DIR, ".admin_key")

BATCH_SIZE = 10

os.makedirs(REVIEW_DIR, exist_ok=True)

app = Flask(__name__)


def load_or_create_admin_key():
    """/progress 只給開發者自己看，不能讓拿到公開連結的測試者也看到全體資料，
    所以需要一組不放進版控、重啟伺服器也不會變的金鑰，存在 data/human_review/.admin_key
    （這個資料夾整個都在 .gitignore 裡，不會被推上 GitHub）。"""
    if os.path.exists(ADMIN_KEY_PATH):
        with open(ADMIN_KEY_PATH) as f:
            return f.read().strip()
    key = secrets.token_urlsafe(16)
    with open(ADMIN_KEY_PATH, "w") as f:
        f.write(key)
    return key


ADMIN_KEY = load_or_create_admin_key()
TOKENS_PATH = os.path.join(REVIEW_DIR, "_tokens.json")

COOKIE_NAME = "taigi_test_token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 180  # 180天。有測試者反應關掉視窗再回來進度就不見了——
# 原因是token只存在網址裡，沒書籤就等於沒了。改成同時存一份cookie在瀏覽器，
# 同一台裝置/瀏覽器之後不管是打開首頁還是重新填名字，都能自動接回原本的進度，
# 不用測試者自己記得收藏連結。

CATEGORY_LABELS = {
    "daily": "一般生活",
    "medical": "醫療需求",
    "robot_service": "機器人服務",
    "negation_risk": "否定與風險",
    "numbers_id": "數字人名病房號",
    "code_mixing": "中英台混合",
}

CHECK_LABELS = {
    "negation": "否定詞可能遺失",
    "number_consistency": "數字唸法可能不一致",
    "medical_terms": "醫療術語可能遺漏",
    "length_anomaly": "長度比例異常",
    "trap_words": "語意反轉風險字",
}


def _load_jsonl(path):
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows[r["id"]] = r
    return rows


def load_merged_dataset():
    test_set = _load_jsonl(os.path.join(TESTS, "test_set_200.jsonl"))
    b2 = _load_jsonl(os.path.join(TESTS, "baseline_taigi_llama.jsonl"))
    b1 = _load_jsonl(os.path.join(TESTS, "baseline_dict_match.jsonl"))
    checks = _load_jsonl(os.path.join(TESTS, "stage3_check_results.jsonl"))

    merged = []
    for id_, r in test_set.items():
        candidate = b2.get(id_, {}).get("baseline_taigi_llama_han")
        dict_ref = b1.get(id_, {}).get("baseline_dict_match")
        chk = checks.get(id_, {}).get("checks", {})
        failed_checks = [
            {"name": name, "label": CHECK_LABELS.get(name, name), "reason": info.get("reason")}
            for name, info in chk.items() if not info.get("ok", True)
        ]
        audio_path = os.path.join(AUDIO_DIR, f"{id_}.wav")
        merged.append({
            "id": id_,
            "zh": r["zh"],
            "category": r["category"],
            "category_label": CATEGORY_LABELS.get(r["category"], r["category"]),
            "candidate": candidate,
            "dict_reference": dict_ref,
            "failed_checks": failed_checks,
            "has_audio": os.path.exists(audio_path),
        })
    category_order = ["daily", "medical", "robot_service", "negation_risk", "numbers_id", "code_mixing"]
    def sort_key(x):
        cat_rank = category_order.index(x["category"]) if x["category"] in category_order else 99
        num = int(x["id"].rsplit("_", 1)[-1]) if x["id"].rsplit("_", 1)[-1].isdigit() else 0
        return (cat_rank, num)
    merged.sort(key=sort_key)
    return merged


DATASET = load_merged_dataset()
DATASET_BY_ID = {r["id"]: r for r in DATASET}


def load_tokens():
    """token -> 顯示名稱 的對照表。存在本機、不進版控（整個 data/human_review/ 都在 .gitignore）。
    測試者資料一律用不可猜的 token 當key，名字只拿來顯示，避免有人用猜的/知道的名字
    就看到或接續別人的答案（例如打「正男」就能看到正男填過什麼）。"""
    if not os.path.exists(TOKENS_PATH):
        return {}
    with open(TOKENS_PATH) as f:
        return json.load(f)


def save_tokens(tokens):
    with open(TOKENS_PATH, "w") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)


def create_tester_token(display_name):
    tokens = load_tokens()
    token = secrets.token_urlsafe(12)
    tokens[token] = {"name": display_name, "created_at": datetime.now(timezone.utc).isoformat()}
    save_tokens(tokens)
    return token


def tester_display_name(token):
    return load_tokens().get(token, {}).get("name", "訪客")


def tester_review_path(token):
    safe = "".join(c for c in token if c.isalnum() or c in ("-", "_")) or "anon"
    return os.path.join(REVIEW_DIR, f"{safe}.jsonl")


def load_tester_reviews(token):
    path = tester_review_path(token)
    reviews = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                reviews[r["id"]] = r
    return reviews


def append_review(token, review_row):
    path = tester_review_path(token)
    with open(path, "a") as f:
        f.write(json.dumps(review_row, ensure_ascii=False) + "\n")


def batch_path(token):
    safe = "".join(c for c in token if c.isalnum() or c in ("-", "_")) or "anon"
    return os.path.join(REVIEW_DIR, f"{safe}_batch.json")


def load_batch(token):
    path = batch_path(token)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_batch(token, ids):
    with open(batch_path(token), "w") as f:
        json.dump({"ids": ids, "created_at": datetime.now(timezone.utc).isoformat()}, f)


def remaining_pool(token):
    reviews = load_tester_reviews(token)
    return [r["id"] for r in DATASET if r["id"] not in reviews]


def get_or_init_batch(token):
    """回傳目前這輪的10題id清單。第一次呼叫才隨機抽新的一輪，
    之後即使這輪已經全部做完，也不會自動換下一輪 —— 換輪要透過 /new_batch 明確觸發，
    這樣「一輪10題」才有明確的段落感，而不是無感一直做下去。"""
    b = load_batch(token)
    if b is not None:
        return b["ids"]
    pool = remaining_pool(token)
    if not pool:
        return []
    ids = random.sample(pool, min(BATCH_SIZE, len(pool)))
    save_batch(token, ids)
    return ids


def start_new_batch(token):
    pool = remaining_pool(token)
    if not pool:
        return []
    ids = random.sample(pool, min(BATCH_SIZE, len(pool)))
    save_batch(token, ids)
    return ids


def resolve_token(candidate):
    """優先用網址/表單帶的token，沒有或無效就退回瀏覽器cookie裡存的那組。"""
    tokens = load_tokens()
    if candidate and candidate in tokens:
        return candidate
    cookie_token = request.cookies.get(COOKIE_NAME, "")
    if cookie_token and cookie_token in tokens:
        return cookie_token
    return None


def set_token_cookie(response, token):
    response.set_cookie(
        COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax"
    )
    return response


@app.route("/")
def index():
    cookie_token = request.cookies.get(COOKIE_NAME, "")
    if cookie_token and cookie_token in load_tokens():
        return redirect(url_for("review", t=cookie_token))
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start():
    cookie_token = request.cookies.get(COOKIE_NAME, "")
    if cookie_token and cookie_token in load_tokens():
        # 這台裝置已經有進行中的session了，不要因為又填了一次名字就開新的、
        # 讓舊進度變成看不到的孤兒資料。
        return redirect(url_for("review", t=cookie_token))
    display_name = request.form.get("tester", "").strip()
    if not display_name:
        return redirect(url_for("index"))
    token = create_tester_token(display_name)
    resp = redirect(url_for("review", t=token))
    return set_token_cookie(resp, token)


@app.route("/review")
def review():
    token = resolve_token(request.args.get("t", "").strip())
    if not token:
        return redirect(url_for("index"))
    tester_name = tester_display_name(token)

    reviews = load_tester_reviews(token)
    batch_ids = get_or_init_batch(token)

    if not batch_ids:
        resp = make_response(render_template(
            "done.html", tester=tester_name, total=len(DATASET), done=len(reviews)
        ))
        return set_token_cookie(resp, token)

    unreviewed_in_batch = [i for i in batch_ids if i not in reviews]
    if not unreviewed_in_batch:
        resp = redirect(url_for("batch_done", t=token))
        return set_token_cookie(resp, token)

    requested_id = request.args.get("id")
    if requested_id and requested_id in batch_ids and requested_id in DATASET_BY_ID:
        item_id = requested_id
    else:
        item_id = unreviewed_in_batch[0]

    item = DATASET_BY_ID[item_id]
    existing = reviews.get(item["id"])
    batch_position = batch_ids.index(item_id) + 1
    resp = make_response(render_template(
        "review.html",
        tester=tester_name,
        token=token,
        item=item,
        existing=existing,
        done=len(reviews),
        total=len(DATASET),
        all_ids=batch_ids,
        batch_position=batch_position,
        batch_size=len(batch_ids),
    ))
    return set_token_cookie(resp, token)


@app.route("/batch_done")
def batch_done():
    token = resolve_token(request.args.get("t", "").strip())
    if not token:
        return redirect(url_for("index"))
    tester_name = tester_display_name(token)
    reviews = load_tester_reviews(token)
    remaining = len(remaining_pool(token))
    resp = make_response(render_template(
        "batch_done.html",
        tester=tester_name,
        token=token,
        done=len(reviews),
        total=len(DATASET),
        remaining=remaining,
    ))
    return set_token_cookie(resp, token)


@app.route("/new_batch", methods=["POST"])
def new_batch():
    token = resolve_token(request.form.get("t", "").strip())
    if not token:
        return redirect(url_for("index"))
    start_new_batch(token)
    resp = redirect(url_for("review", t=token))
    return set_token_cookie(resp, token)


@app.route("/submit", methods=["POST"])
def submit():
    token = resolve_token(request.form.get("t", "").strip())
    id_ = request.form.get("id", "").strip()
    if not token or id_ not in DATASET_BY_ID:
        return redirect(url_for("index"))

    item = DATASET_BY_ID[id_]
    verdict = request.form.get("verdict", "")
    corrected = request.form.get("corrected", "").strip()
    fluency = request.form.get("fluency", "")
    adequacy = request.form.get("adequacy", "")
    note = request.form.get("note", "").strip()

    row = {
        "id": id_,
        "tester": tester_display_name(token),
        "zh": item["zh"],
        "category": item["category"],
        "candidate": item["candidate"],
        "verdict": verdict,  # correct / needs_edit / wrong
        "corrected_nan_han": corrected or None,
        "fluency": int(fluency) if fluency else None,
        "adequacy": int(adequacy) if adequacy else None,
        "note": note or None,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    append_review(token, row)
    resp = redirect(url_for("review", t=token))
    return set_token_cookie(resp, token)


@app.route("/progress")
def progress():
    if request.args.get("key") != ADMIN_KEY:
        abort(404)
    tokens = load_tokens()
    testers = []
    if os.path.isdir(REVIEW_DIR):
        for fname in sorted(os.listdir(REVIEW_DIR)):
            if not fname.endswith(".jsonl"):
                continue
            key = fname[:-6]
            display_name = tokens.get(key, {}).get("name", key)
            reviews = load_tester_reviews(key)
            verdict_counts = {"correct": 0, "needs_edit": 0, "wrong": 0}
            for r in reviews.values():
                v = r.get("verdict")
                if v in verdict_counts:
                    verdict_counts[v] += 1
            testers.append({
                "tester": display_name,
                "done": len(reviews),
                "total": len(DATASET),
                "verdict_counts": verdict_counts,
            })
    return render_template("progress.html", testers=testers, total=len(DATASET))


@app.route("/audio/<id_>")
def audio(id_):
    from flask import send_file
    path = os.path.join(AUDIO_DIR, f"{id_}.wav")
    if not os.path.exists(path):
        return "", 404
    return send_file(path, mimetype="audio/wav")


if __name__ == "__main__":
    print(f"已載入 {len(DATASET)} 句測試資料")
    print(f"開發者專用進度頁： http://127.0.0.1:5001/progress?key={ADMIN_KEY}")
    app.run(host="0.0.0.0", port=5001, debug=False)
