"""
數字→台羅讀音產生器: 病房號/床號/電話號碼用「逐位數字讀」, 劑量/數量用
「完整數值讀」——這是中文/台語共通的慣例, 兩種讀法規則不一樣, 不能共用
同一套邏輯 (見下方兩個函式的docstring)。

## 這個模組解決的問題

`protected_tokens.py` 新增的ROOM/DOSE/TIME類別目前偵測得到, 但沒有讀音
(mask()裡這三類的正則比對不查詞庫, span.tailo固定是None)——因為數字理論上
是有限規則就能產生讀音的, 不需要像藥名/職稱那樣逐詞人工校正, 這個模組
就是補上這個「規則產生讀音」的部分。

## 可信度: 只到「數字結構」層級, 不到「單位詞」層級

逐位數字讀音(0-9)跟十/百/千/萬這些量級詞, 是台羅羅馬字教材裡有明確標準
答案的基礎詞彙, 不是從語料庫猜或自己拼湊的——這裡的風險相對低。

**但這裡刻意不處理「單位」的讀音** (毫克/顆/床/病房/點/分...等), 原因是:
  1. 這些是複合詞, 文白讀選字、有沒有變調, 需要看實際語料或母語者確認,
     不是查表就能保證對, 跟118字pronunciation_overrides.py的态度一致——
     沒有實測依據不亂猜。
  2. cardinal_tailo()/digit_by_digit_tailo()只回傳「數字部分」的台羅,
     呼叫端(例如以後要幫DOSE類別產生完整讀音)需要自己另外接上單位詞的
     台羅讀音, 這個模組不假裝知道「120毫克」的「毫克」怎麼念。

**送進正式pipeline前, 仍需台語母語者確認這裡的數字讀音在實際語境下
念起來自然**——這是規則產生的結果, 不是語料驗證過的結果, 跟romanize.py
的`apply_tone_sandhi`預設關閉是同樣的保守立場。
"""

from __future__ import annotations

# 文讀數字(0-9), 逐位數字讀(病房號/床號/電話號碼/身分證字號等)固定用這組,
# 不用白讀——這是台羅教材的標準逐位讀法, 跟中文電話號碼逐位念「洞么二三」
# (而非「一千二百三十四」)是同樣的語用慣例。
TAILO_DIGIT_LITERARY: dict[str, str] = {
    "0": "khòng",
    "1": "it",
    "2": "jī",
    "3": "sam",
    "4": "sù",
    "5": "ngóo",
    "6": "lio̍k",
    "7": "tshit",
    "8": "pat",
    "9": "kiú",
}

# 量級詞(十/百/千/萬), 用於完整數值讀法(cardinal_tailo)的位值組字
TAILO_UNIT_MULTIPLIER: dict[int, str] = {
    10: "cha̍p",
    100: "pah",
    1000: "tshing",
    10000: "bān",
}


def digit_by_digit_tailo(digits: str) -> str | None:
    """逐位數字讀, 病房號/床號/電話號碼/身分證字號這類「不是數量、是編號」
    的數字使用這個函式, 不要用cardinal_tailo()——編號不能用「完整數值」
    讀法 (例如"603號病房"要念成"六-零-三", 不是"六百零三")。

    輸入只接受純數字字元(0-9)組成的字串, 前面若有英文字母前綴
    (例如protected_tokens.py的ROOM正則允許"A3"這種格式), 呼叫端需自行
    先切掉字母部分再傳進來——這個函式不處理字母, 字母本身怎麼讀
    (是逐字母拼讀還是當作代號) 是另一個層次的問題, 不在這裡決定。

    回傳None表示輸入不是純數字字串(例如空字串或含非數字字元)。
    """
    if not digits or not digits.isdigit():
        return None
    return "-".join(TAILO_DIGIT_LITERARY[d] for d in digits)


def cardinal_tailo(n: int) -> str | None:
    """完整數值讀法, 劑量/數量這類「讀出實際數值大小」的數字使用這個函式
    (例如"120毫克"的"120"要念成"一百二十", 不是逐位讀"一-二-零")。

    只支援 0 <= n <= 99999(萬位以內), 超出範圍或負數回傳None——目前醫療
    劑量/數量情境用不到更大的數字, 沒有實際需求就不猜更大位數(十萬以上,
    需要不只一位的萬位數, 構詞規則更複雜) 的台語讀法規則對不對。

    位值構詞規則跟中文數字系統結構相同(而且台語本身確實也是這樣構詞,
    不是套用中文規則硬轉), 兩條規則都要處理:
      1. "十"開頭的十位數(10-19)省略前面的"一" (念"cha̍p-jī"不是
         "it-cha̍p-jī", 對應中文「十二」不是「一十二」)。
      2. 數字中間(不是最前面)出現位值被跳過(例如105的十位是0、10023的
         千位跟百位都是0), 要補讀一個"khòng"(零)占位, 但連續多個跳過的
         位值只補一次, 不重複("10023"是"一萬khòng二十三", 不是
         "一萬khòngkhòng二十三")；數字最後面(尾端)被跳過的位值則不用補,
         直接省略 (例如100不用念成"一百khòng")。
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 0 or n > 99_999:
        return None
    if n == 0:
        return TAILO_DIGIT_LITERARY["0"]

    # 依序處理萬/千/百/十/個五個位值, 每個位值都剛好是0-9的單一數字
    positions = [
        (n // 10_000 % 10, 10_000),
        (n // 1_000 % 10, 1_000),
        (n // 100 % 10, 100),
        (n // 10 % 10, 10),
        (n % 10, None),  # 個位數: 沒有量級詞
    ]

    parts: list[str] = []
    started = False  # 是否已經吐出過至少一個token(用來分辨「前導零」vs「中間零」)
    pending_zero = False  # 中間有位值被跳過, 還沒補讀"khòng"
    for digit, magnitude in positions:
        if digit == 0:
            if started:
                pending_zero = True  # 前導零直接跳過不處理, 中間零才要記
            continue

        if pending_zero:
            parts.append(TAILO_DIGIT_LITERARY["0"])
            pending_zero = False

        if magnitude == 10 and digit == 1 and not started:
            parts.append(TAILO_UNIT_MULTIPLIER[10])  # 10-19省略"一"
        elif magnitude is None:
            parts.append(TAILO_DIGIT_LITERARY[str(digit)])  # 個位數不帶量級詞
        else:
            parts.append(TAILO_DIGIT_LITERARY[str(digit)])
            parts.append(TAILO_UNIT_MULTIPLIER[magnitude])
        started = True

    return "-".join(parts)
