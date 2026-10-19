"""
詞庫schema升級: 把DRUG_LEXICON/MEDICAL_TITLE_LEXICON/DEVICE_LEXICON這種
「一個中文詞對一個台羅讀音(或None)」的扁平dict, 升級成「一個中文詞可以
對應多個候選讀音」的結構——因為現實中一個華語/台語詞常常有文讀/白讀、
或依語境不同的多種唸法, 一對一結構表達不出來, 見這次架構調整討論的
原始問題描述。

## 這是加法, 不是取代

`ProtectedTokenGuard`(protected_tokens.py)吃的是`dict[str, str | None]`
(一個詞一個讀音字串或None), 這個模組**不改**那個介面——`from_flat_dict()`
負責把既有的DRUG_LEXICON這類扁平dict包裝成`LexiconTerm`結構,
`primary_tailo()`則負責從結構裡挑出「目前最推薦的一個讀音」轉回單一字串,
所以既有call site(assistant_service/*.py等)完全不用改。之後如果真的
要收多候選讀音(例如同一個藥名文讀/白讀都收), 才需要真的改
`ProtectedTokenGuard`去消費多候選, 這裡先把資料結構準備好。

## 沒有假造資料

這裡刻意不幫DRUG_LEXICON/MEDICAL_TITLE_LEXICON/DEVICE_LEXICON裡任何一個
None值填上真正的候選讀音——那些None代表「還沒有人工/語料驗證過的讀音」,
schema升級不等於資料被驗證了, `from_flat_dict()`轉換後對應的
`LexiconEntry.verified`一樣是False, 待驗證的狀態必須原樣保留、不能因為
換了個資料結構就看起來像是「已經處理好了」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReadingType(Enum):
    LITERARY = "literary"  # 文讀
    COLLOQUIAL = "colloquial"  # 白讀
    UNKNOWN = "unknown"  # 尚未分類文白讀 (例如既有扁平dict轉過來的資料)


class RiskLevel(Enum):
    CRITICAL = "critical"  # 唸錯/漏掉會造成醫療安全風險(藥名/劑量/病房號等)
    MODERATE = "moderate"  # 唸錯會造成理解障礙但風險較低(職稱/器材等)
    LOW = "low"  # 一般詞彙


@dataclass
class LexiconEntry:
    """單一候選讀音。"""

    tailo: str | None  # None表示已知有這個詞條, 但還沒有校正過的台羅讀音
    reading_type: ReadingType = ReadingType.UNKNOWN
    domain: str = "general"  # 例如 "medical"
    risk: RiskLevel = RiskLevel.LOW
    verified: bool = False  # 是否已經過母語者/語料驗證(不是「有沒有填讀音」)
    source: str | None = None  # 資料來源, 例如 "moe_dict" / "manual" / "flat_dict_migration"
    notes: str | None = None


@dataclass
class LexiconTerm:
    """一個中文詞條(hanji headword), 可能對應多個候選讀音。"""

    hanji: str
    candidates: list[LexiconEntry] = field(default_factory=list)

    def verified_candidates(self) -> list[LexiconEntry]:
        return [c for c in self.candidates if c.verified and c.tailo]


def from_flat_dict(
    flat: dict[str, str | None],
    *,
    domain: str = "general",
    risk: RiskLevel = RiskLevel.LOW,
    source: str = "flat_dict_migration",
) -> dict[str, LexiconTerm]:
    """把既有的`{"詞": "讀音"|None}`扁平詞庫包裝成`LexiconTerm`結構。

    每個詞條目前只會有一個候選(因為來源資料本身就只有一個), `verified`
    只有在原本的值不是None時才是True——None不是「已驗證但沒有讀音」,
    是「還沒驗證」, 這個語意在轉換過程中必須保留, 不能被schema升級抹掉。
    """
    result: dict[str, LexiconTerm] = {}
    for hanji, tailo in flat.items():
        entry = LexiconEntry(
            tailo=tailo,
            domain=domain,
            risk=risk,
            verified=tailo is not None,
            source=source,
        )
        result[hanji] = LexiconTerm(hanji=hanji, candidates=[entry])
    return result


def primary_tailo(term: LexiconTerm) -> str | None:
    """從一個詞條的候選讀音裡挑出「目前最推薦」的一個, 轉回單一字串,
    供還在吃`dict[str, str | None]`介面的既有call site(例如
    `ProtectedTokenGuard`)使用。

    目前的挑選規則很單純: 有已驗證候選就取第一個已驗證的, 否則回傳None
    (即使有未驗證的候選, 也不冒然拿來用——寧可讓呼叫端知道「這裡缺一個
    驗證過的讀音」, 也不要塞一個沒人確認過的猜測進生產環境)。多候選情境
    下要怎麼依語境挑選, 是之後真正需要消費多候選時才要解決的問題,
    這裡先不假裝有答案。
    """
    verified = term.verified_candidates()
    return verified[0].tailo if verified else None


def to_flat_dict(terms: dict[str, LexiconTerm]) -> dict[str, str | None]:
    """反向轉換: 把`LexiconTerm`結構壓回`ProtectedTokenGuard`吃的扁平
    `dict[str, str | None]`格式, 用`primary_tailo()`挑候選。"""
    return {hanji: primary_tailo(term) for hanji, term in terms.items()}
