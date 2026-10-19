"""
把這學期做的發音消歧研究（ChhoeTaigi辭典 + 母語者盲測黃金標準）接成一個
可以在合成語音「當下」使用的發音決策器——跟`pronunciation_overrides.py`
（教育部TAT-MOE語料庫統計出來的固定表）是完全不同的資料來源與方法，
刻意分開、不共用同一張表，交叉驗證結果見
`reports/pronunciation_overrides_crosscheck.md`。

## 決策順序（信心由高到低）

1. **黃金標準已驗證**（`native_verified=true`）：這個surface在母語者盲測
   裡確認過的讀音。**只有在這個surface在黃金標準裡從頭到尾只驗證出
   同一種讀音時才採用**——如果同一個surface在不同語境驗證出不同讀音
   （代表這是真正的文白異讀/多義字，見`scripts/crosscheck_overrides_
   against_benchmark.py`的CONTEXT_CONFLICT邏輯），代表單一固定答案本來
   就是錯的做法，這裡會直接跳過，退回下一層。
2. **ChhoeTaigi辭典多數決**：這個surface不在黃金標準裡，但在辭典裡查得到
   不只一種讀音時，取CSV裡出現次數最多的讀音（跟`taihoa_dict_loader.py`
   的"majority" strategy同一套邏輯，不是重新發明一套）。
3. **辭典裡只有一種讀音**：不算真正的多音字，直接採用。
4. **辭典查無此字**：不處理，讓neurlang自己的phonemizer決定（跟現況一樣，
   不會更差）。

## 已知限制（誠實列出）

- 跟`pronunciation_overrides.py`一樣，只能對「漢字數」跟「讀音音節數」
  對得起來的詞做替換，對不起來的直接跳過不修改。
- 同一個字在同一句話裡出現兩次、但分屬不同詞彙（正確讀音理論上該不同）
  時，這裡跟`pronunciation_overrides.py`一樣是「值→值」取代，仍然無法
  區分同一句內的兩次出現——這是繼承自現有override機制本身的限制，不是
  這支模組新引入的問題。
- 黃金標準目前只有v1的12筆、v2持續標註中，覆蓋率遠不如經過91,339筆
  辭典/91k語料庫的統計方法，量會隨v2/v3擴充持續變好，不是一步到位。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .tailo_ipa_converter import tailo_syllable_to_ipa
from .taihoa_dict_loader import DEFAULT_CSV_PATH, _readings_by_surface, _resolve_reading

ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_PATHS = [
    ROOT / "tw_hokkien_tts_pipeline" / "tests" / "data" / "ambiguity_gold_benchmark_v1.jsonl",
    ROOT / "tw_hokkien_tts_pipeline" / "tests" / "data" / "ambiguity_gold_benchmark_v2_in_corpus.jsonl",
]


@dataclass
class ResolutionEntry:
    surface: str
    candidates: list[str]
    chosen_reading: str
    source: str  # "gold_verified" | "dictionary_majority" | "dictionary_unambiguous"
    applied: bool  # 漢字數/音節數對不對得起來，決定了有沒有真的套用成override
    reason: str = ""


@dataclass
class ResolutionResult:
    hanji_text: str
    entries: list[ResolutionEntry] = field(default_factory=list)
    ipa_overrides: dict[str, str] = field(default_factory=dict)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class ChhoeTaigiPronunciationResolver:
    """一次性載入辭典+黃金標準，之後可以重複呼叫`resolve_sentence()`，
    避免每個請求都重新掃描91,339列CSV（見`taihoa_dict_loader.py`
    `glosses_for_surface()`docstring提過的效能取捨，這裡選擇快取版本，
    因為這個resolver是要接進即時互動的demo介面，不是一次性腳本）。
    """

    def __init__(self, csv_path: Path | str = DEFAULT_CSV_PATH):
        self.csv_path = Path(csv_path)
        self._readings_by_surface: dict[str, list[str]] = {}
        self._gold_readings: dict[str, str] = {}
        self._gold_conflicts: set[str] = set()
        self._max_surface_len = 1
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.csv_path.exists():
            self._readings_by_surface, _ = _readings_by_surface(self.csv_path)
        else:
            self._readings_by_surface = {}

        gold_by_surface: dict[str, set[str]] = {}
        for path in BENCHMARK_PATHS:
            for row in _load_jsonl(path):
                if row.get("native_verified") and row.get("gold_reading"):
                    gold_by_surface.setdefault(row["surface"], set()).add(row["gold_reading"])

        for surface, readings in gold_by_surface.items():
            if len(readings) == 1:
                self._gold_readings[surface] = next(iter(readings))
            else:
                # 同一個surface黃金標準驗證出不只一種讀音——真正的文白異讀/
                # 多義字，單一固定值本來就是錯的做法，記錄下來但不採用
                self._gold_conflicts.add(surface)

        all_surfaces = set(self._readings_by_surface) | set(self._gold_readings)
        self._max_surface_len = max((len(s) for s in all_surfaces), default=1)
        self._loaded = True

    def _candidate_readings(self, surface: str) -> list[str] | None:
        return self._readings_by_surface.get(surface)

    def _resolve_surface(self, surface: str) -> ResolutionEntry | None:
        candidates = self._candidate_readings(surface)
        if surface in self._gold_readings:
            return ResolutionEntry(
                surface=surface,
                candidates=candidates or [self._gold_readings[surface]],
                chosen_reading=self._gold_readings[surface],
                source="gold_verified",
                applied=False,  # 是否真的套用要等音節數比對後才知道，先設False
            )
        if surface in self._gold_conflicts:
            # 已知是真正的多音字，母語者黃金標準也證實不只一種答案——
            # 不裝作能用單一固定值解決，交給下一層字典多數決(仍然只是
            # 統計近似，不是真正的上下文判斷，但至少不是憑空從標準表挑一個)
            if candidates and len(set(candidates)) > 1:
                chosen = _resolve_reading(candidates, "majority")
                return ResolutionEntry(
                    surface=surface, candidates=candidates, chosen_reading=chosen,
                    source="dictionary_majority", applied=False,
                    reason="黃金標準證實此字為真正多音字(不同語境有不同正確讀音)，"
                           "無法用單一固定值代表，此處退回字典多數決近似",
                )
            return None
        if not candidates:
            return None
        if len(set(candidates)) == 1:
            return ResolutionEntry(
                surface=surface, candidates=candidates, chosen_reading=candidates[0],
                source="dictionary_unambiguous", applied=False,
            )
        chosen = _resolve_reading(candidates, "majority")
        return ResolutionEntry(
            surface=surface, candidates=candidates, chosen_reading=chosen,
            source="dictionary_majority", applied=False,
        )

    def resolve_sentence(self, hanji_text: str) -> ResolutionResult:
        """對一整句台語漢字做貪婪最長匹配：從左到右找詞庫/黃金標準裡有的
        最長surface，逐一解析讀音，回傳每個決策的完整記錄跟可以直接套用
        到phonemizer輸出的IPA override表。"""
        self._ensure_loaded()
        result = ResolutionResult(hanji_text=hanji_text)

        i = 0
        n = len(hanji_text)
        while i < n:
            matched = False
            max_len = min(self._max_surface_len, n - i)
            for length in range(max_len, 0, -1):
                surface = hanji_text[i : i + length]
                entry = self._resolve_surface(surface)
                if entry is None:
                    continue
                syllables = entry.chosen_reading.split("-")
                if len(syllables) == len(surface):
                    ipa_syllables = [tailo_syllable_to_ipa(s) for s in syllables]
                    if all(ipa_syllables):
                        for ch, ipa in zip(surface, ipa_syllables):
                            result.ipa_overrides[ch] = ipa
                        entry.applied = True
                    else:
                        entry.reason = (entry.reason + "；" if entry.reason else "") + \
                            "台羅讀音轉IPA失敗(可能含此轉換器不支援的音節)，未套用"
                else:
                    entry.reason = (entry.reason + "；" if entry.reason else "") + \
                        f"漢字數({len(surface)})跟讀音音節數({len(syllables)})對不起來，未套用"
                result.entries.append(entry)
                i += length
                matched = True
                break
            if not matched:
                i += 1

        return result


_default_resolver: ChhoeTaigiPronunciationResolver | None = None


def get_default_resolver() -> ChhoeTaigiPronunciationResolver:
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = ChhoeTaigiPronunciationResolver()
    return _default_resolver


def resolve_overrides_for_text(hanji_text: str) -> dict[str, str]:
    """給`phoneme_normalize.patch_neurlang_phonemizer()`的`overrides_resolver`
    參數直接用：輸入台語漢字，回傳{字元: IPA}override表。"""
    return get_default_resolver().resolve_sentence(hanji_text).ipa_overrides
