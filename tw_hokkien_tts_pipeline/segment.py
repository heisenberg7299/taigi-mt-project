"""
台語斷詞 + 漢字轉台羅層。

2026-08-20新增: real後端已串接ChhoeTaigi「2002+台華線頂對照典」91,339筆
詞庫(見taihoa_dict_loader.py), 不再是NotImplementedError。詞庫CSV本身
不隨repo提供, 需要另外下載, 見taihoa_dict_loader.py的下載說明。

2026-08-21新增: real後端會自動補上supplemental_lexicon.py的高頻語法詞
補充表(的/欲/仔/咧/矣/恁/佇/个/予/毋等), 解決主詞庫對這類虛詞系統性
缺漏的OOV問題(見supplemental_lexicon.py模組docstring)。

輸出格式為 SegmentedWord 清單, 每個詞包含:
  - surface: 台語漢字/漢羅原文
  - tailo: 台羅拼音 (數字調, 例如 tai5-lo5)
  - confidence: 這個詞轉換的信心分數 (目前兩個後端都用「有沒有查到詞庫」簡化,
    不是真正的機率信心分數)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SegmentedWord:
    surface: str
    tailo: str | None
    confidence: float  # 0.0 ~ 1.0


@dataclass
class SegmentationResult:
    words: list[SegmentedWord]

    @property
    def unresolved_words(self) -> list[SegmentedWord]:
        """回傳查無台羅讀音的詞, 供人工補詞庫或觸發 fallback。"""
        return [w for w in self.words if w.tailo is None]

    @property
    def mean_confidence(self) -> float:
        if not self.words:
            return 0.0
        return sum(w.confidence for w in self.words) / len(self.words)


class SegmentationBackend(ABC):
    name: str = "base"

    @abstractmethod
    def segment(self, tai_text: str) -> SegmentationResult:
        raise NotImplementedError


def _greedy_lexicon_segment(
    text: str, lexicon: dict[str, str], low_confidence_surfaces: frozenset[str] = frozenset()
) -> SegmentationResult:
    """貪婪最長匹配斷詞, 給MockSegmentationBackend/RealSegmentationBackend
    共用——兩者的差異只在詞庫來源跟大小(8筆demo vs 91,339筆真實資料), 斷詞
    演算法本身跟佔位符處理邏輯不該分別各寫一份, 容易兩邊改到不一致。

    詞庫可能很大(真實資料91k筆), 所以不是每個位置都去跑一次「排序後
    整份詞庫比對」(那是O(n*V), 91k詞庫配上稍長的句子會很慢), 而是從
    詞庫裡最長的詞開始, 每個位置只嘗試「這個位置往後數k個字, k從最長詞長
    遞減到1」, 查表(O(1))看看是不是詞庫裡的詞, 是O(n*max_word_len)——
    效果(貪婪最長匹配)跟原本排序比對的寫法完全一樣, 只是換一種更快的
    實作方式。

    `low_confidence_surfaces`: 查到讀音、但讀音本身還沒經過語料/母語者
    驗證的surface集合(見supplemental_lexicon.py), 這些詞匹配到時信心分數
    給0.5, 不是1.0——區分「詞庫裡有, 而且驗證過」跟「詞庫裡有, 但只是
    推測值」, 不能一視同仁, 不然unresolved_words/mean_confidence這些
    統計會看不出這個差異。"""
    from .protected_tokens import _PLACEHOLDER_RE as placeholder_re

    max_word_len = max((len(k) for k in lexicon), default=1)
    words: list[SegmentedWord] = []
    i = 0
    n = len(text)
    while i < n:
        m = placeholder_re.match(text, i)
        if m:
            token = m.group(0)
            words.append(SegmentedWord(surface=token, tailo=None, confidence=1.0))
            i += len(token)
            continue

        matched = False
        for length in range(min(max_word_len, n - i), 0, -1):
            candidate = text[i : i + length]
            if candidate in lexicon:
                confidence = 0.5 if candidate in low_confidence_surfaces else 1.0
                words.append(SegmentedWord(surface=candidate, tailo=lexicon[candidate], confidence=confidence))
                i += length
                matched = True
                break

        if not matched:
            # 查無詞庫: 單字輸出, 信心分數為 0, 標記待補詞庫
            words.append(SegmentedWord(surface=text[i], tailo=None, confidence=0.0))
            i += 1

    return SegmentationResult(words=words)


class MockSegmentationBackend(SegmentationBackend):
    """離線可執行的假斷詞/轉台羅後端, 僅用於開發/測試。"""

    name = "mock"

    # 示範詞庫: 台語漢字 -> 台羅 (數字調), 僅供串接測試, 非正式發音資料
    # 佔位符 (DRUGA 等純大寫字母格式, 見 protected_tokens.py) 直接視為一個
    # 「詞」, 交由後續 romanize 層處理
    _DEMO_LEXICON = {
        "請": "chhiánn",
        "愛": "ài",
        "記得": "kì-tit",
        "佇": "tī",
        "暗頓": "àm-tǹg",
        "後": "āu",
        "食": "chia̍h",
        "。": "。",
    }

    def segment(self, tai_text: str) -> SegmentationResult:
        return _greedy_lexicon_segment(tai_text, self._DEMO_LEXICON)


class RealSegmentationBackend(SegmentationBackend):
    """串接ChhoeTaigi「2002+台華線頂對照典」91,339筆詞庫的斷詞後端, 見
    taihoa_dict_loader.py。詞庫在建構時就一次載入完畢(不是每次segment()
    才載入), 找不到CSV檔案時建構函式就會直接raise FileNotFoundError,
    不是等到第一次呼叫segment()才發現詞庫是空的——這樣pipeline初始化階段
    就能立刻發現詞庫沒裝好, 不用等到真正處理一句話才出錯。

    `strategy`("first"預設 or "majority", 見taihoa_dict_loader.py)決定
    同一個詞有多種讀音時怎麼選——刻意兩個都能建構, 不是選定一種就固定
    死, 方便直接建兩個backend實例互相比較結果。

    `use_supplemental_lexicon`(預設True): 主詞庫查無讀音(OOV)時, 是否
    fallback去查supplemental_lexicon.py的高頻語法詞補充表——只填補主
    詞庫完全沒有的surface, 不會覆蓋主詞庫已經有的答案(OOV跟多音消歧是
    分開的問題, 見taihoa_dict_loader.py模組docstring)。"""

    name = "real_chhoetaigi"

    def __init__(
        self, csv_path=None, strategy="first", use_supplemental_lexicon=True, supplemental_csv_path=None
    ) -> None:
        from .taihoa_dict_loader import DEFAULT_CSV_PATH, load_taihoa_dict

        self.strategy = strategy
        self.name = f"real_chhoetaigi_{strategy}"  # debug trace要能看出兩個backend比較時是哪一種策略
        self.lexicon = load_taihoa_dict(
            csv_path if csv_path is not None else DEFAULT_CSV_PATH, strategy=strategy
        )
        self.low_confidence_surfaces: frozenset[str] = frozenset()

        if use_supplemental_lexicon:
            from .supplemental_lexicon import DEFAULT_SUPPLEMENTAL_CSV_PATH, load_supplemental_lexicon

            supplemental, low_confidence = load_supplemental_lexicon(
                supplemental_csv_path if supplemental_csv_path is not None else DEFAULT_SUPPLEMENTAL_CSV_PATH
            )
            for surface, reading in supplemental.items():
                if surface not in self.lexicon:  # 主詞庫優先, 補充表只填缺口
                    self.lexicon[surface] = reading
            self.low_confidence_surfaces = frozenset(low_confidence)

    def segment(self, tai_text: str) -> SegmentationResult:
        return _greedy_lexicon_segment(tai_text, self.lexicon, self.low_confidence_surfaces)


def build_segmentation_backend(config) -> SegmentationBackend:
    if config.segmentation_backend == "mock":
        return MockSegmentationBackend()
    if config.segmentation_backend == "real":
        return RealSegmentationBackend()
    raise ValueError(f"未知的 segmentation_backend: {config.segmentation_backend}")
