"""
台羅(數字調號)→白話字POJ(重音符調號)拼字轉換, 給需要吃POJ重音符文字的TTS
backend用(例如facebook/mms-tts-nan, 見tts.py新增的MmsTtsNanBackend)。

跟poj_to_tailo.py方向相反, 但不是單純逆運算——poj_to_tailo.py只處理三條
拼字代換規則(ch/chh->ts/tsh, o͘->oo, ⁿ->nn), 完全沒有處理調號本身
(ChhoeTaigi詞庫的PojInput欄位本來就是用數字調號, 不是傳統白話字重音符)。
這個模組額外多做「數字調號->重音符, 且標在正確的母音上」這一步, 這是
poj_to_tailo.py沒有的、真正新的轉換邏輯。

## 調號數字 -> 重音符對照(教育部台羅拼音手冊公告的白話字對照, 非猜測)

  1: 不標調(平調)
  2: 銳音符 ́ (combining acute accent, U+0301)
  3: 重音符 ̀ (combining grave accent, U+0300)
  4: 不標調(入聲, 靠音節本身以-p/-t/-k/-h結尾辨識, 跟調號1不衝突)
  5: 揚抑符 ̂ (combining circumflex accent, U+0302)
  7: 長音符 ̄ (combining macron, U+0304)
  8: 直線符 ̍ (combining vertical line above, U+030D)
  (跟本專案慣例一致, 沒有調號6)

## 標調母音的選字規則(標準白話字/台羅正字法規則, 非猜測)

有明確優先順序(依序檢查, 符合哪一條就用哪一條, 不繼續往下找):
  1. 有 a -> 標在a上
  2. 沒a, 有e -> 標在e上
  3. 沒a/e, 有oo(雙o) -> 標在第一個o上
  4. 沒a/e, 有單一個o -> 標在o上
  5. 沒a/e/o, 有u(不論跟i的相對順序是iu還是ui, u都優先於i) -> 標在u上
  6. 沒a/e/o/u, 有i -> 標在i上
  7. 沒任何母音, 音節核心是鼻化輔音m -> 標在m上(例如ḿ, m̀)
  8. 沒任何母音, 音節核心是鼻化輔音ng -> 標在ng的n上(例如tńg、nn̄g)

規則1-6、8已用已知真實詞彙交叉驗證過(tńg「轉」、nn̄g「兩」、kiú「九」、
chúi/tsuí「水」——iu跟ui兩種相鄰順序都是標在u上, 不是看字母先後),
規則7(單獨m)目前專案24筆ambiguity benchmark沒有實例, 未實際驗證過,
使用前建議先用母語者確認。

## 初聲 ts/tsh -> ch/chh(推測, 非確認)

傳統白話字文獻/聖經翻譯多半用ch/chh拼法, 不是2006年後才標準化的台羅ts/tsh
拼法。facebook/mms-tts-nan的tokenizer字彙表裡有獨立的字母'c'(只有在ch/chh
組合才用得到c), 間接暗示訓練語料是ch拼法——但這只是根據字彙表結構的推論,
沒有實際查證這個模型的訓練語料, 也還沒實際合成測試過ch拼法是否真的比ts
拼法念得更準。convert_initial參數預設True(套用這個轉換), 需要的話可以關掉。

## 鼻化符號ⁿ的已知限制

這個模組仍然會把nn轉成正確的ⁿ(U+207F)重音符, 拼字上是對的。但已經實測
確認facebook/mms-tts-nan的tokenizer字彙表完全沒有這個字元, 遇到ⁿ會被
tokenizer的normalize步驟靜默刪除(不會產生<unk>, 直接消失), 不是這個模組
能解決的問題——這是那個TTS backend本身的表示能力上限, 見
tw_hokkien_tts_pipeline/README.md或相關報告的說明。
"""

from __future__ import annotations

import unicodedata

_TONE_MARKS = {
    "2": "́",  # combining acute accent
    "3": "̀",  # combining grave accent
    "5": "̂",  # combining circumflex accent
    "7": "̄",  # combining macron
    "8": "̍",  # combining vertical line above
}

_NASALIZATION_MARK = "ⁿ"
_COMBINING_DOT_ABOVE_RIGHT = "͘"


def _find_nucleus_index(base: str) -> int:
    """回傳要插入調號重音符的位置(插在這個index的字元之後)。"""
    if "a" in base:
        return base.index("a")
    if "e" in base:
        return base.index("e")
    if "oo" in base:
        return base.index("oo")
    if "o" in base:
        return base.index("o")
    if "u" in base:
        return base.index("u")
    if "i" in base:
        return base.index("i")
    if "m" in base:
        return base.index("m")
    if "ng" in base:
        return base.index("ng")
    raise ValueError(f"找不到可標調的母音/鼻化輔音核心: {base!r}")


def tailo_syllable_to_poj(syllable: str, convert_initial: bool = True) -> str:
    """轉換單一台羅音節(含數字調號, 不含連字號)成POJ重音符拼字。

    **必須先在原始(未做nn->ⁿ代換)的字母序列上找核心, 再做nn/oo代換**——
    先代換的話, 像"nng"(轉/兩的鼻化輔音核心, 前面n是聲母、"ng"才是核心)
    這種情況, "nn"會被誤判成「元音+鼻化」而提早被吃掉, 導致找不到"ng"這個
    真正的核心(這是實作時發現的bug, 已修正並補了對應的regression test:
    見tests/test_tailo_to_poj.py::TestKnownRealWords::test_nng7)。"""
    if not syllable or not syllable[-1].isdigit():
        raise ValueError(f"台羅音節必須以調號數字結尾, 收到: {syllable!r}")

    tone_digit = syllable[-1]
    raw_base = syllable[:-1]

    idx = _find_nucleus_index(raw_base)
    is_oo = raw_base[idx : idx + 2] == "oo"
    insert_at = idx + 1

    prefix = raw_base[:insert_at]
    suffix = raw_base[insert_at:]

    if is_oo:
        # suffix開頭是oo這對裡的第二個o, 要換成combining dot above right
        suffix = _COMBINING_DOT_ABOVE_RIGHT + suffix[1:]

    mark = _TONE_MARKS.get(tone_digit) or ""

    # nn(鼻化)只會接在標調母音/鼻化輔音核心之後, 依定義不會出現在prefix裡
    # (prefix在核心那個字母就結束了), 所以只需要處理suffix——這樣nng這種
    # 核心本身含"nn"的情況(核心的n已經算進prefix)才不會被誤代換
    result = prefix + mark + suffix.replace("nn", _NASALIZATION_MARK)

    if convert_initial:
        if result.startswith("tsh"):
            result = "chh" + result[3:]
        elif result.startswith("ts"):
            result = "ch" + result[2:]

    return unicodedata.normalize("NFC", result)


def tailo_word_to_poj(word: str, convert_initial: bool = True) -> str:
    """轉換整個詞(可能多音節, 用連字號分隔)成POJ重音符拼字, 保留連字號。"""
    return "-".join(
        tailo_syllable_to_poj(syl, convert_initial=convert_initial)
        for syl in word.split("-")
    )
