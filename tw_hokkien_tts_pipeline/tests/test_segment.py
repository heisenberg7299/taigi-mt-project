"""測試segment.py的_greedy_lexicon_segment()共用邏輯、MockSegmentationBackend
沒有因為重構(改用共用函式)而行為跑掉、以及新增的RealSegmentationBackend。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tw_hokkien_tts_pipeline.segment import (
    MockSegmentationBackend,
    RealSegmentationBackend,
    SegmentedWord,
    _greedy_lexicon_segment,
    build_segmentation_backend,
)

_REAL_HEADER = (
    '"DictWordID","PojUnicode","PojUnicodeOthers","PojInput","PojInputOthers",'
    '"HanLoTaibunPoj","KipUnicode","KipUnicodeOthers","KipInput","KipInputOthers",'
    '"HanLoTaibunKip","HoaBun"'
)
_REAL_ROWS = [
    '"1","á-bô","","a2-bo5","","á無","á-bô","","a2-bo5","","á無","不然"',
    '"3","á-î","","a2-i5","","á蛦","á-î","","a2-i5","","á蛦","蟬"',
]


@pytest.fixture
def real_sample_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("\n".join([_REAL_HEADER, *_REAL_ROWS]) + "\n", encoding="utf-8")
    return csv_path


class TestMockSegmentationBackendUnchangedAfterRefactor:
    def test_known_words_segmented_with_tailo(self):
        backend = MockSegmentationBackend()
        result = backend.segment("請記得食。")
        surfaces = [w.surface for w in result.words]
        assert surfaces == ["請", "記得", "食", "。"]
        assert all(w.tailo is not None for w in result.words)

    def test_unknown_char_falls_back_to_single_char_zero_confidence(self):
        backend = MockSegmentationBackend()
        result = backend.segment("未知字")
        assert all(w.confidence == 0.0 and w.tailo is None for w in result.words)
        assert [w.surface for w in result.words] == ["未", "知", "字"]

    def test_placeholder_treated_as_single_word(self):
        backend = MockSegmentationBackend()
        result = backend.segment("請食DRUGA。")
        surfaces = [w.surface for w in result.words]
        assert "DRUGA" in surfaces
        placeholder_word = next(w for w in result.words if w.surface == "DRUGA")
        assert placeholder_word.tailo is None
        assert placeholder_word.confidence == 1.0


class TestRealSegmentationBackend:
    def test_missing_csv_raises_at_construction_not_at_segment_call(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.csv"
        with pytest.raises(FileNotFoundError):
            RealSegmentationBackend(csv_path=missing)

    def test_segments_using_loaded_dictionary(self, real_sample_csv: Path):
        backend = RealSegmentationBackend(csv_path=real_sample_csv)
        result = backend.segment("á無á蛦")
        assert [w.surface for w in result.words] == ["á無", "á蛦"]
        assert result.words[0].tailo == "a2-bo5"
        assert result.words[1].tailo == "a2-i5"

    def test_char_not_in_dictionary_falls_back(self, real_sample_csv: Path):
        backend = RealSegmentationBackend(csv_path=real_sample_csv)
        result = backend.segment("×")
        assert result.words == [SegmentedWord(surface="×", tailo=None, confidence=0.0)]


class TestRealSegmentationBackendStrategy:
    def test_default_strategy_is_first(self, real_sample_csv: Path):
        backend = RealSegmentationBackend(csv_path=real_sample_csv)
        assert backend.strategy == "first"
        assert backend.name == "real_chhoetaigi_first"

    def test_majority_strategy_can_be_selected_and_changes_ambiguous_reading(self, tmp_path: Path):
        rows = [
            '"1","y","","reading_b","","測試詞","y","","reading_b","","測試詞","義1"',
            '"2","x","","reading_a","","測試詞","x","","reading_a","","測試詞","義2"',
            '"3","x","","reading_a","","測試詞","x","","reading_a","","測試詞","義3"',
        ]
        csv_path = tmp_path / "synthetic.csv"
        csv_path.write_text("\n".join([_REAL_HEADER, *rows]) + "\n", encoding="utf-8")

        first_backend = RealSegmentationBackend(csv_path=csv_path, strategy="first")
        majority_backend = RealSegmentationBackend(csv_path=csv_path, strategy="majority")
        assert majority_backend.name == "real_chhoetaigi_majority"

        first_result = first_backend.segment("測試詞")
        majority_result = majority_backend.segment("測試詞")
        assert first_result.words[0].tailo == "reading_b"
        assert majority_result.words[0].tailo == "reading_a"


_SUPPLEMENTAL_CSV = """surface,reading,source,reason,verified
的,e5,pronunciation_overrides.py,語料庫驗證過,true
欲,beh4,公開標準辭典,推測值未驗證,false
"""


@pytest.fixture
def supplemental_csv(tmp_path: Path) -> Path:
    path = tmp_path / "supplemental.csv"
    path.write_text(_SUPPLEMENTAL_CSV, encoding="utf-8")
    return path


class TestGreedyLexiconSegmentLowConfidence:
    def test_low_confidence_surface_gets_half_confidence(self):
        result = _greedy_lexicon_segment("的", {"的": "e5"}, frozenset({"的"}))
        assert result.words[0].confidence == 0.5
        assert result.words[0].tailo == "e5"

    def test_normal_surface_not_in_low_confidence_set_gets_full_confidence(self):
        result = _greedy_lexicon_segment("的", {"的": "e5"}, frozenset())
        assert result.words[0].confidence == 1.0


class TestRealSegmentationBackendSupplementalLexicon:
    def test_supplemental_fills_true_oov_gap(self, real_sample_csv: Path, supplemental_csv: Path):
        # 主詞庫(real_sample_csv, 見上方fixture)沒有"的"或"欲", 應該從
        # 補充表補上
        backend = RealSegmentationBackend(csv_path=real_sample_csv, supplemental_csv_path=supplemental_csv)
        result = backend.segment("的欲")
        assert [w.tailo for w in result.words] == ["e5", "beh4"]

    def test_supplemental_does_not_override_main_dictionary_answer(
        self, real_sample_csv: Path, supplemental_csv: Path
    ):
        # 主詞庫優先: 如果"的"剛好也在主詞庫裡, 補充表不能覆蓋主詞庫的答案
        main_dict_with_de = real_sample_csv.parent / "main_with_de.csv"
        main_dict_with_de.write_text(
            "\n".join(
                [
                    _REAL_HEADER,
                    '"1","e","","main-dict-reading","","的","e","","main-dict-reading","","的","測試"',
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        backend = RealSegmentationBackend(
            csv_path=main_dict_with_de, supplemental_csv_path=supplemental_csv
        )
        result = backend.segment("的")
        assert result.words[0].tailo == "main-dict-reading"

    def test_verified_supplemental_entry_gets_full_confidence_unverified_gets_half(
        self, real_sample_csv: Path, supplemental_csv: Path
    ):
        backend = RealSegmentationBackend(csv_path=real_sample_csv, supplemental_csv_path=supplemental_csv)
        result = backend.segment("的欲")
        by_surface = {w.surface: w.confidence for w in result.words}
        assert by_surface["的"] == 1.0  # verified=true
        assert by_surface["欲"] == 0.5  # verified=false

    def test_use_supplemental_lexicon_false_disables_fallback(
        self, real_sample_csv: Path, supplemental_csv: Path
    ):
        backend = RealSegmentationBackend(
            csv_path=real_sample_csv,
            supplemental_csv_path=supplemental_csv,
            use_supplemental_lexicon=False,
        )
        result = backend.segment("的")
        assert result.words[0].tailo is None  # 沒開補充表, "的"還是OOV


class TestBuildSegmentationBackend:
    def test_unknown_backend_name_raises(self):
        class FakeConfig:
            segmentation_backend = "nonexistent"

        with pytest.raises(ValueError):
            build_segmentation_backend(FakeConfig())
