import wave
from pathlib import Path

import pytest

from tw_hokkien_tts_pipeline.config import PipelineConfig
from tw_hokkien_tts_pipeline.pipeline import Pipeline
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard
from tw_hokkien_tts_pipeline.romanize import apply_tone_sandhi_numbered


def test_protected_token_round_trip():
    guard = ProtectedTokenGuard(
        drug_lexicon={"盤尼西林": "puân-nî-se-lîm"},
        person_names={"王先生"},
    )
    text = "請記得幫王先生在晚餐後服用盤尼西林120毫克。"
    mask_result = guard.mask(text)

    # 佔位符應該取代掉原文中的敏感詞
    assert "王先生" not in mask_result.masked_text
    assert "盤尼西林" not in mask_result.masked_text
    assert "120毫克" not in mask_result.masked_text

    # 還原成中文應該完全等於原文
    restored = guard.unmask_text(mask_result.masked_text, mask_result.spans)
    assert restored == text

    # 藥名應該有查到台羅讀音, 劑量/人名沒有詞庫則保留原文
    drug_spans = [s for s in mask_result.spans if s.kind == "DRUG"]
    assert drug_spans and drug_spans[0].tailo == "puân-nî-se-lîm"


def test_protected_token_coverage():
    # 阿斯匹靈是已知藥名但尚未有人工校正過的台羅讀音 (值為 None)
    guard = ProtectedTokenGuard(
        drug_lexicon={"盤尼西林": "puân-nî-se-lîm", "阿斯匹靈": None}
    )
    mask_result = guard.mask("服用盤尼西林與阿斯匹靈")
    # 兩個藥名都被偵測到, 但只有一個有台羅讀音, coverage 應為 0.5
    assert guard.coverage(mask_result.spans) == 0.5


def test_tone_sandhi_last_syllable_unchanged():
    result = apply_tone_sandhi_numbered(["tai5", "lo5"])
    assert result[-1] == "lo5"  # 最後一字維持本調
    assert result[0] == "tai7"  # 陽平(5) 依簡化規則變陰去(7)


def test_tone_sandhi_single_syllable_unchanged():
    assert apply_tone_sandhi_numbered(["lo5"]) == ["lo5"]


def test_tone_sandhi_ignores_non_numbered_input():
    result = apply_tone_sandhi_numbered(["tâi", "lô"])
    assert result == ["tâi", "lô"]


def test_pipeline_end_to_end_mock(tmp_path: Path):
    config = PipelineConfig(output_dir=tmp_path)
    pipeline = Pipeline(
        config=config,
        drug_lexicon={"盤尼西林": "puân-nî-se-lîm"},
    )
    result = pipeline.run("請記得在晚餐後服用盤尼西林。", out_filename="test.wav")

    # wav 檔案應該存在且可被 wave 模組讀取
    assert result.tts.wav_path.exists()
    with wave.open(str(result.tts.wav_path), "rb") as wav_file:
        assert wav_file.getnframes() > 0

    # debug trace 應該有輸出
    debug_path = tmp_path / "test.debug.json"
    assert debug_path.exists()

    # 藥名的台羅讀音應該出現在最終合成文字中
    assert "puân-nî-se-lîm" in result.romanization.text


def test_pipeline_blocks_when_full_coverage_required(tmp_path: Path):
    config = PipelineConfig(
        output_dir=tmp_path,
        require_full_protected_coverage=True,
    )
    # 阿斯匹靈是已知藥名但沒有人工校正過的台羅讀音, 應該被擋下而不是猜發音
    pipeline = Pipeline(
        config=config,
        drug_lexicon={"盤尼西林": "puân-nî-se-lîm", "阿斯匹靈": None},
    )

    with pytest.raises(ValueError):
        pipeline.run("請服用阿斯匹靈")
