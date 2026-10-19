"""測試numeric_reading.py的逐位數字讀(digit_by_digit_tailo)跟完整數值讀
(cardinal_tailo)——兩種讀法規則不同, 用一組容易搞混的病房號/劑量案例
分開驗證, 特別針對「零」的補讀規則(中間補、尾端不補、只補一次)寫了
專門的測試, 因為這是最容易寫錯的部分(見模組docstring的說明)。"""

from __future__ import annotations

import pytest

from tw_hokkien_tts_pipeline.numeric_reading import cardinal_tailo, digit_by_digit_tailo


class TestDigitByDigitTailo:
    def test_single_digits(self):
        assert digit_by_digit_tailo("0") == "khòng"
        assert digit_by_digit_tailo("9") == "kiú"

    def test_room_number_style_multi_digit(self):
        # "603" 逐位讀, 不是六百零三
        assert digit_by_digit_tailo("603") == "lio̍k-khòng-sam"

    def test_leading_zero_preserved(self):
        # 逐位讀不會像cardinal那樣省略前導零(例如電話號碼"0912"要念四位)
        assert digit_by_digit_tailo("0912") == "khòng-kiú-it-jī"

    def test_empty_and_non_digit_input_returns_none(self):
        assert digit_by_digit_tailo("") is None
        assert digit_by_digit_tailo("12a") is None
        assert digit_by_digit_tailo("A3") is None  # 字母前綴要呼叫端先切掉


class TestCardinalTailo:
    def test_zero(self):
        assert cardinal_tailo(0) == "khòng"

    def test_single_digit(self):
        assert cardinal_tailo(5) == "ngóo"

    @pytest.mark.parametrize(
        "n, expected",
        [
            (10, "cha̍p"),
            (12, "cha̍p-jī"),
            (19, "cha̍p-kiú"),
            (20, "jī-cha̍p"),
            (21, "jī-cha̍p-it"),
        ],
    )
    def test_teens_and_tens_omit_leading_it_only_in_10_to_19(self, n, expected):
        assert cardinal_tailo(n) == expected

    def test_hundred_keeps_leading_it(self):
        # 100是"一百"(it-pah), 跟"十"不同, 不能省略"it"
        assert cardinal_tailo(100) == "it-pah"

    def test_hundred_ten_repeats_it_at_tens_position(self):
        # 110是"一百一十", 十位的"一"不能因為跟百位重複就被省略
        assert cardinal_tailo(110) == "it-pah-it-cha̍p"

    def test_middle_zero_gets_single_khong(self):
        # 105 = 一百零五: 十位被跳過, 補一個"khòng"
        assert cardinal_tailo(105) == "it-pah-khòng-ngóo"

    def test_trailing_zero_is_not_verbalized(self):
        # 120 = 一百二十: 個位是0, 但那是尾端, 不需要補"khòng"
        assert cardinal_tailo(120) == "it-pah-jī-cha̍p"
        assert cardinal_tailo(200) == "jī-pah"

    def test_multiple_skipped_positions_get_only_one_khong(self):
        # 10023 = 一萬零二十三: 千位跟百位都跳過, 只補一次"khòng", 不是兩次
        assert cardinal_tailo(10023) == "it-bān-khòng-jī-cha̍p-sam"

    def test_ten_thousand_exact(self):
        assert cardinal_tailo(10_000) == "it-bān"

    @pytest.mark.parametrize("bad", [-1, 100_000, 3.5, True, "12"])
    def test_out_of_range_or_wrong_type_returns_none(self, bad):
        assert cardinal_tailo(bad) is None

    def test_typical_dosage_values(self):
        # 常見劑量數字, 順便驗證跟digit_by_digit_tailo("120")的差異
        # (劑量要念完整數值, 不是逐位)
        assert cardinal_tailo(120) != digit_by_digit_tailo("120")
        assert cardinal_tailo(500) == "ngóo-pah"
