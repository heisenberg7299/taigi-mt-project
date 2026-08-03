"""
Evaluator v2：concept-level語意比對，取代evaluator v1(逐字串required/
forbidden_meanings比對)。

v1的問題（locked set已經證明過）：required_meanings/forbidden_meanings
用純字面比對，同義詞覆蓋不全時會誤判——例如「跌倒」沒有列出Hokkien常見
說法「跋倒」，導致內容正確的輸出被判定unsafe；「藥膏」被列為forbidden
是為了抓「藥名被籠統化」，但正確輸出「類固醇藥膏」剛好包含這兩個字，也被
誤判違規。

v2改成：
  1. Unicode NFC正規化 + 漢羅格式正規化(移除輕聲標記"--"、全形/半形標點統一)
  2. 用 concept_taxonomy.py 的九種概念(PERSON/STAFF_ROLE/DRUG/DOSE/TIME/
     NEGATION/BED_LOCATION/PERSON_RELATION/ACTION)做同義詞感知比對，不是
     純字面比對
  3. forbidden_meanings改成排除「只是某個正確複合詞子字串」的情況
  4. 否定範圍檢查：句子需要否定但輸出找不到已知否定標記時，如果輸出裡有
     「敢/甘」這類台語是非問句標記(不需要顯式否定詞就能表達詢問語氣)，
     判定uncertain而不是硬判unsafe或safe——這是這次任務新增的第三種結果
  5. 三態結果：safe / unsafe / uncertain。**在medical mode下，
     uncertain視為fail closed(等同unsafe處理，不能播出去)**，跟v1只有
     safe/unsafe二元判定不同。

**StructuredMedicalRenderer(候選C)的評分完全不看它是用哪個template生成的
(不看source semantic frame)，只看最終輸出的文字本身**，用跟其他候選一樣
的流程重新解析——避免「因為是模板生成的就自動判定正確」這種循環評估。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.concept_taxonomy import ALL_ENTRIES, ConceptEntry, build_variant_to_concept_index

# 台語是非問句標記：用「敢/甘+會/有」這類結構問問題時，語法上不需要顯式
# 否定詞就能表達「是不是/會不會」的語意(例如「敢會」對應華語「會不會」)。
# 這是實測(10句+50句測試)反覆看到的已知模式，不是憑空假設。
QUESTION_MARKERS = ["敢", "甘"]

_FULLWIDTH_TO_HALFWIDTH = str.maketrans(
    "，。！？：；「」『』（）",
    ",.!?:;\"\"''()",
)


def normalize_text(text: str | None) -> str:
    """Unicode NFC正規化 + 漢羅格式正規化。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    # "出--矣" 這種"--"是台語文字標記輕聲/停頓的正字法慣例，不是內容差異，
    # 比對概念時應該忽略，不然"報告出--矣"會比對不到"報告出來矣"
    text = text.replace("--", "")
    text = text.translate(_FULLWIDTH_TO_HALFWIDTH)
    return text


@dataclass
class ConceptMatch:
    entry: ConceptEntry
    matched_variant: str


def extract_concept_matches(text: str) -> list[ConceptMatch]:
    """在正規化後的文字裡，用最長字串優先掃描找出出現過哪些concept。

    這不是真正的統計式分詞器，是針對這個資料集詞彙規模(taxonomy約150個
    variant字串)做的簡單比對，足夠這次評估用，不是要取代正式的台語斷詞
    工具(那是另一個階段的任務，這次刻意不碰斷詞邏輯)。
    """
    normalized = normalize_text(text)
    index = build_variant_to_concept_index()
    matches: list[ConceptMatch] = []
    for variant in sorted(index.keys(), key=len, reverse=True):
        norm_variant = normalize_text(variant)
        if norm_variant and norm_variant in normalized:
            matches.append(ConceptMatch(entry=index[variant], matched_variant=variant))
    return matches


def concept_aware_required_ok(required_item: str, text: str) -> bool:
    """檢查required_meanings裡的一項，是否在text裡以任何已知同義詞形式出現。

    先相容v1既有的"/"分隔多候選寫法(字面比對)，再用concept_taxonomy擴充
    比對——required_meanings本身沒列出的同義詞，只要taxonomy裡有登記，
    一樣算數。
    """
    normalized_text = normalize_text(text)
    literal_candidates = required_item.split("/")
    if any(normalize_text(c) in normalized_text for c in literal_candidates):
        return True

    index = build_variant_to_concept_index()
    for candidate in literal_candidates:
        entry = index.get(candidate)
        if entry and any(normalize_text(v) in normalized_text for v in entry.variants):
            return True
    return False


def concept_aware_forbidden_violated(forbidden_item: str, text: str) -> bool:
    """檢查forbidden_meanings的一項是否真的構成違規。

    排除「只是某個taxonomy裡登記過的正確複合詞的子字串」這種情況——例如
    forbidden="藥膏"，但輸出正確用了複合詞"類固醇藥膏"，"藥膏"只是這個
    正確複合詞的一部分，不該被判違規(這正是locked set的drug_009案例，
    v1誤判過)。
    """
    normalized_text = normalize_text(text)
    norm_forbidden = normalize_text(forbidden_item)
    if norm_forbidden not in normalized_text:
        return False

    for entry in ALL_ENTRIES:
        for variant in entry.variants:
            norm_variant = normalize_text(variant)
            if norm_forbidden in norm_variant and norm_forbidden != norm_variant and norm_variant in normalized_text:
                return False  # 只是正確複合詞的子字串
    return True


def _negation_status(zh_text: str, hanji_text: str) -> str:
    """回傳 'ok' / 'lost' / 'uncertain'。"""
    zh_negation_markers = ["沒有", "不是", "沒", "不會", "不能", "不想", "不需要", "不確定", "並不", "並非", "不可以", "不"]
    if not any(m in zh_text for m in zh_negation_markers):
        return "ok"  # 原文本來就沒有否定，不用檢查

    negation_variants = [v for e in ALL_ENTRIES if e.concept_type == "NEGATION" for v in e.variants]
    normalized_output = normalize_text(hanji_text)
    if any(normalize_text(v) in normalized_output for v in negation_variants):
        return "ok"

    if any(marker in normalized_output for marker in QUESTION_MARKERS):
        return "uncertain"  # 是非問句可能不需要顯式否定詞，但無法完全確認

    return "lost"


def score_output_v2(sentence: dict, hanji_text: str | None) -> dict:
    """evaluator v2的主要評分函式。跟v1的 score_output() 介面盡量一致，
    方便直接替換比較，但回傳三態 verdict(safe/unsafe/uncertain)，不是
    v1的 is_safe 布林值。
    """
    if hanji_text is None:
        return {
            "produced": False, "verdict": None, "severity": None,
            "entity_preservation": 0.0, "context_preservation": None,
            "matched_concepts": [], "notes": [],
        }

    notes: list[str] = []
    required = sentence.get("required_meanings") or []
    forbidden = sentence.get("forbidden_meanings") or []

    required_results = {req: concept_aware_required_ok(req, hanji_text) for req in required}
    required_ok = all(required_results.values())

    forbidden_results = {f: concept_aware_forbidden_violated(f, hanji_text) for f in forbidden}
    forbidden_ok = not any(forbidden_results.values())

    neg_status = "ok"
    if sentence.get("negation", {}).get("present"):
        neg_status = _negation_status(sentence["zh"], hanji_text)
        if neg_status == "uncertain":
            notes.append("否定範圍無法確認(輸出含是非問句標記但無顯式否定詞)")
        elif neg_status == "lost":
            notes.append("否定語意疑似遺失")

    entities = sentence.get("critical_entities") or []
    if entities:
        preserved = sum(1 for e in entities if e["text"] in normalize_text(hanji_text))
        entity_preservation = preserved / len(entities)
    else:
        entity_preservation = 1.0

    loc = sentence.get("location_bed_relation")
    context_preservation = None
    if loc is not None:
        location_matches = extract_concept_matches(hanji_text)
        location_ok = (
            loc["location"] in normalize_text(hanji_text)
            or any(m.entry.concept_type == "BED_LOCATION" for m in location_matches)
        )
        person_texts = [e["text"] for e in entities if e["type"] == "person"]
        person_ok = (not person_texts) or any(p in normalize_text(hanji_text) for p in person_texts)
        context_preservation = 1.0 if (location_ok and person_ok) else 0.0

    # 三態判定：
    #   - forbidden違反 或 required沒過(且非uncertain) -> unsafe
    #   - 否定範圍uncertain -> uncertain(除非同時有其他明確unsafe理由，那樣直接unsafe)
    #   - 都通過 -> safe
    if not forbidden_ok:
        verdict = "unsafe"
        notes.append(f"觸犯forbidden_meanings: {[k for k,v in forbidden_results.items() if v]}")
    elif not required_ok:
        # required沒過，但如果唯一沒過的原因跟否定有關且是uncertain狀態，
        # 整體判uncertain而不是硬判unsafe
        missing = [k for k, v in required_results.items() if not v]
        if neg_status == "uncertain" and all(_looks_negation_related(m) for m in missing):
            verdict = "uncertain"
        else:
            verdict = "unsafe"
            notes.append(f"required_meanings未滿足: {missing}")
    elif neg_status == "uncertain":
        verdict = "uncertain"
    else:
        verdict = "safe"

    severity = 0 if verdict == "safe" else sentence.get("expected_severity_if_failed", 0)

    return {
        "produced": True, "verdict": verdict, "severity": severity,
        "entity_preservation": entity_preservation, "context_preservation": context_preservation,
        "required_ok": required_ok, "forbidden_ok": forbidden_ok,
        "negation_status": neg_status,
        "matched_concepts": [m.entry.canonical for m in extract_concept_matches(hanji_text)],
        "notes": notes,
    }


def _looks_negation_related(required_item: str) -> bool:
    negation_hint_words = ["不", "毋", "袂", "莫", "無", "免", "禁止", "不能", "不可以", "不要"]
    return any(w in required_item for w in negation_hint_words)
