"""
補充詞庫: 針對ChhoeTaigi「2002+台華線頂對照典」查無讀音(OOV)的高頻語法詞
(的/欲/仔/咧/矣/恁/佇/个/予/毋等), 建立獨立的小型補充表——不修改
ChhoeTaigi原始CSV本身。

## 為什麼獨立成一個檔案, 不是塞進ChhoeTaigi CSV或直接改taihoa_dict_loader.py

OOV(詞庫查無這個詞)跟多音消歧是兩個分開的問題(見taihoa_dict_loader.py
模組docstring), 這裡補的是OOV, 用途、資料來源、審核狀態都跟原始91,339筆
詞庫不一樣, 混在同一個檔案裡會讓「這筆資料到底是ChhoeTaigi原始收錄的,
還是這個專案自己後來補的」變得不清楚, 之後要追溯來源或重新驗證會很麻煩。

## 資料來源分兩種, `verified`欄位誠實區分

跑200句baseline_taigi_llama_han統計出的高頻OOV詞裡, 有6個字剛好已經在
pronunciation_overrides.py裡有語料庫驗證過的讀音(的/咧/毋/較/袂/敲——
那個表是2026-08-06/07針對TAT-MOE語料庫大規模比對pygoruut輸出建立的),
直接沿用、標記`verified=true`、`source`指向那個檔案。

其餘12個字(欲/仔/矣/恁/佇/个/予/𤆬/喙/跤/蹛/啉)沒有語料佐證, 這裡填的是
依教育部台灣閩南語常用詞辭典等公開標準辭典的常見讀音"推測值", 明確標記
`verified=false`——這跟這個專案一貫的原則一致(見DRUG_LEXICON/
MEDICAL_TITLE_LEXICON的None值慣例): 沒有語料或母語者驗證前, 不能假裝
這個讀音是確定的, 但填一個有根據的候選值總比留空好, 讓segment.py可以
先用、同時明確標記信心較低(見`SupplementalEntry.verified`跟
`load_supplemental_lexicon()`回傳的low_confidence_surfaces)。

## 已知超出範圍的OOV: 數字跟標點

統計高頻OOV時還看到「三」「十」這類單獨的數字漢字, 跟這份補充詞庫的
性質不一樣——這些不該當成固定讀音的詞條收錄, 應該走
`numeric_reading.py`的組合規則(cardinal_tailo/digit_by_digit_tailo)
動態產生讀音, 這裡故意不收錄。標點符號(，。？等)也不是詞, 不在這份
補充詞庫的處理範圍內。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SUPPLEMENTAL_CSV_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "lexicons" / "supplemental_particles.csv"
)


@dataclass
class SupplementalEntry:
    surface: str
    reading: str
    source: str
    reason: str
    verified: bool


def load_supplemental_entries(
    csv_path: Path | str = DEFAULT_SUPPLEMENTAL_CSV_PATH,
) -> list[SupplementalEntry]:
    csv_path = Path(csv_path)
    entries: list[SupplementalEntry] = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            entries.append(
                SupplementalEntry(
                    surface=row["surface"],
                    reading=row["reading"],
                    source=row["source"],
                    reason=row["reason"],
                    verified=row["verified"].strip().lower() == "true",
                )
            )
    return entries


def load_supplemental_lexicon(
    csv_path: Path | str = DEFAULT_SUPPLEMENTAL_CSV_PATH,
) -> tuple[dict[str, str], set[str]]:
    """回傳({surface: reading}, low_confidence_surfaces)——low_confidence_surfaces
    是`verified=false`那些, 呼叫端(見segment.py)應該用這個集合把對應詞的
    分辨信心分數調低, 不能跟已驗證的詞條一視同仁。"""
    entries = load_supplemental_entries(csv_path)
    lexicon = {entry.surface: entry.reading for entry in entries}
    low_confidence_surfaces = {entry.surface for entry in entries if not entry.verified}
    return lexicon, low_confidence_surfaces
