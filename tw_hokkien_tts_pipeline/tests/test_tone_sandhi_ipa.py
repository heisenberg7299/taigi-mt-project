"""tone_sandhi_ipa.py測試：驗證把romanize.py既有的連讀變調規則套用到
pygoruut IPA輸出的邏輯(見tone_sandhi_ipa.py docstring的完整背景)。

用手動建構的IPA字串測試變調/詞組切分邏輯本身(不需要真的載入模型)；
真實pygoruut輸出的smoke test見
test_tone_sandhi_matches_expected_pattern_on_real_phonemizer_output。
"""

from __future__ import annotations

import importlib.util

import pytest

from tw_hokkien_tts_pipeline.tone_sandhi_ipa import apply_tone_sandhi_to_ipa


def test_two_syllable_word_first_syllable_sandhis_second_stays():
    # tai5(˨˦) + lo5(˨˦)：romanize.py的_SANDHI_CYCLE規則 5->7，
    # 第一個音節應該變成˧˧(tone7)，第二個(最後一個)維持˨˦(tone5)不變
    ipa = "tai˨˦lo˨˦"
    result = apply_tone_sandhi_to_ipa(ipa)
    assert result == "tai˧˧lo˨˦"


def test_single_syllable_unchanged():
    """單一音節就是自己詞組裡的最後一個，不該被變調。"""
    ipa = "e˧˧"
    assert apply_tone_sandhi_to_ipa(ipa) == "e˧˧"


def test_last_syllable_before_punctuation_is_tone_group_boundary():
    """標點字元切詞組邊界：逗號前的音節是它那個詞組的「最後一個」，
    不該被變調；逗號後面開始新詞組。"""
    # "好，好" -> 第一個"好"(˥˧,tone2)在逗號前=詞組結尾，不變調
    # 第二個"好"是全句最後一個字，也是它詞組的結尾，也不變調
    ipa = "ho˥˧，ho˥˧"
    result = apply_tone_sandhi_to_ipa(ipa)
    assert result == "ho˥˧，ho˥˧"


def test_sandhi_applies_within_each_comma_separated_group_independently():
    # "你好，我好" -> 你(li,tone2,非最後)要變調成1調(˥˥)；
    # 好(第一個，逗號前=詞組結尾)不變調；我(非最後)變調2->1；好(全句最後)不變調
    ipa = "li˥˧ho˥˧，ɡua˥˧ho˥˧"
    result = apply_tone_sandhi_to_ipa(ipa)
    assert result == "li˥˥ho˥˧，ɡua˥˥ho˥˧"


def test_unrecognized_tone_pattern_left_unchanged():
    """不在對照表裡的聲調符號組合，原樣保留，不要亂猜。"""
    ipa = "xyz˥˩˧"  # 不是任何已知合法的聲調組合
    assert apply_tone_sandhi_to_ipa(ipa) == ipa


_HAS_COQUI_TTS = importlib.util.find_spec("TTS") is not None
try:
    from tw_hokkien_tts_pipeline.tts import NeurlangTTSBackend

    _model_dir = NeurlangTTSBackend._DEFAULT_MODEL_DIR
    _MODEL_DIR_AVAILABLE = (_model_dir / "best_model.pth").exists() and (_model_dir / "config.json").exists()
except ImportError:
    _MODEL_DIR_AVAILABLE = False


@pytest.mark.skipif(
    not (_HAS_COQUI_TTS and _MODEL_DIR_AVAILABLE),
    reason="需要coqui-tts+neurlang模型權重都到位才會跑",
)
def test_tone_sandhi_matches_expected_pattern_on_real_phonemizer_output():
    """真實smoke test：「我的藥」的「我」(gua2)不是最後一個字，套用
    變調後應該從本調2(˥˧)變成1調(˥˥)，「藥」(最後一個字)維持本調不變。"""
    from TTS.utils.synthesizer import Synthesizer

    synth = Synthesizer(
        tts_checkpoint=str(NeurlangTTSBackend._DEFAULT_MODEL_DIR / "best_model.pth"),
        tts_config_path=str(NeurlangTTSBackend._DEFAULT_MODEL_DIR / "config.json"),
    )
    phonemizer = synth.tts_model.tokenizer.phonemizer

    raw_ipa = phonemizer.phonemize("我欲食藥仔矣", separator="", language=None)
    sandhied = apply_tone_sandhi_to_ipa(raw_ipa)
    assert sandhied != raw_ipa, "這句應該要有非最後音節被變調，不然測試前提不成立"
