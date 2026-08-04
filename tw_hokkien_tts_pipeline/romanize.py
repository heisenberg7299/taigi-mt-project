"""
台羅正規化 + 連讀變調 (tone sandhi) 處理。

台語 (泉漳片/Hokkien) 的連讀變調規則概略如下 (以數字調表示, 陰陽調略有差異,
這裡採用常見的簡化八聲調循環, 僅供 demo 與單元測試, 正式上線前必須由台語
語言學專業人士審核, 不同腔調 / 白話字 vs 台羅 的變調表可能不同):

    非句尾 (前字) 變調方向:
        1 -> 7 -> 3 -> 2 -> 1  (陰平/陰去/陰上 循環)
        5 -> 7 或 3            (陽平, 依腔調而定, 這裡採 7)
        4 -> 8 (短促入聲, -p/-t/-k 韻尾)
        8 -> 4 (短促入聲, -h 韻尾) / 或 3 (依腔調)
    句尾/詞組最後一字: 維持本調, 不變調

本模組操作的是「數字調」表示法 (例如 tai5), 因為變調規則以調號為單位最
容易表達與測試。詞庫若只有附加符號調 (diacritic, 例如 tâi) 版本的台羅
(目前 segment.py 的 mock 詞庫即是如此), 則暫不自動套用變調, 只會照詞庫
原樣輸出, 並在結果中標記 sandhi_applied=False, 提醒需要先建立
diacritic <-> 數字調 的雙向轉換表, 才能讓變調規則正確套用在最終發音上。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .segment import SegmentationResult, SegmentedWord

_NUMBERED_SYLLABLE_RE = re.compile(r"^([a-zA-Z]+)([1-8])$")

# 簡化版連讀變調循環表 (前字調 -> 變調後的調號)
_SANDHI_CYCLE = {
    1: 7,
    7: 3,
    3: 2,
    2: 1,
    5: 7,
    4: 8,
    8: 4,
}


@dataclass
class RomanizedWord:
    surface: str
    tailo: str
    resolved: bool  # 是否有查到詞庫讀音 (非 fallback)


@dataclass
class RomanizationResult:
    text: str  # 供 TTS 使用的完整台羅字串 (含未解析的 placeholder / 原字 fallback)
    words: list[RomanizedWord]
    unresolved_count: int
    mean_confidence: float


def apply_tone_sandhi_numbered(syllables: list[str]) -> list[str]:
    """對「數字調」音節序列套用簡化連讀變調, 最後一個音節維持本調。

    輸入範例: ["tai5", "lo5"] -> 輸出: ["tai7", "lo5"]
    非數字調格式 (例如 diacritic 或不合法輸入) 的音節會原樣返回。
    """
    if not syllables:
        return syllables

    result = list(syllables)
    for i in range(len(result) - 1):  # 最後一個音節不變調
        m = _NUMBERED_SYLLABLE_RE.match(result[i])
        if not m:
            continue
        base, tone_str = m.group(1), int(m.group(2))
        new_tone = _SANDHI_CYCLE.get(tone_str, tone_str)
        result[i] = f"{base}{new_tone}"
    return result


def romanize(segmentation: SegmentationResult, apply_tone_sandhi: bool = False) -> RomanizationResult:
    """把斷詞結果轉成最終要送進 TTS 的台羅字串。

    未解析的詞 (含 Protected Token 佔位符) 直接保留原文 surface, 交由
    pipeline 後續的 unmask_to_tailo 或人工檢查處理; 這裡不假裝猜測發音。

    apply_tone_sandhi 預設 False：連讀變調規則(見上方模組docstring)只是
    簡化版demo, 且只對「數字調」音節有效, 詞庫目前多是diacritic格式(不受影響)。
    開啟前應先由台語語言學背景的人確認規則是否適用於目標腔調。
    """
    words: list[RomanizedWord] = []
    parts: list[str] = []

    for w in segmentation.words:
        if w.tailo:
            words.append(RomanizedWord(surface=w.surface, tailo=w.tailo, resolved=True))
            parts.append(w.tailo)
        else:
            words.append(RomanizedWord(surface=w.surface, tailo=w.surface, resolved=False))
            parts.append(w.surface)

    if apply_tone_sandhi:
        parts = apply_tone_sandhi_numbered(parts)

    text = "-".join(p for p in parts if p and p != "。")
    if any(w.surface == "。" for w in segmentation.words):
        text += "。"

    unresolved = sum(1 for w in words if not w.resolved)
    return RomanizationResult(
        text=text,
        words=words,
        unresolved_count=unresolved,
        mean_confidence=segmentation.mean_confidence,
    )
