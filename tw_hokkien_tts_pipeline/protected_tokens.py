"""
Protected Token 遮罩 / 還原模組。

送進外部翻譯平台前, 先把藥名、人名、劑量等醫療關鍵資訊替換成佔位符,
避免翻譯模型誤譯、漏譯或擅自改寫這些資訊; 翻譯完成後再用人工校正過的
發音詞庫把佔位符換回對應的台羅讀音(或原文漢字, 供不同TTS backend使用)。

佔位符格式: 純大寫英文單字 (例如 DRUGA, PERSONB, DOSEC), 不用底線/數字/括號。
這不是隨便挑的格式, 是 scripts/protected_token_pipeline.py 實測過的結論:
  - [PERSON1] 這種帶括號+數字的格式: 不可靠, 有時被丟掉, 有時被當成語意
    提示重新生成成別的字
  - PERSONA 這種純大寫英文單字 (無括號、無數字): 實測穩定通過, 推測是
    LLM把它當成「不需要翻譯的外語詞」直接複製過去
同一種類別的第N個實體用第N個字母 (A, B, C, ... Z, AA, AB, ...), 用字母而非
數字index, 是延續同一份實測結論的格式, 且刻意不用固定3個一組後折返覆用
(index % 3) 的寫法, 避免超過3個同類實體時，第4個又變回A而蓋掉第1個的映射。

注意: 這裡的偵測規則 (正則表示式 + 詞庫比對) 只是起點, 實際上線前必須:
  1. 由醫療專業人員審核詞庫涵蓋率
  2. 針對院內常用藥名/劑型建立專屬詞庫
  3. 對於偵測不到的實體, 視設定決定是否直接擋下 (fail-closed) 而非放行

## 類別涵蓋範圍 (2026-08-17新增ROOM/TIME/TITLE/DEVICE)

新增的四個類別刻意都取單一英文單字當kind名稱 (ROOM, TIME, TITLE, DEVICE),
不是ROOM_ID/MEDICAL_TITLE這種帶底線的複合詞——因為佔位符格式是
"{kind}{字母尾碼}" 直接串接, kind名稱裡如果有底線, 佔位符就會變成
"ROOM_IDA" 這種帶底線的字串, 違反上面已經實測驗證過的「純大寫英文單字,
不用底線/數字/括號」格式結論, 可能重新引入同樣的LLM不穩定問題。

沿用原本DRUG/PERSON/DOSE的設計分工: 這個模組只提供「偵測機制」(正則/
詞庫比對), 實際詞庫資料 (例如醫療職稱/器材詞庫) 刻意不內建在這裡, 由
呼叫端 (見 scripts/eval_translation_safety.py 的 DRUG_LEXICON/PERSON_NAMES)
提供、審核、擴充——原因同DRUG_LEXICON: 未經母語者/醫療人員審核的詞庫
不該混進正式程式碼裡當作預設值。

刻意不把NEGATION做成protected token: 遮罩會把「不」「沒有」這類否定詞
換成佔位符, 等於拿掉翻譯模型判斷句子語意所需的關鍵訊號, 這跟遮罩藥名/
人名 (翻譯模型不需要「理解」藥名本身, 只需要原樣保留) 的情境完全不同。
否定詞的正確處理方式是翻譯後檢查 (見 scripts/safety_checks.py 的
negation check, 比對原文跟譯文的否定語意是否一致), 不是翻譯前遮罩。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 目前支援的類別, 順序即偵測順序 (見 mask())
_KIND_NAMES = ("DRUG", "TITLE", "DEVICE", "PERSON", "DOSE", "ROOM", "TIME")

# 佔位符格式: KIND + 字母尾碼 (例如 DRUGA), 用來掃描/驗證文字裡的佔位符
_PLACEHOLDER_RE = re.compile(r"(?:" + "|".join(_KIND_NAMES) + r")[A-Z]+")

# 劑量: 數字 + 常見單位 (毫克/公克/毫升/顆/錠/單位...)
_DOSE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|ml|g|毫克|公克|克|毫升|c\.?c\.?|顆|錠|包|單位|IU)",
    re.IGNORECASE,
)

# 病房/床號/診間: 數字(可帶英文字母前綴, 例如"A3") + 病房/床/室/診間
_ROOM_RE = re.compile(r"[A-Za-z]?\d{1,4}(?:號)?(?:病房|床|室|診間)")

# 時刻: "早上八點半"/"下午三點整"/"九點三十分"這類中文時刻講法, 或"14:30"
# 這種數字時刻。刻意不含日期 (年/月/日)——日期讀法牽涉到跟劑量/病房號不同
# 的唸法規則, 留給 numeric_reading.py 未來擴充, 不在這裡的偵測範圍內。
_TIME_RE = re.compile(
    r"(?:(?:凌晨|清晨|早上|上午|中午|下午|傍晚|晚上|半夜)?"
    r"(?:[0-9]{1,2}|[一二三四五六七八九十]{1,3})點(?:半|整)?"
    r"(?:(?:[0-9]{1,2}|[一二三四五六七八九十]{1,3})分)?"
    r"|\d{1,2}:\d{2})"
)


def _build_combined_replace(text: str, lookup: dict[str, str]) -> str:
    """一次性用單一regex pass把 lookup 裡所有已知佔位符換回對應值。

    不能對每個佔位符各自呼叫 str.replace() 或各自套用邊界正則再依序處理:
    中文原句常常是「藥名+劑量」緊接在一起沒有分隔字元 (例如「盤尼西林120毫克」),
    遮罩後就會變成「DRUGADOSEA」這種兩個佔位符黏在一起的字串。因為佔位符
    只由大寫字母組成，這種情況下不管用簡單的str.replace()(可能因為
    "DRUGA"剛好是"DRUGAA"的前綴而誤吃鄰居的字元)或是「左右不能接A-Z字母」
    的邊界正則(會因為緊鄰的另一個佔位符本身就是A-Z字母而永遠比對不到)
    都會出錯。

    正確做法是把所有「已知確實存在的佔位符字串」組成一個 alternation
    pattern(依長度由長到短排序, 避免像"DRUGA"/"DRUGAA"這種一個是另一個
    前綴的情況比對到較短的那個)，一次掃描整個字串、按實際切分位置逐一
    替換 —— 因為每個佔位符長度固定已知，regex引擎會依序精確比對出
    "DRUGA"+"DOSEA"這樣正確的切分，不會誤判邊界。
    """
    if not lookup:
        return text
    ordered = sorted(lookup, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(p) for p in ordered))
    return pattern.sub(lambda m: lookup[m.group(0)], text)


def index_to_letter_suffix(index: int) -> str:
    """0->A, 1->B, ..., 25->Z, 26->AA, 27->AB, ...

    類似試算表欄位命名, 用意是同一類別超過26個實體時也不會折返覆用同一個
    字母(那樣會讓後面的實體覆蓋掉前面已經配好的映射, 造成還原時對應錯誤)。
    """
    n = index + 1  # 轉成1-based方便算
    letters = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


@dataclass
class ProtectedSpan:
    """一段被遮罩的原文, 以及它對應的台羅讀音 (若有的話)。"""

    kind: str  # DRUG / TITLE / DEVICE / PERSON / DOSE / ROOM / TIME
    original: str
    placeholder: str
    tailo: str | None = None  # 由發音詞庫查到的台羅讀音, 供最終還原用


@dataclass
class MaskResult:
    masked_text: str
    spans: list[ProtectedSpan] = field(default_factory=list)


class ProtectedTokenGuard:
    """負責把敏感詞遮罩成佔位符, 之後再依台羅發音詞庫還原。"""

    def __init__(
        self,
        drug_lexicon: dict[str, str | None] | None = None,
        person_names: set[str] | None = None,
        medical_title_lexicon: dict[str, str | None] | None = None,
        device_lexicon: dict[str, str | None] | None = None,
    ) -> None:
        # drug_lexicon / medical_title_lexicon / device_lexicon: {"盤尼西林": "puân-nî-se-lîm", ...}
        # 值為 None 表示「已知是這個類別的詞, 但尚未有人工校正過的台羅讀音」,
        # 會被遮罩、但 coverage() 會視為未涵蓋, 觸發 fail-closed 檢查。
        # 實際讀音需由台語專業人士確認, 這裡只提供結構, 不內建未經審核的資料
        self.drug_lexicon = drug_lexicon or {}
        self.person_names = person_names or set()
        self.medical_title_lexicon = medical_title_lexicon or {}
        self.device_lexicon = device_lexicon or {}

    def mask(self, text: str) -> MaskResult:
        spans: list[ProtectedSpan] = []
        counters = {kind: 0 for kind in _KIND_NAMES}

        # 藥名/醫療職稱/醫療器材: 依詞庫做最長字串優先比對, 避免子字串誤蓋。
        # 職稱/器材放在人名之前, 避免像「陳護理師」這種詞裡的職稱先被人名
        # 詞庫的姓氏比對搶走 (目前person_names是全名比對所以還不會衝突,
        # 但保留這個順序讓未來若改成姓氏+職稱組合偵測時行為一致)
        masked = self._mask_literal_terms(text, self.drug_lexicon, "DRUG", spans, counters)
        masked = self._mask_literal_terms(masked, self.medical_title_lexicon, "TITLE", spans, counters)
        masked = self._mask_literal_terms(masked, self.device_lexicon, "DEVICE", spans, counters)

        # 人名
        for name in sorted(self.person_names, key=len, reverse=True):
            masked = self._mask_one(masked, name, "PERSON", spans, counters)

        # 劑量/病房床號/時刻 (正則, 無詞庫——讀法由 numeric_reading.py 之後
        # 視需要另外產生, 這裡先只負責偵測跟遮罩)
        masked = self._mask_regex(masked, _DOSE_RE, "DOSE", spans, counters)
        masked = self._mask_regex(masked, _ROOM_RE, "ROOM", spans, counters)
        masked = self._mask_regex(masked, _TIME_RE, "TIME", spans, counters)

        return MaskResult(masked_text=masked, spans=spans)

    def _mask_literal_terms(
        self,
        text: str,
        lexicon: dict[str, str | None],
        kind: str,
        spans: list[ProtectedSpan],
        counters: dict[str, int],
    ) -> str:
        masked = text
        for term in sorted(lexicon, key=len, reverse=True):
            masked = self._mask_one(masked, term, kind, spans, counters, tailo=lexicon.get(term))
        return masked

    @staticmethod
    def _mask_one(
        text: str,
        term: str,
        kind: str,
        spans: list[ProtectedSpan],
        counters: dict[str, int],
        tailo: str | None = None,
    ) -> str:
        if term and term in text:
            idx = counters[kind]
            counters[kind] += 1
            placeholder = f"{kind}{index_to_letter_suffix(idx)}"
            spans.append(ProtectedSpan(kind, term, placeholder, tailo))
            text = text.replace(term, placeholder)
        return text

    @staticmethod
    def _mask_regex(
        text: str,
        pattern: re.Pattern,
        kind: str,
        spans: list[ProtectedSpan],
        counters: dict[str, int],
    ) -> str:
        def _sub(m: re.Match) -> str:
            idx = counters[kind]
            counters[kind] += 1
            placeholder = f"{kind}{index_to_letter_suffix(idx)}"
            spans.append(ProtectedSpan(kind, m.group(0), placeholder))
            return placeholder

        return pattern.sub(_sub, text)

    def unmask_text(self, text: str, spans: list[ProtectedSpan]) -> str:
        """把佔位符換回原始中文 (用於一致性檢查 / debug trace)。"""
        lookup = {span.placeholder: span.original for span in spans}
        return _build_combined_replace(text, lookup)

    def unmask_to_tailo(self, text: str, spans: list[ProtectedSpan]) -> str:
        """把佔位符換回台羅讀音 (供 TTS 使用)。

        若某個 span 沒有對應台羅讀音 (詞庫沒收錄), 保留原文中文字並在
        debug trace 標記, 以便人工補詞庫, 而不是讓 TTS 拿到未知拼音亂讀。
        """
        lookup = {span.placeholder: (span.tailo if span.tailo else span.original) for span in spans}
        return _build_combined_replace(text, lookup)

    # 這三類是「詞庫比對」類別, 讀音來自人工校正過的詞庫, 才需要納入涵蓋率
    # 檢查; PERSON目前沒有台羅詞庫機制、DOSE/ROOM/TIME是正則偵測+數字
    # 讀法 (見numeric_reading.py) 而非詞庫比對, 所以不算進這裡
    _LEXICON_BASED_KINDS = ("DRUG", "TITLE", "DEVICE")

    def coverage(self, spans: list[ProtectedSpan]) -> float:
        """回傳詞庫比對類別 (DRUG/TITLE/DEVICE) 有台羅讀音對應的涵蓋率,
        供醫療安全門檻檢查。"""
        lexicon_spans = [s for s in spans if s.kind in self._LEXICON_BASED_KINDS]
        if not lexicon_spans:
            return 1.0
        covered = sum(1 for s in lexicon_spans if s.tailo)
        return covered / len(lexicon_spans)
