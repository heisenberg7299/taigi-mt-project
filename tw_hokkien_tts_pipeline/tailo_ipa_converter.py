"""台羅數字調(Tai-lo numbered-tone)音節 -> pygoruut風格IPA的規則轉換器。

## 背景

這個轉換邏輯第一次出現是在生成`pronunciation_overrides.py`的118字表時
(2026-08-06)，當時是「開發時的一次性腳本，沒有留在repo裡」，只用15組
人工驗證過的真實pygoruut輸出配對測試過就丟棄。後續在語料庫發音錯誤率
分析、MAS對齊異常跟118字表的相關性分析，都各自需要重新比對台羅
ground truth跟pygoruut輸出，重複寫過三次類似邏輯——這代表它是會反覆
用到的工具，值得正式留在repo裡。

## 規則怎麼來的

不是憑空推導IPA規則，是直接從`pronunciation_overrides.py`
`CHARACTER_IPA_OVERRIDES`裡118組「人工/程式化驗證過的真實pygoruut
輸出」反推規則，每條規則都用這127組(118+後續確認的9組)已知正確配對
驗證過(見`tests/test_tailo_ipa_converter.py`，127組全部通過)才視為
可信。這跟第一版一次性腳本的驗證精神一致，只是這次規則庫更完整、有
自動化測試守著，不會又變成沒人記得驗證過什麼的一次性腳本。

## 已知不支援的範圍(刻意回傳None，不猜)

**純鼻音自成音節**(hng/tng/nng/sng/ng等，整個音節沒有元音，鼻音本身
就是韻核)：跟`pronunciation_overrides.py`docstring記錄的踩雷經驗一致
——pygoruut對這類音節有時用特殊的鼻化聲調符號(ń/ǹ)標記，不是這裡假設
的標準Chao tone letter系統，貿然轉換可能產生模型詞彙表沒有的符號組合。
`m`(毋)是唯一驗證過的例外，直接特判處理，其餘一律回傳`None`。

**輸入格式必須是純小寫字母+單一數字調**(例如`khuann3`)，不支援連字號
組成的多音節詞組(那是`romanize.py`的`_SANDHI_CYCLE`等模組處理的範圍，
不是這裡的責任)——呼叫端要先自己切好單一音節再傳進來。

回傳`None`代表這個音節形式目前規則庫沒把握，保守不猜，比照
`pronunciation_overrides.py`「對不起來寧可不修」的一貫原則。
"""

from __future__ import annotations

import re

TONE_MAP: dict[str, str] = {
    "1": "˥˥",
    "2": "˥˧",
    "3": "˨˩",
    "4": "˨",  # 入聲(promised本調)，音節必須以p/t/k/h收尾
    "5": "˨˦",
    "7": "˧˧",
    "8": "˦",  # 入聲，音節必須以p/t/k/h收尾
}
_CHECKED_TONES = {"4", "8"}

# 長的字串要排在前面，避免「th」被誤判成「t」+剩下的「h」
_INITIAL_MAP: list[tuple[str, str]] = [
    ("tsh", "tsʰ"),
    ("chh", "tsʰ"),
    ("ts", "ts"),
    ("ch", "ts"),
    ("kh", "kʰ"),
    ("ph", "pʰ"),
    ("th", "tʰ"),
    ("ng", "ŋ"),
    ("b", "b"),
    ("g", "ɡ"),
    ("j", "dz"),
    ("h", "h"),
    ("k", "k"),
    ("l", "l"),
    ("m", "m"),
    ("n", "n"),
    ("p", "p"),
    ("s", "s"),
    ("t", "t"),
]

# 元音拼寫跟IPA符號大多數是identity mapping，這裡只列出「拼寫≠IPA符號」
# 的特例(目前只有「oo」這個雙字母合成雙元音代表/ɔ/，跟單一「o」/o/不同)
_VOWEL_SPECIAL_MAP: dict[str, str] = {
    "oo": "ɔ",
}

_SYLLABLE_RE = re.compile(r"^[a-z]+\d$")
_VOWEL_LETTER_RE = re.compile(r"[aeiou]")


def _strip_initial(body: str) -> tuple[str, str]:
    for prefix, ipa in _INITIAL_MAP:
        if body.startswith(prefix):
            return ipa, body[len(prefix) :]
    return "", body


# pygoruut輸出鼻化母音時用的是「預組合」(precomposed)Unicode字元(例如
# U+00E3 ã)，不是「基底字母+組合波浪符」(combining tilde, U+0303)的分解
# 形式——兩者視覺上一樣，但codepoint不同，字元對字元比對會不相等，這裡
# 一定要用precomposed，不能自己組合
_PRECOMPOSED_NASAL_VOWEL: dict[str, str] = {
    "a": "ã",
    "e": "ẽ",
    "i": "ĩ",
    "o": "õ",
    "u": "ũ",
}


def _nasalize(vowel_core: str) -> str:
    return "".join(_PRECOMPOSED_NASAL_VOWEL.get(ch, ch + "̃") for ch in vowel_core)


def tailo_syllable_to_ipa(syllable: str) -> str | None:
    """把單一台羅數字調音節(例如`khuann3`)轉成pygoruut風格IPA字串。

    回傳`None`代表規則庫對這個形式沒把握，見module docstring「已知不
    支援的範圍」。
    """
    syllable = syllable.strip()
    if not _SYLLABLE_RE.match(syllable):
        return None

    body, tone = syllable[:-1], syllable[-1]
    if tone not in TONE_MAP:
        return None

    if body == "m":  # 唯一驗證過的純鼻音自成音節例外，見module docstring
        return "m" + TONE_MAP[tone]

    initial, rest = _strip_initial(body)

    if not _VOWEL_LETTER_RE.search(rest):
        return None  # 其餘純鼻音自成音節(hng/tng/nng/sng/ng等)，保守不猜

    nasalize = False
    coda = ""
    if rest.endswith("nn"):
        nasalize = True
        rest = rest[:-2]
    elif rest.endswith("ng"):
        coda = "ŋ"
        rest = rest[:-2]
    elif rest.endswith("n"):
        coda = "n"
        rest = rest[:-1]
    elif rest.endswith("m"):
        coda = "m"
        rest = rest[:-1]
    elif rest and rest[-1] in "ptkh":
        if tone not in _CHECKED_TONES:
            return None  # 有塞音韻尾但不是入聲調，形式不一致，不猜
        last = rest[-1]
        rest = rest[:-1]
        coda = "ʔ" if last == "h" else last

    if tone in _CHECKED_TONES and coda not in ("p", "t", "k", "ʔ"):
        return None  # 入聲調卻沒有對應的塞音韻尾，形式不一致，不猜

    if not rest:
        return None  # 韻核被清空了，代表拼寫形式超出目前規則庫，不猜

    vowel_core = _VOWEL_SPECIAL_MAP.get(rest, rest)
    if nasalize:
        vowel_core = _nasalize(vowel_core)

    return f"{initial}{vowel_core}{coda}{TONE_MAP[tone]}"
