"""
白話字(POJ)→台羅拼字正規化: 把ChhoeTaigi詞庫(見taihoa_dict_loader.py)裡的
POJ拼字轉成台羅標準拼字, 讓詞庫產生的讀音可以跟這個專案既有的
tailo_ipa_converter.py/pronunciation_overrides.py共用同一套拼字慣例。

## 為什麼選POJ欄位, 不選Kip欄位

ChhoeTaigi CSV同時有PojInput跟KipInput兩個羅馬字欄位。Poj(白話字)欄位
語意明確——就是白話字, 跟台羅的對應規則是教育部公告過的固定字母代換
(見下面三條規則), 是有明確依據的, 不是用猜的。Kip欄位目前不確定對應
哪一套系統: 樣本資料顯示它跟Poj欄位有時完全相同、有時卻有實質差異(例如
"à-lêng" vs "à-lîng"母音不同), 不是單純的POJ別名, 也不像單純的教育部台羅
(若是台羅, 應該系統性套用下面三條代換規則, 但樣本裡"o"沒有變成"oo"、
子音也沒有ch→ts的變化, 顯示Kip很可能根本是另一套系統, 不是台羅)。沒有
查證清楚前, 不冒然把Kip當台羅用, 這跟pronunciation_overrides.py「沒有
語料佐證不亂猜發音」是同一個原則, 見data/licenses/chhoetaigi_taihoa_dict.json
的known_limitation_unverified。

## 三條代換規則(教育部公告, 非猜測)

  1. 音節開頭的 ch / chh -> ts / tsh (是的, 這條不需要猜: 白話字跟台羅
     在這個位置的差異只有字母, 發音完全相同, 這也是為什麼
     tailo_ipa_converter.py的_INITIAL_MAP本來就同時接受ch/chh跟ts/tsh
     兩種拼法當輸入)
  2. o͘ (o加右上方一點, combining dot above right, U+0358) -> oo
  3. ⁿ (鼻化符號, modifier letter small n, U+207F) -> nn

**這裡的規則只處理拼字轉換, 不驗證轉換後的發音正不正確**——這是機械式的
字母代換, 跟118字pronunciation_overrides.py那種需要語料驗證的「發音選字」
是不同層次的問題, 風險相對低, 但仍建議串接進正式pipeline前用台語母語者
再抽樣確認幾個轉換結果聽起來對不對。
"""

from __future__ import annotations

_COMBINING_DOT_ABOVE_RIGHT = "͘"  # o͘ 的組合符號部分
_NASALIZATION_MARK = "ⁿ"  # ⁿ


def poj_syllable_to_tailo(poj_syllable: str) -> str:
    """轉換單一POJ音節(不含連字號)成台羅拼字。"""
    result = poj_syllable
    if result.startswith("chh"):
        result = "tsh" + result[3:]
    elif result.startswith("ch"):
        result = "ts" + result[2:]
    result = result.replace("o" + _COMBINING_DOT_ABOVE_RIGHT, "oo")
    result = result.replace(_NASALIZATION_MARK, "nn")
    return result


def poj_word_to_tailo(poj_word: str) -> str:
    """轉換整個詞(可能多音節, 用連字號分隔, 例如ChhoeTaigi CSV的PojInput
    格式)成台羅拼字, 逐音節套用poj_syllable_to_tailo(), 保留原本的連字號
    分隔方式。"""
    return "-".join(poj_syllable_to_tailo(syl) for syl in poj_word.split("-"))
