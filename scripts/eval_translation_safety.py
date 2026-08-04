"""
比較四種翻譯安全策略：No protection / Always mask / Adaptive A-B / Adaptive A-B+C。

用法：
  python3 scripts/eval_translation_safety.py dev      # 在30句dev set上跑，可重複執行、依結果調整規則
  python3 scripts/eval_translation_safety.py locked    # 在20句locked set上跑一次，存下原始結果，不得回頭改規則

方法論：
  - 每句話只實際呼叫LLM兩次(候選A原文 + 候選B遮罩)，四種方法都是從這兩個
    候選推導出來的，不重複呼叫，省時間也保證四種方法看到的是同一次翻譯結果
    (可比較性更好，不會因為LLM輸出的隨機性——雖然temperature=0是決定性的——
    在不同方法間看到不一樣的候選内容)。
  - No protection: 不管三七二十一直接用候選A(原文翻譯)的結果，不做任何檢查。
  - Always mask: 不管三七二十一直接用候選B(遮罩後翻譯還原)的結果，不做任何檢查。
    對應這個repo原本的single-strategy pipeline行為。
  - Adaptive A/B: 候選A通過(entities_ok+safety_ok)就用A，否則候選B通過就用B，
    否則視為fail closed(輸出為None)。
  - Adaptive A/B+C: 在A/B都失敗後，如果這句的structured_intent屬於
    StructuredMedicalRenderer支援範圍，改用候選C(人工審核模板)；否則fail closed。

  「是否安全」的地面真相(ground truth)用每句資料自己標註的required_meanings/
  forbidden_meanings/critical_entities/location_bed_relation判定，不是用
  scripts/safety_checks.py的通用檢查——那些檢查本身有已知誤報率(用來決定
  adaptive策略要不要選某個候選)，但拿來當「這句到底安不安全」的最終裁判
  不夠準，所以另外定義一套字面比對的裁判邏輯，見 score_output()。
"""
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.adaptive_translation import _evaluate_raw_candidate, _evaluate_masked_candidate
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard
from tw_hokkien_tts_pipeline.structured_renderer import StructuredIntent, StructuredMedicalRenderer
from tw_hokkien_tts_pipeline.translate import TaigiLlamaTranslationBackend

DATA_DIR = os.path.join(ROOT, "tw_hokkien_tts_pipeline", "tests", "data")
RESULTS_DIR = os.path.join(ROOT, "reports", "translation_safety_eval")

# 這50句資料集共用的Protected Token詞庫：藥名(部分故意不給台羅讀音，
# 模擬「尚未人工校正」的真實狀況)、人名(結構化 full_name，不是只給名字)
DRUG_LEXICON = {
    "普拿疼": "phóo-ná-thàng",
    "盤尼西林": "puân-nî-se-lîm",
    "胰島素": None,
    "降血壓藥": None,
    "抗生素": None,
    "降血糖藥": None,
    "阿斯匹靈": "a-suh-phit-lîng",
    "類固醇藥膏": None,
    "消炎藥水": None,
    # locked_v2(2026-08-03新增, 20句全新測試集用)
    "止痛藥": None,
    "抗凝血劑": None,
    "眼藥水": None,
    "顯影劑": None,
}
PERSON_NAMES = {
    "王小明", "陳美惠", "陳太太", "林先生", "林小姐", "張美玲",
    "劉建國", "黃淑芬", "陳先生", "王小華", "李醫師",
    # locked_v2(2026-08-03新增)
    "林淑芬", "黃伯伯", "吳文彬", "林志豪",
}


def score_output(sentence: dict, hanji_text: str | None) -> dict:
    """用資料集自己標註的required_meanings/forbidden_meanings/critical_entities/
    location_bed_relation當地面真相，判定這次輸出到底安不安全。跟
    scripts/safety_checks.py的通用檢查是兩回事，這裡是這次評估唯一的
    最終裁判標準。"""
    if hanji_text is None:
        return {
            "produced": False, "is_safe": None, "severity": None,
            "entity_preservation": 0.0, "context_preservation": None,
        }

    required = sentence.get("required_meanings") or []
    forbidden = sentence.get("forbidden_meanings") or []
    # required_meanings裡用"/"隔開的是同義詞候選，任一個出現就算通過
    required_ok = all(
        any(alt in hanji_text for alt in req.split("/"))
        for req in required
    )
    forbidden_ok = not any(f in hanji_text for f in forbidden)
    is_safe = required_ok and forbidden_ok

    entities = sentence.get("critical_entities") or []
    if entities:
        preserved = sum(1 for e in entities if e["text"] in hanji_text)
        entity_preservation = preserved / len(entities)
    else:
        entity_preservation = 1.0  # 沒有critical entity的句子(例如控制組)視為滿分, 不拉低平均

    loc = sentence.get("location_bed_relation")
    context_preservation = None
    if loc is not None:
        location_ok = loc["location"] in hanji_text
        person_texts = [e["text"] for e in entities if e["type"] == "person"]
        person_ok = (not person_texts) or any(p in hanji_text for p in person_texts)
        context_preservation = 1.0 if (location_ok and person_ok) else 0.0

    severity = 0 if is_safe else sentence.get("expected_severity_if_failed", 0)

    return {
        "produced": True, "is_safe": is_safe, "severity": severity,
        "entity_preservation": entity_preservation, "context_preservation": context_preservation,
        "required_ok": required_ok, "forbidden_ok": forbidden_ok,
    }


def run_one_sentence(sentence: dict, guard: ProtectedTokenGuard, backend, renderer: StructuredMedicalRenderer) -> dict:
    zh = sentence["zh"]
    mask_result = guard.mask(zh)

    raw_output = backend.translate(zh).translated_text
    raw_candidate = _evaluate_raw_candidate(zh, mask_result.spans, raw_output)

    masked_output = backend.translate(mask_result.masked_text).translated_text
    masked_candidate = _evaluate_masked_candidate(zh, guard, mask_result.spans, masked_output)

    # Adaptive A/B 決策 (不重新呼叫LLM，用上面已經算好的兩個候選推導)
    if raw_candidate.overall_ok:
        adaptive_ab_text = raw_candidate.hanji_text
        adaptive_ab_chosen = "raw"
    elif masked_candidate.overall_ok:
        adaptive_ab_text = masked_candidate.hanji_text
        adaptive_ab_chosen = "masked"
    else:
        adaptive_ab_text = None
        adaptive_ab_chosen = "blocked"

    # Adaptive A/B+C
    structured_intent = StructuredIntent.from_dict(sentence.get("structured_intent"))
    if adaptive_ab_text is not None:
        adaptive_abc_text = adaptive_ab_text
        adaptive_abc_chosen = adaptive_ab_chosen
    elif renderer.can_handle(structured_intent):
        adaptive_abc_text = renderer.render(structured_intent, backend)
        adaptive_abc_chosen = "structured_c"
    else:
        adaptive_abc_text = None
        adaptive_abc_chosen = "blocked"

    methods = {
        "no_protection": raw_candidate.hanji_text,
        "always_mask": masked_candidate.hanji_text,
        "adaptive_ab": adaptive_ab_text,
        "adaptive_abc": adaptive_abc_text,
    }
    scores = {name: score_output(sentence, text) for name, text in methods.items()}

    # false block用的參考：候選A或候選B任一個依「地面真相」算出來是安全的，
    # 就代表這句話其實有救，adaptive方法選擇block是可以避免的(false block)
    raw_score = score_output(sentence, raw_candidate.hanji_text)
    masked_score = score_output(sentence, masked_candidate.hanji_text)
    could_have_been_safe = bool(raw_score["is_safe"] or masked_score["is_safe"])

    return {
        "id": sentence["id"], "category": sentence["category"], "zh": zh,
        "raw_candidate_hanji": raw_candidate.hanji_text,
        "raw_candidate_entities_ok": raw_candidate.entities_ok,
        "raw_candidate_safety_ok": raw_candidate.safety_ok,
        "masked_candidate_hanji": masked_candidate.hanji_text,
        "masked_candidate_entities_ok": masked_candidate.entities_ok,
        "masked_candidate_safety_ok": masked_candidate.safety_ok,
        "adaptive_ab_chosen": adaptive_ab_chosen,
        "adaptive_abc_chosen": adaptive_abc_chosen,
        "could_have_been_safe": could_have_been_safe,
        "methods_output": methods,
        "methods_score": scores,
    }


def aggregate_metrics(rows: list[dict], method: str) -> dict:
    n = len(rows)
    produced = [r["methods_score"][method] for r in rows if r["methods_score"][method]["produced"]]
    blocked = [r for r in rows if not r["methods_score"][method]["produced"]]

    unsafe_pass = sum(1 for s in produced if not s["is_safe"])
    safe_completion = sum(1 for s in produced if s["is_safe"])
    abstention = len(blocked)
    false_block = sum(1 for r in blocked if r["could_have_been_safe"])

    entity_preservation_vals = [r["methods_score"][method]["entity_preservation"] for r in rows]
    context_vals = [
        r["methods_score"][method]["context_preservation"] for r in rows
        if r["methods_score"][method]["context_preservation"] is not None
    ]

    severity_counts = Counter(
        r["methods_score"][method]["severity"] for r in rows if r["methods_score"][method]["produced"]
    )

    return {
        "n": n,
        "unsafe_pass_rate": round(unsafe_pass / n, 3),
        "safe_completion_rate": round(safe_completion / n, 3),
        "abstention_rate": round(abstention / n, 3),
        "false_block_rate": round(false_block / abstention, 3) if abstention else 0.0,
        "critical_entity_preservation": round(sum(entity_preservation_vals) / n, 3),
        "context_preservation": round(sum(context_vals) / len(context_vals), 3) if context_vals else None,
        "level_0": severity_counts.get(0, 0),
        "level_1": severity_counts.get(1, 0),
        "level_2": severity_counts.get(2, 0),
        "level_3": severity_counts.get(3, 0),
        "abstained": abstention,
    }


FNAME_BY_WHICH = {
    "dev": "translation_safety_dev_30.jsonl",
    "locked": "translation_safety_locked_20.jsonl",
    "locked_v2": "translation_safety_locked_v2_20.jsonl",
}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "dev"
    assert which in FNAME_BY_WHICH, f"用法: python3 scripts/eval_translation_safety.py [{'|'.join(FNAME_BY_WHICH)}]"

    fname = FNAME_BY_WHICH[which]
    with open(os.path.join(DATA_DIR, fname), encoding="utf-8") as f:
        sentences = [json.loads(line) for line in f if line.strip()]

    guard = ProtectedTokenGuard(drug_lexicon=DRUG_LEXICON, person_names=PERSON_NAMES)
    backend = TaigiLlamaTranslationBackend()
    renderer = StructuredMedicalRenderer()

    rows = []
    for i, sentence in enumerate(sentences):
        print(f"[{i+1}/{len(sentences)}] {sentence['id']}: {sentence['zh']}", file=sys.stderr, flush=True)
        rows.append(run_one_sentence(sentence, guard, backend, renderer))

    os.makedirs(RESULTS_DIR, exist_ok=True)
    raw_path = os.path.join(RESULTS_DIR, f"{which}_raw_results.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    metrics = {
        method: aggregate_metrics(rows, method)
        for method in ["no_protection", "always_mask", "adaptive_ab", "adaptive_abc"]
    }
    metrics_path = os.path.join(RESULTS_DIR, f"{which}_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(f"\n寫入 {raw_path}", file=sys.stderr)
    print(f"寫入 {metrics_path}", file=sys.stderr)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
