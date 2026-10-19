import unicodedata

import pytest

from tw_hokkien_tts_pipeline.tailo_to_poj import tailo_syllable_to_poj, tailo_word_to_poj

_ACUTE = "́"
_GRAVE = "̀"
_CIRCUMFLEX = "̂"
_MACRON = "̄"
_VBAR = "̍"
_DOT = "͘"
_NASAL = "ⁿ"


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


class TestKnownRealWords:
    """跟真實已知常用詞交叉驗證, 不是憑空編造的測試案例。"""

    def test_tng2_zng_syllabic_nasal(self):
        # 轉(tńg) - 鼻化輔音ng當音節核心, 調號標在ng的n上
        assert tailo_syllable_to_poj("tng2") == _nfc("t" + "n" + _ACUTE + "g")

    def test_nng7_double_n_syllabic_nasal(self):
        # 兩(nn̄g) - 前面的n是聲母, 後面ng是鼻化輔音核心
        assert tailo_syllable_to_poj("nng7") == _nfc("n" + "n" + _MACRON + "g")

    def test_kiu2_iu_diphthong_marks_u(self):
        # 九(kiú) - iu雙元音, u優先於i
        assert tailo_syllable_to_poj("kiu2") == _nfc("ki" + "u" + _ACUTE)

    def test_tsui2_ui_diphthong_also_marks_u(self):
        # 水(tsuí/chúi) - ui雙元音, 一樣是u優先於i(不是看字母先後順序)
        assert tailo_syllable_to_poj("tsui2", convert_initial=False) == _nfc(
            "ts" + "u" + _ACUTE + "i"
        )


class TestVowelPriority:
    def test_a_present_marks_a(self):
        assert tailo_syllable_to_poj("han5", convert_initial=False) == _nfc(
            "h" + "a" + _CIRCUMFLEX + "n"
        )

    def test_no_a_present_marks_e(self):
        assert tailo_syllable_to_poj("he7", convert_initial=False) == _nfc("h" + "e" + _MACRON)

    def test_oo_marks_the_single_collapsed_o_before_the_dot(self):
        assert tailo_syllable_to_poj("noo7", convert_initial=False) == _nfc(
            "n" + "o" + _MACRON + _DOT
        )

    def test_single_o_marks_o(self):
        assert tailo_syllable_to_poj("kong2", convert_initial=False) == _nfc(
            "k" + "o" + _ACUTE + "ng"
        )


class TestNasalizationMarkConversion:
    def test_nn_becomes_nasalization_mark_after_tone(self):
        # 敢(kann2) - nn鼻化, 調號標在a上, ⁿ接在a後面
        assert tailo_syllable_to_poj("kann2", convert_initial=False) == _nfc(
            "k" + "a" + _ACUTE + _NASAL
        )


class TestInitialConsonantConversion:
    def test_ts_becomes_ch_by_default(self):
        assert tailo_syllable_to_poj("tsai5") == _nfc("ch" + "a" + _CIRCUMFLEX + "i")

    def test_tsh_becomes_chh_by_default(self):
        assert tailo_syllable_to_poj("tshui2") == _nfc("chh" + "u" + _ACUTE + "i")

    def test_ts_kept_when_convert_initial_false(self):
        assert tailo_syllable_to_poj("tsai5", convert_initial=False) == _nfc(
            "ts" + "a" + _CIRCUMFLEX + "i"
        )


class TestToneOneAndFourNoDiacritic:
    def test_tone1_no_mark(self):
        assert tailo_syllable_to_poj("ka1", convert_initial=False) == "ka"

    def test_tone4_no_mark(self):
        assert tailo_syllable_to_poj("khah4", convert_initial=False) == "khah"

    def test_tone1_syllabic_ng_nucleus_stays_nng_not_collapsed_to_nasal_mark(self):
        # 核心本身含"nn"(聲母n + 核心ng)時, 沒有調號要標也不該被誤代換成ⁿ
        assert tailo_syllable_to_poj("nng1", convert_initial=False) == "nng"


class TestErrorHandling:
    def test_missing_tone_digit_raises(self):
        with pytest.raises(ValueError):
            tailo_syllable_to_poj("tshui")


class TestWordLevel:
    def test_multi_syllable_word_keeps_hyphens(self):
        result = tailo_word_to_poj("an2-tsoann2")
        assert result.count("-") == 1
        assert len(result.split("-")) == 2
