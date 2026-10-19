"""把`romanize.py`裡已經寫好、測試過的連讀變調規則(`_SANDHI_CYCLE`)，
套用到pygoruut phonemizer的IPA輸出上。

## 為什麼需要這個模組

`romanize.py`的`apply_tone_sandhi_numbered()`操作的是「數字調」台羅
音節(例如tai5)，用在`pipeline.py`的`romanize()`產生`tailo_text`。但
`NeurlangTTSBackend`(見`tts.py`)固定只用`tts_input.hanji_text`，完全
不經過`romanize()`這條路——這代表就算`romanize.py`的變調規則寫得再對，
正式合成路徑也永遠用不到，這正是`reports/moe_corpus_taigi_analysis.md`
「發現二」量測到「pygoruut phonemizer完全沒有套用連讀變調」的根本原因。

這個模組把同一套`_SANDHI_CYCLE`規則表(直接從`romanize.py` import，
不重複定義，避免兩份規則表以後改一邊忘記改另一邊)，套用在IPA音節的
聲調符號(Chao tone letters)上，讓neurlang backend實際會用到的路徑
也能套用變調。

## 詞組邊界怎麼判斷

變調規則是「詞組最後一個字維持本調，其他都變調」，一整句話通常不只
一個詞組——遇到標點(逗號/句號等)照理說就是一個詞組結束。pygoruut原始
IPA輸出裡，標點符號會以字面字元的形式留在字串中(還沒被
`normalize_phonemes()`/tokenizer丟棄)，這裡就拿這些字面標點字元切
詞組邊界，每個詞組各自套用「最後一個音節不變調」的規則，而不是整句
只有最後一個音節不變調(那樣句子中間的逗號前面也會被錯誤變調)。

**實測結論(2026-08-06)：套用後使用者回報比沒套用更差，沒有正式啟用。**

寫完之後產生了3組A/B對照音檔(A=現有pipeline含發音修正但不含變調，
B=A再加這個模組的變調)，讓使用者實際比較，回報「A比較好」——套用
變調反而讓合成結果變差，不是變自然。這跟`phoneme_normalize.py`
docstring記錄過的「全形標點轉半形」教訓是同一種模式：**規則本身
語言學上正確，不代表套用在這個模型上聽起來會更好**——這個模型(VITS
+ vocoder)訓練時的語料(SuiSiann)本身沒有被驗證過是不是有一致地
呈現連讀變調，如果訓練資料本身變調不穩定或稀少，模型的聲學(acoustic)
層可能沒有正確學會「變調後的調型」該對應什麼實際發音，這時候把
「理論正確」的變調調型硬塞進去，模型可能生成不自然的結果，比不管它、
統一用本調(至少模型本身在推論時可能已經某種程度上適應了本調的輸出
模式)更差。

**這個模組保留在repo裡，但不接進`phoneme_normalize.py`的
`patch_neurlang_phonemizer()`(不是預設啟用的pipeline的一部分)**——
程式碼本身沒有bug(單元測試都過)，只是實測後確認對這個特定模型不該
用。如果之後模型有重新訓練、或換了對變調更敏感的backend，這裡的
邏輯可以重新拿出來測試，不用重寫。
"""

from __future__ import annotations

import re

from .romanize import _SANDHI_CYCLE

_SYLLABLE_RE = re.compile(r"[^˥˦˧˨˩，。？！、；：「」『』（）—－,\.\?!;:\(\)　\s]+[˥˦˧˨˩]+")

_TONE_LETTER_TO_NUM = {
    "˥˥": 1,
    "˥˧": 2,
    "˨˩": 3,
    "˨": 4,
    "˨˦": 5,
    "˧˧": 7,
    "˦": 8,
}
_TONE_NUM_TO_LETTER = {v: k for k, v in _TONE_LETTER_TO_NUM.items()}

_TONE_GROUP_BOUNDARY_RE = re.compile(r"[，。？！、；：「」『』（）—－,\.\?!;:\(\)　]")


def _split_into_tone_groups(ipa: str) -> list[tuple[int, int]]:
    """回傳每個詞組在原字串裡的(start, end) span，用標點字元切。"""
    groups = []
    start = 0
    for m in _TONE_GROUP_BOUNDARY_RE.finditer(ipa):
        if m.start() > start:
            groups.append((start, m.start()))
        start = m.end()
    if start < len(ipa):
        groups.append((start, len(ipa)))
    return groups


def apply_tone_sandhi_to_ipa(ipa_output: str) -> str:
    """對pygoruut的IPA輸出套用連讀變調(每個標點分隔的詞組內，除了最後
    一個音節，其他都按`romanize.py`的`_SANDHI_CYCLE`變調)。

    不認得的聲調符號組合(不在`_TONE_LETTER_TO_NUM`裡)原樣保留，不猜測。
    """
    pieces = []
    cursor = 0
    for group_start, group_end in _split_into_tone_groups(ipa_output):
        pieces.append(ipa_output[cursor:group_start])

        group_text = ipa_output[group_start:group_end]
        syll_spans = [m.span() for m in _SYLLABLE_RE.finditer(group_text)]

        group_pieces = []
        group_cursor = 0
        for i, (s, e) in enumerate(syll_spans):
            group_pieces.append(group_text[group_cursor:s])
            syll = group_text[s:e]
            is_last = i == len(syll_spans) - 1
            if not is_last:
                syll = _sandhi_one_syllable(syll)
            group_pieces.append(syll)
            group_cursor = e
        group_pieces.append(group_text[group_cursor:])

        pieces.append("".join(group_pieces))
        cursor = group_end
    pieces.append(ipa_output[cursor:])
    return "".join(pieces)


def _sandhi_one_syllable(syll: str) -> str:
    m = re.search(r"([˥˦˧˨˩]+)$", syll)
    if not m:
        return syll
    tone_letters = m.group(1)
    tone_num = _TONE_LETTER_TO_NUM.get(tone_letters)
    if tone_num is None:
        return syll
    new_tone_num = _SANDHI_CYCLE.get(tone_num, tone_num)
    new_tone_letters = _TONE_NUM_TO_LETTER.get(new_tone_num, tone_letters)
    return syll[: m.start()] + new_tone_letters
