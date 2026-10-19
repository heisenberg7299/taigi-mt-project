"""clause_pause_synthesis.py測試：驗證用程式明確插入靜音處理斷句/停頓
的邏輯(見模組docstring的完整背景)。

用假的synth(FakeSynth，回傳固定長度的假waveform，記錄被呼叫過的文字)
測試切分/插入靜音/合併邏輯本身，不需要真的載入模型。
"""

from __future__ import annotations

from tw_hokkien_tts_pipeline.clause_pause_synthesis import (
    split_into_clauses,
    synthesize_with_explicit_pauses,
)


def test_split_into_clauses_splits_on_fullwidth_punctuation():
    text = "你好，我今仔日感覺無舒服。請共我叫護理師好無？"
    assert split_into_clauses(text) == ["你好", "我今仔日感覺無舒服", "請共我叫護理師好無"]


def test_split_into_clauses_single_sentence_no_punctuation():
    assert split_into_clauses("我欲食藥仔矣") == ["我欲食藥仔矣"]


def test_split_into_clauses_drops_empty_pieces_from_consecutive_punctuation():
    assert split_into_clauses("你好，，，我好") == ["你好", "我好"]


class FakeSynth:
    def __init__(self, output_sample_rate=22050):
        self.output_sample_rate = output_sample_rate
        self.calls: list[str] = []

    def tts(self, text: str):
        self.calls.append(text)
        return [1.0, 1.0, 1.0]  # 固定長度的假waveform，方便驗證有幾段


def test_single_clause_calls_tts_once_with_original_text_unchanged():
    """沒有標點可切時，直接呼叫原本的synth.tts(text)，不做任何額外處理
    (不該把「我欲食藥仔矣」多此一舉地當成1個clause重新組裝)。"""
    synth = FakeSynth()
    result = synthesize_with_explicit_pauses(synth, "我欲食藥仔矣")
    assert synth.calls == ["我欲食藥仔矣"]
    assert result == [1.0, 1.0, 1.0]


def test_multiple_clauses_each_synthesized_separately_with_silence_between():
    synth = FakeSynth(output_sample_rate=1000)  # 1000Hz方便算靜音長度
    result = synthesize_with_explicit_pauses(synth, "你好，我好", pause_ms=100)
    assert synth.calls == ["你好", "我好"]
    # 100ms靜音在1000Hz下 = 100個樣本；[1,1,1] + [0]*100 + [1,1,1]
    assert len(result) == 3 + 100 + 3
    assert result[:3] == [1.0, 1.0, 1.0]
    assert result[3:103] == [0.0] * 100
    assert result[103:] == [1.0, 1.0, 1.0]


def test_no_trailing_silence_after_last_clause():
    synth = FakeSynth(output_sample_rate=1000)
    result = synthesize_with_explicit_pauses(synth, "你好，我好，伊好", pause_ms=50)
    assert synth.calls == ["你好", "我好", "伊好"]
    # 3段話、2個靜音間隔(段落之間，不是段落之後)
    assert len(result) == 3 * 3 + 2 * 50
    assert result[-3:] == [1.0, 1.0, 1.0]  # 最後一段結尾不該還有靜音
