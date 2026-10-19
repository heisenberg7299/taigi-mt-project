"""
Concept-level 語意標註 taxonomy，evaluator v2 的核心資料表。

evaluator v1(`scripts/eval_translation_safety.py`)用的是逐字串比對
`required_meanings`/`forbidden_meanings`，遇到Hokkien同義詞/漢羅變體沒有
列全就會誤判——locked set已經證明過這一點(`drug_008`的「跋倒」vs「跌倒」、
`drug_006`的「暗時」vs「晚上」)。這裡改成先把輸出文字裡的詞正規化、映射
到「概念」(concept)，再判斷概念有沒有出現，而不是原始字面比對。

九種概念類型：
  PERSON, STAFF_ROLE, DRUG, DOSE, TIME, NEGATION, BED_LOCATION,
  PERSON_RELATION, ACTION

## 同義詞表的來源(每一條entry都要標明，不能假裝是憑空定義的)

- `dev_output`：直接觀察自 `reports/translation_safety_eval/v1_study/
  dev_raw_results.json`(dev set，evaluator v1第一次執行時的真實LLM輸出)，
  這是development set，這裡取用完全合乎「用dev set調整系統」的紀律。
- `moe_dict`：查過教育部臺灣台語常用詞辭典(`data/raw/moe_dictionary/
  dict-twblg.json`)確認過的正式詞條，通常是 `title`/`synonyms` 欄位直接
  給出的對應關係。
- `manual`：現有詞典/dev輸出都查不到，但屬於常識性判斷的補充(例如「醫師」
  「護理師」這類現代醫療專有名詞，MOE辭典設計上不收錄這類詞——辭典只收
  「有特色的台語詞」，不是完整詞庫，這個限制在之前的研究已經確認過)。
- `post_hoc_locked`：**這次任務新增的重要規則**——從舊的locked set
  (`translation_safety_locked_20.jsonl`)輸出裡才發現、dev set沒出現過的
  詞，一律標這個來源，且在報告裡要明確寫「事後補上」，不能假裝是
  預先定義好的。目前這個taxonomy裡沒有任何一條是這個來源(修這個taxonomy
  時故意只用dev_output/moe_dict/manual，把locked set的詞留給之後的
  post-hoc analysis章節單獨處理，避免不小心把locked set學到的東西
  偷偷混進「未見資料」的同義詞表裡)。

**這不是通用台語NLP資源**，範圍刻意限定在這個研究的50句資料集(以及未來
locked v2大概率會用到的類似醫療服務情境詞彙)，不是要取代正式的台語詞典
專案。
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONCEPT_TYPES = (
    "PERSON", "STAFF_ROLE", "DRUG", "DOSE", "TIME", "NEGATION",
    "BED_LOCATION", "PERSON_RELATION", "ACTION",
)


@dataclass
class ConceptEntry:
    concept_type: str
    canonical: str  # 概念的代表詞(用華語方便閱讀/除錯，不代表華語優先於台語)
    variants: list[str]  # 所有已知同義詞/漢羅變體/複合詞，含canonical本身
    source: str  # "dev_output" / "moe_dict" / "manual" / "post_hoc_locked"


# ---------- NEGATION ----------
# 跟 scripts/safety_checks.py 的 NAN_NEGATION 同源，但這裡是概念層級的
# entry(可以附加scope描述)，不是純粹的關鍵字清單
NEGATION_ENTRIES = [
    ConceptEntry("NEGATION", "毋通(不要/不可以)", ["毋通", "不要", "不可以"], "dev_output"),
    ConceptEntry("NEGATION", "袂使/袂當(不能/不可以)", ["袂使", "袂當", "不能", "不可以"], "dev_output"),
    ConceptEntry("NEGATION", "莫(不要)", ["莫", "不要"], "moe_dict"),  # moe_dict確認"莫"讀mài
    ConceptEntry("NEGATION", "免(不用)", ["免", "不用", "不需要"], "moe_dict"),
    ConceptEntry("NEGATION", "猶未(還沒)", ["猶未", "還沒", "尚未"], "moe_dict"),
    ConceptEntry("NEGATION", "袂(不會)", ["袂", "不會"], "moe_dict"),
    ConceptEntry("NEGATION", "毋(不)", ["毋", "不"], "manual"),
    ConceptEntry("NEGATION", "無(沒有)", ["無", "沒有"], "manual"),
]

# ---------- TIME ----------
TIME_ENTRIES = [
    ConceptEntry("TIME", "逐工(每天/一天)", ["逐工", "一工", "一日", "每天", "一天"], "dev_output"),
    ConceptEntry("TIME", "暗時(晚上)", ["暗時", "暗頓", "晚上", "夜晚"], "dev_output"),
    ConceptEntry("TIME", "早起/透早(早上)", ["早起", "透早", "早頓", "早上", "早餐"], "dev_output"),
    ConceptEntry("TIME", "連紲(連續)", ["連紲", "連續"], "dev_output"),
    ConceptEntry("TIME", "飯飽(飯後)", ["飯飽", "食飽", "飯後"], "dev_output"),
    ConceptEntry("TIME", "這馬(現在)", ["這馬", "現在", "這陣"], "dev_output"),
    ConceptEntry("TIME", "下晡(下午)", ["下晡", "下午"], "dev_output"),
    ConceptEntry("TIME", "隨(馬上/立刻)", ["隨", "馬上", "立刻", "趕緊"], "dev_output"),
    ConceptEntry("TIME", "半點鐘(半小時)", ["半點鐘", "半小時"], "dev_output"),
]

# ---------- ACTION ----------
ACTION_ENTRIES = [
    ConceptEntry("ACTION", "食(吃)", ["食", "吃"], "dev_output"),
    ConceptEntry("ACTION", "啉水(喝水)", ["啉水", "啉", "喝水"], "dev_output"),
    ConceptEntry("ACTION", "食物件(吃東西)", ["食物件", "食物", "吃東西"], "dev_output"),
    ConceptEntry("ACTION", "抽血/驗血", ["抽血", "驗血", "血液檢查"], "dev_output"),
    ConceptEntry("ACTION", "量血壓", ["量血壓", "測血壓"], "dev_output"),
    ConceptEntry("ACTION", "拍痰", ["拍痰"], "dev_output"),
    ConceptEntry("ACTION", "巡房", ["巡房"], "dev_output"),
    ConceptEntry("ACTION", "照顧/顧", ["照顧", "顧"], "dev_output"),
    ConceptEntry("ACTION", "跋倒/跌倒", ["跋倒", "跌倒", "摔倒"], "moe_dict"),  # moe_dict: 跋倒 synonyms=摔倒
    ConceptEntry("ACTION", "停藥/停睏", ["停藥", "停睏"], "dev_output"),
    ConceptEntry("ACTION", "簽名/簽同意書", ["簽名", "簽同意書", "簽"], "dev_output"),
    ConceptEntry("ACTION", "開刀/手術", ["開刀", "手術"], "dev_output"),
    ConceptEntry("ACTION", "急救", ["急救", "救護車"], "dev_output"),
    ConceptEntry("ACTION", "過敏", ["過敏"], "dev_output"),
    ConceptEntry("ACTION", "冷藏/囥冰箱", ["冷藏", "囥冰箱", "囥冰箱冷凍", "放冰箱"], "dev_output"),
    ConceptEntry("ACTION", "抹(塗抹)", ["抹", "塗"], "dev_output"),
    ConceptEntry("ACTION", "解說/解釋", ["解說", "解釋"], "dev_output"),
    ConceptEntry("ACTION", "出院", ["出院"], "dev_output"),
    ConceptEntry("ACTION", "報告出來", ["報告出來", "報告出來矣"], "dev_output"),
]

# ---------- STAFF_ROLE ----------
STAFF_ROLE_ENTRIES = [
    ConceptEntry("STAFF_ROLE", "醫師/醫生", ["醫師", "醫生"], "manual"),  # moe_dict無收錄(現代醫療詞)
    ConceptEntry("STAFF_ROLE", "主治醫師", ["主治醫師", "主治"], "manual"),
    ConceptEntry("STAFF_ROLE", "值班醫師", ["值班醫師", "值班的醫生"], "dev_output"),
    ConceptEntry("STAFF_ROLE", "護理師", ["護理師", "護士", "看護婦"], "moe_dict"),  # moe_dict: 看護婦 synonyms=護士
    ConceptEntry("STAFF_ROLE", "護理長", ["護理長"], "dev_output"),
    ConceptEntry("STAFF_ROLE", "呼吸治療師", ["呼吸治療師"], "manual"),
    ConceptEntry("STAFF_ROLE", "營養師", ["營養師"], "dev_output"),
    ConceptEntry("STAFF_ROLE", "麻醉科醫師", ["麻醉科醫師"], "dev_output"),
    ConceptEntry("STAFF_ROLE", "復健科醫師/治療師", ["復健科醫師", "復健科治療師", "治療師"], "dev_output"),
]

# ---------- BED_LOCATION ----------
BED_LOCATION_ENTRIES = [
    ConceptEntry("BED_LOCATION", "隔壁床", ["隔壁床"], "dev_output"),
    ConceptEntry("BED_LOCATION", "隔壁病房", ["隔壁病房"], "dev_output"),
    ConceptEntry("BED_LOCATION", "對面床", ["對面床", "對面眠床"], "dev_output"),
    ConceptEntry("BED_LOCATION", "三號病房", ["三號病房"], "dev_output"),
    ConceptEntry("BED_LOCATION", "五號床", ["五號床"], "dev_output"),
    ConceptEntry("BED_LOCATION", "急診室", ["急診室"], "dev_output"),
    ConceptEntry("BED_LOCATION", "護理站", ["護理站"], "dev_output"),
    ConceptEntry("BED_LOCATION", "復健科", ["復健科"], "dev_output"),
]

# ---------- PERSON_RELATION ----------
PERSON_RELATION_ENTRIES = [
    ConceptEntry("PERSON_RELATION", "家屬/親人/親情", ["家屬", "親人", "親情"], "dev_output"),
    ConceptEntry("PERSON_RELATION", "太太/某", ["太太", "某"], "dev_output"),
    ConceptEntry("PERSON_RELATION", "小弟/弟弟", ["小弟", "細漢兄弟", "弟弟"], "dev_output"),
    ConceptEntry("PERSON_RELATION", "查某囝/女兒", ["查某囝", "女兒"], "dev_output"),
    ConceptEntry("PERSON_RELATION", "病人/患者", ["病人", "患者"], "dev_output"),
]

# ---------- DRUG ----------
# 藥名多半是音譯外來詞或已固定的漢字寫法, 沒有豐富的台語同義詞, 這裡的
# variants主要收錄「正確的寫法本身」，不收錄觀察到的錯誤/幻覺輸出
# (例如"普拿金"、"盤古靈敏"是LLM的錯誤輸出，不是合法同義詞，絕對不能
# 收進來，那樣會讓評分器把錯誤當成正確)
DRUG_ENTRIES = [
    ConceptEntry("DRUG", "普拿疼", ["普拿疼"], "dev_output"),
    ConceptEntry("DRUG", "盤尼西林", ["盤尼西林"], "dev_output"),
    ConceptEntry("DRUG", "胰島素", ["胰島素"], "dev_output"),
    ConceptEntry("DRUG", "阿斯匹靈", ["阿斯匹靈"], "dev_output"),
    ConceptEntry("DRUG", "抗生素", ["抗生素"], "dev_output"),
    ConceptEntry("DRUG", "降血壓藥", ["降血壓藥", "降血壓的藥仔", "降血壓的"], "dev_output"),
    ConceptEntry("DRUG", "降血糖藥", ["降血糖藥", "降血糖的藥仔", "降血糖的"], "dev_output"),
    ConceptEntry("DRUG", "類固醇藥膏", ["類固醇藥膏", "類固醇的藥膏"], "dev_output"),
    ConceptEntry("DRUG", "消炎藥水", ["消炎藥水", "退火仔"], "dev_output"),
]

# ---------- DOSE ----------
DOSE_ENTRIES = [
    ConceptEntry("DOSE", "六顆/六粒", ["六顆", "六粒"], "dev_output"),
    ConceptEntry("DOSE", "兩次/兩擺", ["兩次", "兩擺"], "dev_output"),
    ConceptEntry("DOSE", "十毫升", ["十毫升"], "dev_output"),
    ConceptEntry("DOSE", "一天三次/一工三擺", ["一天三次", "一工三擺", "一日三擺"], "dev_output"),
    ConceptEntry("DOSE", "一天四次/一工四擺", ["一天四次", "一工四擺", "一日四擺"], "dev_output"),
]

ALL_ENTRIES: list[ConceptEntry] = (
    NEGATION_ENTRIES + TIME_ENTRIES + ACTION_ENTRIES + STAFF_ROLE_ENTRIES
    + BED_LOCATION_ENTRIES + PERSON_RELATION_ENTRIES + DRUG_ENTRIES + DOSE_ENTRIES
)


def build_variant_to_concept_index() -> dict[str, ConceptEntry]:
    """variant字串 -> 對應的ConceptEntry，用最長字串優先比對時可以直接查表。"""
    index: dict[str, ConceptEntry] = {}
    for entry in ALL_ENTRIES:
        for variant in entry.variants:
            index[variant] = entry
    return index


def source_breakdown() -> dict[str, int]:
    """統計每個來源(dev_output/moe_dict/manual/post_hoc_locked)有幾條entry，
    供報告誠實列出同義詞表的組成，不要讓人誤以為全部都是預先定義好的。"""
    counts: dict[str, int] = {}
    for entry in ALL_ENTRIES:
        counts[entry.source] = counts.get(entry.source, 0) + 1
    return counts
