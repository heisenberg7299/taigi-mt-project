"""驗證`tailo_ipa_converter.tailo_syllable_to_ipa()`對127組已知正確的
台羅數字調->IPA配對(118組來自`pronunciation_overrides.py`的
`CHARACTER_IPA_OVERRIDES`，加上9組後續MAS對齊調查時額外人工核對過的
pygoruut輸出)全部轉換正確，見兩個模組的docstring說明完整背景。
"""

from __future__ import annotations

import pytest

from tw_hokkien_tts_pipeline.pronunciation_overrides import CHARACTER_IPA_OVERRIDES
from tw_hokkien_tts_pipeline.tailo_ipa_converter import tailo_syllable_to_ipa

# 字元 -> (台羅數字調, 對應的正確IPA)，直接從
# CHARACTER_IPA_OVERRIDES的註解跟後續調查抽取，兩邊對不上就是規則錯了
_TAILO_BY_CHAR: dict[str, str] = {
    "毋": "m7",
    "我": "gua2",
    "著": "tioh8",
    "落": "loh8",
    "正": "tsing3",
    "空": "khong3",
    "月": "gueh8",
    "號": "ho7",
    "重": "tiong7",
    "請": "tshiann2",
    "咧": "leh4",
    "世": "si3",
    "復": "hok8",
    "開": "khai1",
    "下": "e7",
    "初": "tshe1",
    "恢": "hue1",
    "育": "iok8",
    "水": "tsui2",
    "看": "khuann3",
    "當": "tang3",
    "俗": "siok8",
    "阮": "gun2",
    "共": "ka7",
    "地": "te7",
    "若": "na2",
    "動": "tang7",
    "面": "bin7",
    "關": "kuan1",
    "後": "au7",
    "定": "tiann7",
    "較": "khah4",
    "煞": "suah4",
    "灣": "uan5",
    "袂": "bue7",
    "讀": "thak8",
    "代": "tai7",
    "碼": "be2",
    "好": "ho2",
    "處": "tshu3",
    "用": "iong7",
    "親": "tshin1",
    "愈": "lu2",
    "為": "ui7",
    "物": "mih8",
    "數": "soo3",
    "像": "tshiunn7",
    "中": "tiong1",
    "接": "tsiap4",
    "陣": "tsun7",
    "學": "hak8",
    "嘛": "ma7",
    "影": "ing2",
    "教": "kau3",
    "照": "tsiau3",
    "倒": "to2",
    "氣": "khi3",
    "遮": "tsia1",
    "然": "lian5",
    "樂": "lok8",
    "山": "suann1",
    "師": "su1",
    "要": "iau3",
    "房": "pang5",
    "暝": "mi5",
    "佮": "kah4",
    "種": "tsiong2",
    "死": "si2",
    "今": "kin1",
    "年": "ni5",
    "工": "kang1",
    "彼": "he1",
    "流": "lau5",
    "知": "tsai1",
    "沖": "tshiang5",
    "先": "sing1",
    "忍": "jim2",
    "騎": "khia5",
    "猛": "me2",
    "內": "lai7",
    "上": "siong7",
    "命": "mia7",
    "幾": "kui2",
    "昏": "hun1",
    "還": "hing5",
    "短": "te2",
    "健": "kiann7",
    "惱": "lo2",
    "衝": "tshiong1",
    "厚": "kau7",
    "陳": "tan5",
    "桃": "tho5",
    "想": "siong2",
    "碌": "lok8",
    "爸": "pah4",
    "合": "hap8",
    "奇": "ki5",
    "寒": "han5",
    "彌": "mi5",
    "陀": "to5",
    "如": "lu5",
    "張": "tiunn1",
    "把": "pa2",
    "原": "uan5",
    "應": "ing3",
    "分": "hun1",
    "醫": "i1",
    "作": "tsoh4",
    "支": "ki1",
    "別": "pat8",
    "加": "ke1",
    "災": "tsai1",
    "目": "bok8",
    "化": "hua3",
    "葉": "hioh8",
    "敢": "kann2",
    "石": "tsioh8",
    "嘓": "kok4",
    "的": "e5",
    # 後續MAS對齊調查(2026-08-07)額外人工核對過的正確pygoruut輸出
    "來": "lai5",
    "欲": "beh4",
    "出": "tshut4",
    "予": "hoo7",
    "閣": "koh4",
    "鼎": "tiann2",
    "淹": "im1",
    "磟": "lak8",
}


@pytest.mark.parametrize("char,tailo", sorted(_TAILO_BY_CHAR.items()))
def test_matches_known_pygoruut_output(char: str, tailo: str) -> None:
    expected_ipa = CHARACTER_IPA_OVERRIDES.get(char)
    if expected_ipa is None:
        expected_ipa = {
            "來": "lai˨˦",
            "欲": "beʔ˨",
            "出": "tsʰut˨",
            "予": "hɔ˧˧",
            "閣": "koʔ˨",
            "鼎": "tĩã˥˧",
            "淹": "im˥˥",
            "磟": "lak˦",
            # 2026-09-10：「共」從CHARACTER_IPA_OVERRIDES移除了(黃金標準
            # 證實是真正的文白異讀字，不該用固定表覆蓋，見
            # pronunciation_overrides.py的移除記錄)，但ka7這個音節本身
            # 轉IPA轉成ka˧˧仍然是驗證過的正確轉換，跟「共」這個字該不該
            # 固定念ka7是兩件事，這裡改成直接寫死預期值，不再依賴
            # CHARACTER_IPA_OVERRIDES裡是否還留著這個字元。
            "共": "ka˧˧",
        }[char]

    assert tailo_syllable_to_ipa(tailo) == expected_ipa


def test_pure_nasal_syllabic_finals_return_none() -> None:
    # 見module docstring：hng/tng/nng/sng/ng這類純鼻音自成音節，pygoruut
    # 有時用ń/ǹ這種跟這裡規則庫不同的鼻化聲調符號標記，保守回傳None
    for syllable in ["hng5", "tng1", "nng7", "sng1", "ng5"]:
        assert tailo_syllable_to_ipa(syllable) is None


def test_malformed_input_returns_none() -> None:
    assert tailo_syllable_to_ipa("") is None
    assert tailo_syllable_to_ipa("khuann") is None  # 沒有聲調數字
    assert tailo_syllable_to_ipa("khuann9") is None  # 不支援的聲調數字
    assert tailo_syllable_to_ipa("tai5-tiong1") is None  # 多音節詞組，不是單一音節
