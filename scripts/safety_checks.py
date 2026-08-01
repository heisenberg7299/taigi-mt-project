"""
階段3：可控式翻譯 pipeline 的四層檢查。
這些檢查是「翻譯完之後」的把關層，不是翻譯本身，
目的是攔截 PLAN.md 記錄過的高風險錯誤類型（否定詞遺失、數字不一致等）。

每個 check_* 函式回傳 (ok: bool, reason: str|None)。
"""
import re

# ---------- 1. 否定詞檢查 ----------

ZH_NEGATION = ["沒有", "不是", "沒", "不會", "不能", "不想", "不需要", "不確定", "並不", "並非", "不"]
NAN_NEGATION = ["無", "袂", "猶未", "毋", "勿", "免", "昧"]


def check_negation(zh: str, nan: str):
    if nan is None:
        return False, "無翻譯結果"
    zh_has_neg = any(m in zh for m in ZH_NEGATION)
    if not zh_has_neg:
        return True, None
    nan_has_neg = any(m in nan for m in NAN_NEGATION)
    if not nan_has_neg:
        return False, f"中文含否定詞但台語輸出未偵測到否定標記：{nan}"
    return True, None


# ---------- 2. 數字一致性檢查 ----------

DIGIT_HAN = "零一二三四五六七八九"


def digit_by_digit(num_str: str) -> str:
    return "".join(DIGIT_HAN[int(c)] for c in num_str)


ROOM_CONTEXT_RE = re.compile(r"(\d+)\s*(號病房|病房|號床|床|室|樓)")
PHONE_RE = re.compile(r"\d{8,}")


def check_number_consistency(zh: str, nan: str):
    if nan is None:
        return False, "無翻譯結果"
    problems = []
    for m in ROOM_CONTEXT_RE.finditer(zh):
        num = m.group(1)
        expected = digit_by_digit(num)
        if expected not in nan:
            problems.append(f"病房/床號 {num} 應逐位數唸成「{expected}」，但輸出中找不到")
    for m in PHONE_RE.finditer(zh):
        num = m.group(0)
        expected = digit_by_digit(num)
        if expected not in nan:
            problems.append(f"電話號碼 {num} 應逐位數唸成「{expected}」，但輸出中找不到")
    if problems:
        return False, "；".join(problems)
    return True, None


# ---------- 3. 醫療術語白名單 ----------

MEDICAL_WHITELIST = [
    "護理師", "護士", "醫師", "醫生", "血壓", "血糖", "體溫", "點滴",
    "復健", "輪椅", "病房", "病床", "手術", "麻醉", "X光", "超音波",
    "掛號", "回診", "出院", "住院", "藥仔", "藥", "傷口", "過敏",
    "氧氣", "呼吸", "心跳", "抽血", "同意書", "探病", "社工",
]


def check_medical_terms(zh: str, nan: str, whitelist=MEDICAL_WHITELIST):
    """檢查中文句子出現的醫療詞，台語輸出裡是否有對應詞（同詞或常見變體）出現過。"""
    if nan is None:
        return False, "無翻譯結果"
    missing = []
    for term in whitelist:
        if term in zh and term not in nan:
            missing.append(term)
    if missing:
        return False, f"醫療術語可能遺漏：{missing}"
    return True, None


# ---------- 4. 長度異常檢查 ----------

def check_length_anomaly(zh: str, nan: str, min_ratio=0.5, max_ratio=2.0):
    if nan is None:
        return False, "無翻譯結果"
    zh_len = len(zh)
    nan_len = len(nan)
    if zh_len == 0:
        return True, None
    ratio = nan_len / zh_len
    if ratio < min_ratio or ratio > max_ratio:
        return False, f"長度比異常：中文{zh_len}字 -> 台語{nan_len}字（比例{ratio:.2f}）"
    return True, None


# ---------- 5. 陷阱字（語意反轉）檢查 ----------
# 目前只收錄實測驗證過、有把握的一組（見 PLAN.md「今天的實測教訓」第5點）。
# 這份清單刻意只放有把握的條目，不要為了「看起來完整」就自己加未經確認的字對——
# 亂加反而會製造假警報，比沒有檢查還糟。之後應該靠驗證平台測試者的備註持續補充。

TRAP_WORDS = [
    {
        "zh_re": re.compile(r"慢慢走|走路|怎麼走|走\d+步|走了\d+步|走走"),
        "wrong_char": "走",
        "correct_char": "行",
        "explanation": (
            "中文「走」在這類語境是「行走」，台語對應詞是「行(kiânn)」；"
            "台語「走(tsáu)」意思是「跑」，字面照搬會造成語意反轉"
            "（例如「請慢慢走」變成「請慢慢跑」）"
        ),
    },
]


def check_trap_words(zh: str, nan: str):
    if nan is None:
        return False, "無翻譯結果"
    problems = []
    for trap in TRAP_WORDS:
        if trap["zh_re"].search(zh) and trap["wrong_char"] in nan and trap["correct_char"] not in nan:
            problems.append(f"「{trap['wrong_char']}」語意反轉風險：{trap['explanation']}")
    if problems:
        return False, "；".join(problems)
    return True, None


ALL_CHECKS = [
    ("negation", check_negation),
    ("number_consistency", check_number_consistency),
    ("medical_terms", check_medical_terms),
    ("length_anomaly", check_length_anomaly),
    ("trap_words", check_trap_words),
]


def run_all_checks(zh: str, nan: str):
    results = {}
    for name, fn in ALL_CHECKS:
        ok, reason = fn(zh, nan)
        results[name] = {"ok": ok, "reason": reason}
    return results
