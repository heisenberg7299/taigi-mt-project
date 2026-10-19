"""
phoneme_normalize.py測試：修正neurlang VITS(pygoruut phonemizer)因Unicode
正規化形式不匹配、被靜默丟棄的送氣/鼻化音素+全形標點問題(見
reports/tts_oov_audit.md、tw_hokkien_tts_pipeline/phoneme_normalize.py
docstring的完整背景說明)。

`test_normalize_phonemes_*`是純字串轉換的單元測試，不需要真的載入模型。
`test_patch_neurlang_phonemizer_*`是真實smoke test，需要neurlang模型權重
+coqui-tts都到位才會跑，缺任一個直接skip，跟test_tts_neurlang_smoke.py
同樣的慣例。
"""

from __future__ import annotations

import importlib.util
import unicodedata

import pytest

from tw_hokkien_tts_pipeline.phoneme_normalize import normalize_phonemes


def test_aspiration_modifier_converts_to_plain_h():
    """ʰ(U+02B0，模型詞彙表沒有)轉成純字母h(模型詞彙表有)，對應台語羅馬字
    (白話字/台羅)標準寫法本來就是用「子音+h」表示送氣(th/ph/kh/tsh)。"""
    assert normalize_phonemes("tsʰiŋ") == "tshiŋ"
    assert "ʰ" not in normalize_phonemes("pʰa kʰi tʰai tsʰa")


def test_precomposed_nasalized_vowels_decompose_to_vowel_plus_combining_tilde():
    """模型詞彙表沒有precomposed鼻化母音(ã/ĩ/ũ/ẽ/õ)，但有組合用鼻化符號
    (combining tilde, U+0303)，NFD正規化後兩個部分都在詞彙表裡查得到。"""
    for vowel, nasalized in [("a", "ã"), ("i", "ĩ"), ("u", "ũ"), ("e", "ẽ"), ("o", "õ")]:
        result = normalize_phonemes(nasalized)
        assert result == unicodedata.normalize("NFD", nasalized)
        assert vowel in result
        assert "̃" in result  # combining tilde
        assert nasalized not in result  # precomposed形式不應該還留著


def test_fullwidth_chinese_punctuation_is_left_untouched():
    """全形中文標點轉半形ASCII標點這個做法實測後被使用者回報「斷句更怪」，
    已經撤掉(見phoneme_normalize.py docstring「全形標點轉半形：實測後
    撤掉了」)，這裡鎖定「不處理標點」是目前故意的行為，不是遺漏。"""
    assert normalize_phonemes("你好，我欲食飯。") == "你好，我欲食飯。"
    assert normalize_phonemes("按怎？") == "按怎？"
    assert normalize_phonemes("緊來！") == "緊來！"


def test_normalize_is_noop_for_already_supported_symbols():
    """一般ASCII IPA符號、半形標點不應該被這個正規化動到。"""
    text = "li2 ho2, ts a i5 pai2."
    assert normalize_phonemes(text) == unicodedata.normalize("NFD", text)


def test_combined_sentence_fixes_phonemes_but_leaves_punctuation_alone():
    raw = "tsʰĩã˥˧ki˨˩tit˨tsai˧˧am˨˩tǹɡau˧˧tsiaʔ˦ioʔ˨a˥˧。"
    result = normalize_phonemes(raw)
    assert "ʰ" not in result
    assert "ĩ" not in result
    assert "ã" not in result
    assert result.endswith("。")  # 標點刻意不處理，見上面的說明


_MODEL_DIR_AVAILABLE = False
try:
    from tw_hokkien_tts_pipeline.tts import NeurlangTTSBackend

    _model_dir = NeurlangTTSBackend._DEFAULT_MODEL_DIR
    _MODEL_DIR_AVAILABLE = (_model_dir / "best_model.pth").exists() and (_model_dir / "config.json").exists()
except ImportError:
    pass

_HAS_COQUI_TTS = importlib.util.find_spec("TTS") is not None and importlib.util.find_spec("TTS.utils.synthesizer") is not None


@pytest.mark.skipif(
    not (_HAS_COQUI_TTS and _MODEL_DIR_AVAILABLE),
    reason="需要coqui-tts(transformers<5)+neurlang模型權重都到位才會跑，這是唯一需要真的載入模型的測試，上面的都是純字串轉換單元測試",
)
def test_patch_neurlang_phonemizer_eliminates_previously_dropped_phoneme_symbols():
    """真實smoke test：用真的Synthesizer+真的tokenizer，驗證修正前後
    not_found_characters(coqui-tts tokenizer自己記錄的「查不到vocab、被
    靜默丟棄」清單)的差異——修正後，送氣/鼻化符號不應該再出現在這個清單裡
    (鼻音聲調符號ń/ǹ是已知殘留限制，不在這個測試的驗證範圍)。**全形標點
    刻意不驗證**：轉半形標點這個做法實測後使用者回報斷句更怪，已經撤掉，
    全形標點現在應該還是會被丟棄，這是目前故意的行為。"""
    from TTS.utils.synthesizer import Synthesizer

    from tw_hokkien_tts_pipeline.phoneme_normalize import patch_neurlang_phonemizer

    synth = Synthesizer(
        tts_checkpoint=str(NeurlangTTSBackend._DEFAULT_MODEL_DIR / "best_model.pth"),
        tts_config_path=str(NeurlangTTSBackend._DEFAULT_MODEL_DIR / "config.json"),
    )
    tokenizer = synth.tts_model.tokenizer

    sentence = "你好，請問有啥物需要鬥相共的無？"  # 已知含送氣+鼻化母音+全形標點

    tokenizer.not_found_characters = []
    tokenizer.text_to_ids(sentence)
    dropped_before = set(tokenizer.not_found_characters)
    assert dropped_before, "這句話修正前應該要有被丟棄的符號，不然測試前提不成立"

    patch_neurlang_phonemizer(synth)

    tokenizer.not_found_characters = []
    tokenizer.text_to_ids(sentence)
    dropped_after = set(tokenizer.not_found_characters)

    assert "ʰ" not in dropped_after
    assert not ({"ã", "ĩ", "ũ", "ẽ", "õ"} & dropped_after)
    assert {"，", "？"} <= dropped_after  # 標點刻意還是會被丟棄
