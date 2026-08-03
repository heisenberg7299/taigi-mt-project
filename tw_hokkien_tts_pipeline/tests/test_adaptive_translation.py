"""
Adaptive Protected Token(雙路翻譯+安全檢查選擇)的測試, 用假backend讓結果
決定性、不需要Ollama。

背景：實測10句泛化測試發現「一律遮罩」策略對「模型本來就認得的常見詞」
(普拿疼)反而有害——遮罩成DRUGA後模型當成陌生詞去泛化翻譯，比不遮罩還差。
這裡的測試對應三種實際觀察到的情境：候選A(原文)就成功、候選A失敗但候選B
(遮罩)成功、兩者都失敗。
"""

from __future__ import annotations

import pytest

from tw_hokkien_tts_pipeline.adaptive_translation import UnsafeTranslationError, translate_adaptive
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard
from tw_hokkien_tts_pipeline.translate import TranslationBackend, TranslationResult


class _FakeBackend(TranslationBackend):
    """依固定對照表回傳翻譯結果的假backend, 讓adaptive邏輯的測試是決定性的。"""

    name = "fake"

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.call_log: list[str] = []

    def translate(self, zh_text: str) -> TranslationResult:
        self.call_log.append(zh_text)
        return TranslationResult(
            source_text=zh_text,
            translated_text=self.mapping.get(zh_text, zh_text),
            backend_name=self.name,
        )


def test_raw_candidate_chosen_when_it_preserves_entities_and_passes_safety():
    """對應「普拿疼」案例：模型本來就認得的常見詞，原文不遮罩直接翻譯就
    成功保留，不應該白白多花一次LLM呼叫去試遮罩版本。"""
    guard = ProtectedTokenGuard(drug_lexicon={"普拿疼": "phóo-ná-thàng"})
    backend = _FakeBackend({"這罐普拿疼一天不要吃超過六顆。": "這罐普拿疼一日毋通食超過六粒。"})

    result = translate_adaptive("這罐普拿疼一天不要吃超過六顆。", guard, backend)

    assert result.chosen == "raw"
    assert result.masked_candidate is None
    assert "普拿疼" in result.hanji_text
    # 候選A成功時不應該再呼叫一次masked版本 (省一次LLM呼叫)
    assert len(backend.call_log) == 1


def test_falls_back_to_masked_candidate_when_raw_drops_entity():
    """對應「盤尼西林」案例：原文翻譯把藥名吃掉，遮罩後翻譯才保留佔位符，
    應該fallback使用遮罩版本(還原後)。"""
    guard = ProtectedTokenGuard(drug_lexicon={"盤尼西林": "puân-nî-se-lîm"})
    backend = _FakeBackend({
        "請服用盤尼西林。": "請食藥仔。",  # 候選A：藥名被吃掉
        "請服用DRUGA。": "請食DRUGA。",  # 候選B：佔位符保留
    })

    result = translate_adaptive("請服用盤尼西林。", guard, backend)

    assert result.chosen == "masked"
    assert result.masked_candidate is not None
    assert not result.raw_candidate.entities_ok
    assert result.masked_candidate.entities_ok
    assert "盤尼西林" in result.hanji_text
    assert "DRUGA" not in result.hanji_text
    # 候選A失敗才會真的呼叫候選B
    assert len(backend.call_log) == 2


def test_raises_unsafe_translation_error_when_both_candidates_fail():
    """對應「小明」/「陳太太」案例：兩條路都救不回來時，要fail closed，
    不能兩害相權取其輕地選一個「比較不差」的版本硬用。"""
    guard = ProtectedTokenGuard(person_names={"小明"})
    backend = _FakeBackend({
        "小明先生，你的報告出來了。": "先生，你的報告出來矣。",  # 候選A：人名整個消失
        "PERSONA先生，你的報告出來了。": "先生，你的報告出來矣。",  # 候選B：佔位符也消失
    })

    with pytest.raises(UnsafeTranslationError) as exc_info:
        translate_adaptive("小明先生，你的報告出來了。", guard, backend)

    err = exc_info.value
    assert not err.raw_candidate.entities_ok
    assert not err.masked_candidate.entities_ok


def test_no_protected_entities_short_circuits_to_raw_without_extra_call():
    """句子裡沒有任何protected entity時(drug_lexicon/person_names都沒配到)，
    候選A不需要檢查entities，只要安全檢查通過就直接用，不必浪費一次呼叫試B。"""
    guard = ProtectedTokenGuard()
    backend = _FakeBackend({"今天天氣很好。": "今仔日天色真好。"})

    result = translate_adaptive("今天天氣很好。", guard, backend)

    assert result.chosen == "raw"
    assert result.hanji_text == "今仔日天色真好。"
    assert len(backend.call_log) == 1
