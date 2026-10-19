"""驗證`pronunciation_reference.py`合併表的內部一致性，見該模組docstring
完整背景(118字表+MAS對齊異常330候選字分類的合併結果)。
"""

from __future__ import annotations

from tw_hokkien_tts_pipeline.pronunciation_reference import PRONUNCIATION_CANDIDATES

_VALID_CATEGORIES = {
    "OVERRIDE_CANDIDATE",
    "ALREADY_CORRECT",
    "AMBIGUOUS",
    "UNSUPPORTED_SYLLABLE_FORM",
    "NOT_FOUND",
}


def test_has_exactly_330_entries() -> None:
    assert len(PRONUNCIATION_CANDIDATES) == 330


def test_every_entry_has_a_known_category() -> None:
    for candidate in PRONUNCIATION_CANDIDATES.values():
        assert candidate.category in _VALID_CATEGORIES


def test_override_and_already_correct_entries_have_expected_ipa() -> None:
    for candidate in PRONUNCIATION_CANDIDATES.values():
        if candidate.category in ("OVERRIDE_CANDIDATE", "ALREADY_CORRECT"):
            assert candidate.expected_ipa is not None
            assert candidate.dominant_frac is not None
            assert candidate.dominant_frac >= 0.90


def test_ambiguous_entries_have_no_single_dominant_reading() -> None:
    for candidate in PRONUNCIATION_CANDIDATES.values():
        if candidate.category == "AMBIGUOUS":
            assert candidate.dominant_frac is not None
            assert candidate.dominant_frac < 0.90


def test_already_in_118_list_flag_marks_the_58_overlap_characters() -> None:
    # already_in_118_list是「這輪MAS調查開始前，字元是不是已經在118字表
    # 裡」的歷史快照(58個候選字跟118字表重疊，其中24個這輪重新驗證後仍是
    # OVERRIDE_CANDIDATE，其餘34個分類到AMBIGUOUS/ALREADY_CORRECT，見
    # module docstring)，不是CHARACTER_IPA_OVERRIDES現在有沒有這個字——
    # 42個新字合併進去之後，後者對42個新字也會是True，會蓋掉這個有意義
    # 的區分，所以這裡用固定數字驗證，不要動態比對CHARACTER_IPA_OVERRIDES
    flagged = [c for c in PRONUNCIATION_CANDIDATES.values() if c.already_in_118_list]
    assert len(flagged) == 58
    flagged_override = [c for c in flagged if c.category == "OVERRIDE_CANDIDATE"]
    assert len(flagged_override) == 24


def test_key_matches_char_field() -> None:
    for char, candidate in PRONUNCIATION_CANDIDATES.items():
        assert char == candidate.char
