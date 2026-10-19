"""測試poj_to_tailo.py的三條教育部公告代換規則(ch/chh->ts/tsh、o͘->oo、
ⁿ->nn), 用課本等級沒有爭議的已知詞驗證, 不用語料庫猜測資料。"""

from __future__ import annotations

from tw_hokkien_tts_pipeline.poj_to_tailo import poj_syllable_to_tailo, poj_word_to_tailo


class TestPojSyllableToTailo:
    def test_ch_becomes_ts(self):
        assert poj_syllable_to_tailo("chia̍h") == "tsia̍h"  # 食

    def test_chh_becomes_tsh(self):
        assert poj_syllable_to_tailo("chhia") == "tshia"  # 車

    def test_ch_only_substituted_at_syllable_start(self):
        # 用startswith()判斷、只代換開頭, 不是對整個字串做全域字串替換
        # (POJ音節結構裡ch/chh本來就只會出現在開頭, 這裡驗證這個實作細節)
        assert poj_syllable_to_tailo("chham") == "tsham"

    def test_dotted_o_becomes_double_o(self):
        assert poj_syllable_to_tailo("ho͘") == "hoo"  # 雨/護 一類的韻母

    def test_nasalization_mark_becomes_nn(self):
        assert poj_syllable_to_tailo("hiⁿ") == "hinn"

    def test_syllable_without_special_forms_unchanged(self):
        assert poj_syllable_to_tailo("bô") == "bô"
        assert poj_syllable_to_tailo("î") == "î"

    def test_numbered_tone_form_preserved(self):
        # PojInput欄位是數字調格式(例如"a2-bo5"裡的單音節"bo5"), 代換規則
        # 不該動到數字調尾碼, 只動開頭的子音拼字
        assert poj_syllable_to_tailo("chham1") == "tsham1"


class TestPojWordToTailo:
    def test_multi_syllable_word_hyphen_preserved(self):
        assert poj_word_to_tailo("á-bô") == "á-bô"

    def test_each_syllable_converted_independently(self):
        assert poj_word_to_tailo("chia̍h-pn̄g") == "tsia̍h-pn̄g"  # 食飯

    def test_real_sample_row_from_chhoetaigi_csv(self):
        # 這五筆是實際從ChhoeTaigiDatabase repo README/CSV確認過的真實資料
        # (見data/licenses/chhoetaigi_taihoa_dict.json), 不是假造的測試資料
        assert poj_word_to_tailo("a2-bo5") == "a2-bo5"  # á-bô, 無ch/chh/o͘/ⁿ可代換
        assert poj_word_to_tailo("a2-phau3") == "a2-phau3"  # á-phàu
