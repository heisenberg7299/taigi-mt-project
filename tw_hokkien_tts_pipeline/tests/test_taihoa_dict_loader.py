"""測試taihoa_dict_loader.py, 用實際從ChhoeTaigiDatabase README/CSV(見
data/licenses/chhoetaigi_taihoa_dict.json)核對過的5筆真實資料當fixture,
不是自己編造的假資料——完整91,339列CSV本身沒有隨repo提供(見模組
docstring), 這裡的fixture就是拿真實表頭+真實前5列資料寫成暫存CSV測試。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tw_hokkien_tts_pipeline.taihoa_dict_loader import (
    _canonicalize_readings,
    _readings_equal_modulo_missing_tone,
    glosses_for_surface,
    load_taihoa_dict,
    load_taihoa_dict_with_stats,
)

_REAL_HEADER = (
    '"DictWordID","PojUnicode","PojUnicodeOthers","PojInput","PojInputOthers",'
    '"HanLoTaibunPoj","KipUnicode","KipUnicodeOthers","KipInput","KipInputOthers",'
    '"HanLoTaibunKip","HoaBun"'
)
# 這5列是實際查證過的ChhoeTaigi_TaihoaSoanntengTuichiautian.csv真實資料
_REAL_ROWS = [
    '"1","á-bô","","a2-bo5","","á無","á-bô","","a2-bo5","","á無","不然"',
    '"2","á-bô","","a2-bo5","","á無","á-bô","","a2-bo5","","á無","還是沒有"',
    '"3","á-î","","a2-i5","","á蛦","á-î","","a2-i5","","á蛦","蟬"',
    '"4","á-phàu","","a2-phau3","","阿炮","á-phàu","","a2-phau3","","阿炮","凱子"',
    '"5","à-lêng","","a3-leng5","","啞鈴","à-lîng","","a3-ling5","","啞鈴","小鎮"',
]


@pytest.fixture
def real_sample_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("\n".join([_REAL_HEADER, *_REAL_ROWS]) + "\n", encoding="utf-8")
    return csv_path


class TestLoadTaihoaDict:
    def test_missing_file_raises_with_download_hint(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.csv"
        with pytest.raises(FileNotFoundError) as exc_info:
            load_taihoa_dict(missing)
        assert "curl" in str(exc_info.value)
        assert str(missing) in str(exc_info.value)

    def test_loads_surface_to_tailo_from_hanlo_taibun_poj_not_hoa_bun(self, real_sample_csv: Path):
        result = load_taihoa_dict(real_sample_csv)
        # key是HanLoTaibunPoj(台語漢羅寫法), 不是HoaBun(華語翻譯)
        assert "á無" in result
        assert "不然" not in result
        assert "還是沒有" not in result

    def test_pojinput_values_come_through_via_poj_to_tailo(self, real_sample_csv: Path):
        result = load_taihoa_dict(real_sample_csv)
        # 這5筆真實資料都沒有ch/chh/o͘/ⁿ, poj_word_to_tailo()應該原樣通過
        assert result["á蛦"] == "a2-i5"
        assert result["阿炮"] == "a2-phau3"
        assert result["啞鈴"] == "a3-leng5"

    def test_duplicate_surface_with_same_reading_collapses_to_one_entry(self, real_sample_csv: Path):
        # DictWordID 1跟2都是"á無", 讀音相同, 應該只留一筆, 值是"a2-bo5"
        result = load_taihoa_dict(real_sample_csv)
        assert result["á無"] == "a2-bo5"
        assert len(result) == 4  # 5列but "á無"出現兩次, 去重後剩4個surface


class TestLoadTaihoaDictWithStats:
    def test_stats_match_dict_values_no_inconsistency(self, real_sample_csv: Path):
        """load_taihoa_dict()跟load_taihoa_dict_with_stats()對同一個surface
        要選出同一個讀音, 不能有兩套不一致的挑選邏輯。"""
        plain_result = load_taihoa_dict(real_sample_csv)
        stats_result, _ = load_taihoa_dict_with_stats(real_sample_csv)
        assert plain_result == stats_result

    def test_stats_counts_are_correct_for_unambiguous_sample(self, real_sample_csv: Path):
        _, stats = load_taihoa_dict_with_stats(real_sample_csv)
        assert stats.total_rows == 5
        assert stats.unique_surfaces == 4
        assert stats.ambiguous_surfaces == 0  # 這5筆真實資料裡沒有真正的歧義詞

    def test_ambiguous_surface_detected_when_readings_differ(self, tmp_path: Path):
        """用一筆刻意編造(非真實ChhoeTaigi資料, 純粹測試用)的重複surface但
        不同讀音的列, 驗證ambiguous_surfaces統計邏輯真的有在比對讀音差異,
        不是隨便回傳0。"""
        csv_path = tmp_path / "synthetic_ambiguous.csv"
        rows = [
            '"1","á-bô","","a2-bo5","","測試詞","á-bô","","a2-bo5","","測試詞","義項一"',
            '"2","á-bo̍h","","a2-boh8","","測試詞","á-bo̍h","","a2-boh8","","測試詞","義項二(不同讀音)"',
        ]
        csv_path.write_text("\n".join([_REAL_HEADER, *rows]) + "\n", encoding="utf-8")

        result, stats = load_taihoa_dict_with_stats(csv_path)
        assert stats.ambiguous_surfaces == 1
        assert stats.strategy == "first"
        # 依CSV出現順序, 保留第一筆("a2-bo5")當預設值
        assert result["測試詞"] == "a2-bo5"


class TestFalseAmbiguityFromMissingToneDigit:
    """測試「今仔日」這類假歧義的偵測/合併邏輯——CSV裡有些列漏標最後一個
    音節的調號, 不是真正的多音字, 見taihoa_dict_loader.py模組docstring
    「假歧義」章節。"""

    def test_readings_equal_modulo_missing_tone_true_case(self):
        assert _readings_equal_modulo_missing_tone("kin-a2-jit", "kin-a2-jit8") is True

    def test_readings_equal_modulo_missing_tone_false_when_other_syllable_differs(self):
        # 不只尾端調號不同, 中間音節本身就不一樣, 不該被判定為「只差調號」
        assert _readings_equal_modulo_missing_tone("kin-a2-jit", "kin-a3-jit8") is False

    def test_readings_equal_modulo_missing_tone_false_for_genuine_heteronym(self):
        # 行(hîng5/kiânn5)是真正的白讀/文讀差異, 不是漏標調號, 不該被合併
        assert _readings_equal_modulo_missing_tone("heng5", "kiann5") is False

    def test_readings_equal_modulo_missing_tone_false_different_syllable_count(self):
        assert _readings_equal_modulo_missing_tone("kin-a2-jit8", "jit8") is False

    def test_canonicalize_merges_missing_tone_variant_keeping_the_toned_one(self):
        merged = _canonicalize_readings(["kin-a2-jit", "kin-a2-jit8", "kin-a2-jit8"])
        assert merged == ["kin-a2-jit8", "kin-a2-jit8", "kin-a2-jit8"]

    def test_canonicalize_does_not_touch_genuine_heteronyms(self):
        readings = ["heng5-khi3", "kiann5-khi3", "kiann5-khui3"]
        assert _canonicalize_readings(readings) == readings

    def test_end_to_end_false_ambiguity_not_counted_as_ambiguous(self, tmp_path: Path):
        """完整走一次load_taihoa_dict_with_stats(), 確認"今仔日"這種只差
        調號有沒有標的case, 不會被算進ambiguous_surfaces, 而且first/majority
        兩種策略應該給出一致的(有標調號的)答案。"""
        rows = [
            '"1","kin-a2-jit","","kin-a2-jit","","今仔日","kin-a2-jit","","kin-a2-jit","","今仔日","今天"',
            '"2","kin-a2-jit8","","kin-a2-jit8","","今仔日","kin-a2-jit8","","kin-a2-jit8","","今仔日","今天(另一句)"',
        ]
        csv_path = tmp_path / "synthetic_false_ambiguity.csv"
        csv_path.write_text("\n".join([_REAL_HEADER, *rows]) + "\n", encoding="utf-8")

        first_result, first_stats = load_taihoa_dict_with_stats(csv_path, strategy="first")
        majority_result, majority_stats = load_taihoa_dict_with_stats(csv_path, strategy="majority")

        assert first_stats.ambiguous_surfaces == 0
        assert majority_stats.ambiguous_surfaces == 0
        assert first_result["今仔日"] == "kin-a2-jit8"
        assert majority_result["今仔日"] == "kin-a2-jit8"


class TestDisambiguationStrategy:
    """測試"first"跟"majority"兩種消歧策略——兩者刻意都要能用, 不是
    "majority"取代"first", 見taihoa_dict_loader.py模組docstring。"""

    def _write_csv(self, tmp_path: Path, rows: list[str]) -> Path:
        csv_path = tmp_path / "synthetic.csv"
        csv_path.write_text("\n".join([_REAL_HEADER, *rows]) + "\n", encoding="utf-8")
        return csv_path

    def test_majority_picks_most_frequent_reading(self, tmp_path: Path):
        # "測試詞"三筆是reading_a、一筆是reading_b, majority應該選reading_a
        rows = [
            f'"{i}","x","","reading_a","","測試詞","x","","reading_a","","測試詞","義{i}"'
            for i in range(1, 4)
        ] + ['"4","y","","reading_b","","測試詞","y","","reading_b","","測試詞","義4"']
        csv_path = self._write_csv(tmp_path, rows)

        first_result = load_taihoa_dict(csv_path, strategy="first")
        majority_result = load_taihoa_dict(csv_path, strategy="majority")
        assert first_result["測試詞"] == "reading_a"  # 剛好第一筆也是多數, 這裡先確認前提
        assert majority_result["測試詞"] == "reading_a"

    def test_majority_differs_from_first_when_first_entry_is_minority(self, tmp_path: Path):
        # 第一筆是少數讀音(reading_b只出現1次), 後面兩筆reading_a出現2次,
        # "first"應該選到reading_b, "majority"應該選到reading_a——兩者要
        # 給出不同答案, 這才是這個功能真正的價值所在
        rows = [
            '"1","y","","reading_b","","測試詞","y","","reading_b","","測試詞","義1"',
            '"2","x","","reading_a","","測試詞","x","","reading_a","","測試詞","義2"',
            '"3","x","","reading_a","","測試詞","x","","reading_a","","測試詞","義3"',
        ]
        csv_path = self._write_csv(tmp_path, rows)

        first_result = load_taihoa_dict(csv_path, strategy="first")
        majority_result = load_taihoa_dict(csv_path, strategy="majority")
        assert first_result["測試詞"] == "reading_b"
        assert majority_result["測試詞"] == "reading_a"

    def test_majority_tie_falls_back_to_first_occurrence_deterministically(self, tmp_path: Path):
        # 1:1真平手時, majority也要有確定的答案(不能每次執行結果不一樣),
        # 退回第一次出現的那個
        rows = [
            '"1","y","","reading_b","","測試詞","y","","reading_b","","測試詞","義1"',
            '"2","x","","reading_a","","測試詞","x","","reading_a","","測試詞","義2"',
        ]
        csv_path = self._write_csv(tmp_path, rows)

        result1 = load_taihoa_dict(csv_path, strategy="majority")
        result2 = load_taihoa_dict(csv_path, strategy="majority")
        assert result1["測試詞"] == result2["測試詞"] == "reading_b"

    def test_unknown_strategy_raises(self, real_sample_csv: Path):
        with pytest.raises(ValueError):
            load_taihoa_dict(real_sample_csv, strategy="bogus")

    def test_stats_records_which_strategy_was_used(self, real_sample_csv: Path):
        _, stats = load_taihoa_dict_with_stats(real_sample_csv, strategy="majority")
        assert stats.strategy == "majority"


class TestGlossesForSurface:
    def test_returns_glosses_grouped_by_reading(self, real_sample_csv: Path):
        result = glosses_for_surface(real_sample_csv, "á無")
        assert result == {"a2-bo5": ["不然", "還是沒有"]}

    def test_unknown_surface_returns_empty_dict(self, real_sample_csv: Path):
        assert glosses_for_surface(real_sample_csv, "查無此詞") == {}

    def test_single_gloss_entry(self, real_sample_csv: Path):
        result = glosses_for_surface(real_sample_csv, "á蛦")
        assert result == {"a2-i5": ["蟬"]}
