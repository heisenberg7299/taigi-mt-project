"""
Protected Token 遮罩 / 還原模組。

送進外部翻譯平台前, 先把藥名、人名、劑量等醫療關鍵資訊替換成佔位符
(例如 __DRUG_0__, __PERSON_0__, __DOSE_0__), 避免翻譯模型誤譯、漏譯
或擅自改寫這些資訊; 翻譯完成後再用人工校正過的發音詞庫把佔位符換回
對應的台羅讀音。

注意: 這裡的偵測規則 (正則表示式 + 詞庫比對) 只是起點, 實際上線前必須:
  1. 由醫療專業人員審核詞庫涵蓋率
  2. 針對院內常用藥名/劑型建立專屬詞庫
  3. 對於偵測不到的實體, 視設定決定是否直接擋下 (fail-closed) 而非放行
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# 佔位符格式: __TYPE_INDEX__, 選用不會被中文分詞器/翻譯器拆開的英數字組合
_PLACEHOLDER_RE = re.compile(r"__([A-Z]+)_(\d+)__")

# 劑量: 數字 + 常見單位 (毫克/公克/毫升/顆/錠/單位...)
_DOSE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|ml|g|毫克|公克|克|毫升|c\.?c\.?|顆|錠|包|單位|IU)",
    re.IGNORECASE,
)


@dataclass
class ProtectedSpan:
    """一段被遮罩的原文, 以及它對應的台羅讀音 (若有的話)。"""

    kind: str  # DRUG / PERSON / DOSE
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
    ) -> None:
        # drug_lexicon: {"盤尼西林": "puân-nî-se-lîm", ...}
        # 值為 None 表示「已知是藥名, 但尚未有人工校正過的台羅讀音」,
        # 會被遮罩、但 coverage() 會視為未涵蓋, 觸發 fail-closed 檢查。
        # 實際讀音需由台語專業人士確認, 這裡只提供結構, 不內建未經審核的資料
        self.drug_lexicon = drug_lexicon or {}
        self.person_names = person_names or set()

    def mask(self, text: str) -> MaskResult:
        spans: list[ProtectedSpan] = []
        counters = {"DRUG": 0, "PERSON": 0, "DOSE": 0}

        # 藥名: 依詞庫做最長字串優先比對, 避免子字串誤蓋
        masked = self._mask_literal_terms(text, spans, counters)

        # 人名
        for name in sorted(self.person_names, key=len, reverse=True):
            masked = self._mask_one(masked, name, "PERSON", spans, counters)

        # 劑量 (正則)
        masked = self._mask_regex(masked, _DOSE_RE, "DOSE", spans, counters)

        return MaskResult(masked_text=masked, spans=spans)

    def _mask_literal_terms(
        self, text: str, spans: list[ProtectedSpan], counters: dict[str, int]
    ) -> str:
        masked = text
        for drug in sorted(self.drug_lexicon, key=len, reverse=True):
            masked = self._mask_one(
                masked, drug, "DRUG", spans, counters, tailo=self.drug_lexicon.get(drug)
            )
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
            placeholder = f"__{kind}_{idx}__"
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
            placeholder = f"__{kind}_{idx}__"
            spans.append(ProtectedSpan(kind, m.group(0), placeholder))
            return placeholder

        return pattern.sub(_sub, text)

    def unmask_text(self, text: str, spans: list[ProtectedSpan]) -> str:
        """把佔位符換回原始中文 (用於一致性檢查 / debug trace)。"""
        result = text
        for span in spans:
            result = result.replace(span.placeholder, span.original)
        return result

    def unmask_to_tailo(self, text: str, spans: list[ProtectedSpan]) -> str:
        """把佔位符換回台羅讀音 (供 TTS 使用)。

        若某個 span 沒有對應台羅讀音 (詞庫沒收錄), 保留原文中文字並在
        debug trace 標記, 以便人工補詞庫, 而不是讓 TTS 拿到未知拼音亂讀。
        """
        result = text
        for span in spans:
            replacement = span.tailo if span.tailo else span.original
            result = result.replace(span.placeholder, replacement)
        return result

    def coverage(self, spans: list[ProtectedSpan]) -> float:
        """回傳有台羅讀音對應 (DRUG 類) 的涵蓋率, 供醫療安全門檻檢查。"""
        drug_spans = [s for s in spans if s.kind == "DRUG"]
        if not drug_spans:
            return 1.0
        covered = sum(1 for s in drug_spans if s.tailo)
        return covered / len(drug_spans)
