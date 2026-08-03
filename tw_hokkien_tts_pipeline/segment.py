"""
台語斷詞 + 漢字轉台羅層。

真實環境建議串接「臺灣言語工具」(白話字/台羅轉換、斷詞) 或教育部台語辭典
資料庫建立的詞庫。這裡先用最簡單的規則式 mock 實作 (逐字查表 + 找不到就
原樣保留), 讓 pipeline 可以先跑通、之後再替換成專業工具。

輸出格式為 SegmentedWord 清單, 每個詞包含:
  - surface: 台語漢字/漢羅原文
  - tailo: 台羅拼音 (數字調, 例如 tai5-lo5)
  - confidence: 這個詞轉換的信心分數 (mock 版本用「有沒有查到詞庫」簡化)
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


class MockSegmentationBackend(SegmentationBackend):
    """離線可執行的假斷詞/轉台羅後端, 僅用於開發/測試。"""

    name = "mock"

    # 示範詞庫: 台語漢字 -> 台羅 (數字調), 僅供串接測試, 非正式發音資料
    # 佔位符 (__DRUG_0__ 等) 直接視為一個「詞」, 交由後續 romanize 層處理
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
        words: list[SegmentedWord] = []
        remaining = tai_text
        # 依詞長由長到短貪婪比對, 佔位符優先整段視為一詞
        import re

        placeholder_re = re.compile(r"__[A-Z]+_\d+__")

        i = 0
        while i < len(remaining):
            m = placeholder_re.match(remaining, i)
            if m:
                token = m.group(0)
                words.append(SegmentedWord(surface=token, tailo=None, confidence=1.0))
                i += len(token)
                continue

            matched = False
            for surface in sorted(self._DEMO_LEXICON, key=len, reverse=True):
                if remaining.startswith(surface, i):
                    words.append(
                        SegmentedWord(
                            surface=surface,
                            tailo=self._DEMO_LEXICON[surface],
                            confidence=1.0,
                        )
                    )
                    i += len(surface)
                    matched = True
                    break

            if not matched:
                # 查無詞庫: 單字輸出, 信心分數為 0, 標記待補詞庫
                words.append(
                    SegmentedWord(surface=remaining[i], tailo=None, confidence=0.0)
                )
                i += 1

        return SegmentationResult(words=words)


def build_segmentation_backend(config) -> SegmentationBackend:
    if config.segmentation_backend == "mock":
        return MockSegmentationBackend()
    if config.segmentation_backend == "real":
        raise NotImplementedError(
            "real 斷詞後端尚未實作, 請整合臺灣言語工具或教育部台語辭典資料後,"
            "實作一個繼承 SegmentationBackend 的類別"
        )
    raise ValueError(f"未知的 segmentation_backend: {config.segmentation_backend}")
