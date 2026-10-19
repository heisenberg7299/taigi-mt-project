"""pronunciation_overrides.py測試：驗證高信心、無合法例外字元(毋/我/的)
的IPA音節覆蓋邏輯(見pronunciation_overrides.py docstring的完整背景)。

用手動建構的假IPA字串測試對齊/替換邏輯本身(不需要真的載入模型)；
真實pygoruut輸出的smoke test見
test_pronunciation_overrides_fixes_real_phonemizer_output。
"""

from __future__ import annotations

import importlib.util

import pytest

from tw_hokkien_tts_pipeline.pronunciation_overrides import apply_pronunciation_overrides


def test_replaces_known_wrong_syllable_for_target_character():
    # 「毋」被念成m1(m˥˥)，應該被修正成m7(m˧˧)；其他音節不動
    hanji = "你毋通"
    ipa = "li˥˧m˥˥tʰaŋ˥˥"
    result = apply_pronunciation_overrides(hanji, ipa)
    assert result == "li˥˧m˧˧tʰaŋ˥˥"


def test_no_change_when_no_target_character_present():
    hanji = "你好嗎"
    ipa = "li˥˧ho˥˧mã˥˥"
    result = apply_pronunciation_overrides(hanji, ipa)
    assert result == ipa


def test_no_change_when_syllable_count_does_not_match_character_count():
    """字數/音節數對不起來，代表沒把握對齊，寧可不修，不要冒著改錯的風險
    (見module docstring的保守原則)。"""
    hanji = "我"
    ipa = "ɡua˥˧a˥˧"  # 故意兩個音節對一個字，模擬對不齊的情況
    result = apply_pronunciation_overrides(hanji, ipa)
    assert result == ipa


def test_preserves_trailing_untoned_content_like_rare_characters_and_punctuation():
    """替換只動目標字元自己的音節span，句尾未被音素化的雜訊字元/標點
    (沒有聲調符號、split時會被filter掉的那種)要完整保留，不能因為
    重組字串而遺失。"""
    hanji = "我恁蔡"  # 「蔡」模擬罕見字(不在phonemizer詞彙表，不會有聲調符號)
    ipa = "ɡua˥˧lin˥˧蔡"
    result = apply_pronunciation_overrides(hanji, ipa)
    assert result == "ɡua˥˧lin˥˧蔡"  # 我已經是正確音，不動；蔡完整保留


def test_punctuation_immediately_before_target_syllable_is_not_swallowed():
    """迴歸測試：標點字元緊鄰在目標字元前面時，音節切分不能把標點吸進
    音節span裡，不然整段替換時標點會被一起吃掉(開發過程實測到的bug：
    「你好，我今仔日...」的逗號因為這個原因消失)。「好」後來也被加進
    覆蓋表(見CHARACTER_IPA_OVERRIDES)，這裡順便驗證兩個目標字元(好/我)
    同時被修正、逗號還是完整保留。"""
    hanji = "你好，我今仔日"
    ipa = "li˥˧hõ˨˩，ŋɔ˥˧kin˥˥a˥˧dzit˦"
    result = apply_pronunciation_overrides(hanji, ipa)
    assert "，" in result
    assert result == "li˥˧ho˥˧，ɡua˥˧kin˥˥a˥˧dzit˦"


def test_multiple_target_characters_in_same_sentence():
    hanji = "我的藥"
    ipa = "ɡua˥˧tik˦ioʔ˨"  # 的被錯念成tik(tik4)
    result = apply_pronunciation_overrides(hanji, ipa)
    assert result == "ɡua˥˧e˨˦ioʔ˨"


_HAS_COQUI_TTS = importlib.util.find_spec("TTS") is not None
try:
    from tw_hokkien_tts_pipeline.tts import NeurlangTTSBackend

    _model_dir = NeurlangTTSBackend._DEFAULT_MODEL_DIR
    _MODEL_DIR_AVAILABLE = (_model_dir / "best_model.pth").exists() and (_model_dir / "config.json").exists()
except ImportError:
    _MODEL_DIR_AVAILABLE = False


@pytest.mark.skipif(
    not (_HAS_COQUI_TTS and _MODEL_DIR_AVAILABLE),
    reason="需要coqui-tts+neurlang模型權重都到位才會跑，這是唯一需要真的呼叫phonemizer的測試",
)
def test_pronunciation_overrides_fixes_real_phonemizer_output():
    """真實smoke test：用真的pygoruut phonemizer，確認「你毋通激動」
    這句真實輸出的「毋」確實被修正成m7(見開發過程中直接觀察到的
    'li˥˧m˥˥tʰaŋ˥˥kik˨toŋ˧˧。'，m˥˥是m1，修正後應該變成m˧˧)。"""
    from TTS.utils.synthesizer import Synthesizer

    synth = Synthesizer(
        tts_checkpoint=str(NeurlangTTSBackend._DEFAULT_MODEL_DIR / "best_model.pth"),
        tts_config_path=str(NeurlangTTSBackend._DEFAULT_MODEL_DIR / "config.json"),
    )
    phonemizer = synth.tts_model.tokenizer.phonemizer

    hanji = "你毋通激動。"
    raw_ipa = phonemizer.phonemize(hanji, separator="", language=None)
    assert "m˥˥" in raw_ipa, "這句修正前應該要有m1(m˥˥)這個已知錯誤，不然測試前提不成立"

    fixed = apply_pronunciation_overrides(hanji, raw_ipa)
    assert "m˧˧" in fixed
    assert "m˥˥" not in fixed
