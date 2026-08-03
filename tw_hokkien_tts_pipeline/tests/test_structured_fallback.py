"""
測試 person_records.py(呼格判斷)、structured_renderer.py(候選C模板)、
adaptive_translation.py 的 translate_with_structured_fallback(A->B->C->fail
closed 完整順序)。用假backend讓結果決定性，不需要Ollama。
"""

from __future__ import annotations

import pytest

from tw_hokkien_tts_pipeline.adaptive_translation import (
    UnsafeTranslationError,
    translate_with_structured_fallback,
)
from tw_hokkien_tts_pipeline.person_records import PersonRecord, is_vocative_address, vocative_remainder
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard
from tw_hokkien_tts_pipeline.structured_renderer import StructuredIntent, StructuredMedicalRenderer
from tw_hokkien_tts_pipeline.translate import TranslationBackend, TranslationResult


class _FakeBackend(TranslationBackend):
    name = "fake"

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.call_log: list[str] = []

    def translate(self, zh_text: str) -> TranslationResult:
        self.call_log.append(zh_text)
        return TranslationResult(
            source_text=zh_text, translated_text=self.mapping.get(zh_text, zh_text), backend_name=self.name,
        )


# ---------- person_records.py ----------

def test_is_vocative_address_detects_full_name_plus_title_at_sentence_start():
    person = PersonRecord(full_name="王小明", title="先生", role="patient")
    assert is_vocative_address("王小明先生，你的抽血報告出來了。", person)


def test_is_vocative_address_false_for_third_person_description():
    person = PersonRecord(full_name="陳太太", title=None, role="patient")
    assert not is_vocative_address("隔壁床的陳太太剛剛按了呼叫鈴。", person)


def test_vocative_remainder_strips_the_vocative_head():
    person = PersonRecord(full_name="王小明", title="先生", role="patient")
    remainder = vocative_remainder("王小明先生，你的抽血報告出來了。", person)
    assert remainder == "你的抽血報告出來了。"


# ---------- structured_renderer.py ----------

def test_structured_renderer_addressing_patient_keeps_name_untouched_by_llm():
    renderer = StructuredMedicalRenderer()
    backend = _FakeBackend({"你的抽血報告出來了。": "[TRANSLATED]"})
    intent = StructuredIntent(
        intent="addressing_patient", patient="王小明", patient_title="先生",
        remainder_zh="你的抽血報告出來了。",
    )
    result = renderer.render(intent, backend)
    assert result == "王小明先生，[TRANSLATED]"
    # 姓名本身不應該出現在送進LLM的呼叫紀錄裡
    assert all("王小明" not in call for call in backend.call_log)


def test_structured_renderer_request_staff_includes_person_location_role():
    renderer = StructuredMedicalRenderer()
    intent = StructuredIntent(intent="request_staff", patient="陳太太", location="隔壁床", staff_role="護理師", need="協助")
    result = renderer.render(intent)
    assert "陳太太" in result and "隔壁床" in result and "護理師" in result


def test_structured_renderer_rejects_unsupported_intent():
    renderer = StructuredMedicalRenderer()
    assert not renderer.can_handle(StructuredIntent(intent="unknown_intent"))
    assert not renderer.can_handle(None)


# ---------- translate_with_structured_fallback: A -> B -> C -> fail closed ----------

def test_full_pipeline_uses_candidate_a_when_it_succeeds_without_touching_c():
    guard = ProtectedTokenGuard(drug_lexicon={"普拿疼": "phóo-ná-thàng"})
    backend = _FakeBackend({"這罐普拿疼一天不要吃超過六顆。": "這罐普拿疼一日毋通食超過六粒。"})
    renderer = StructuredMedicalRenderer()

    result = translate_with_structured_fallback(
        "這罐普拿疼一天不要吃超過六顆。", guard, backend,
        structured_intent=StructuredIntent(intent="medication_reminder", drug="普拿疼"),
        structured_renderer=renderer,
    )
    assert result.chosen == "raw"


def test_full_pipeline_falls_back_to_candidate_c_when_a_and_b_both_fail():
    guard = ProtectedTokenGuard(drug_lexicon={"盤尼西林": "puân-nî-se-lîm"})
    backend = _FakeBackend({
        "請服用盤尼西林。": "請食藥仔。",  # 候選A：藥名被吃掉
        "請服用DRUGA。": "請食藥仔。",  # 候選B：佔位符也被吃掉
    })
    renderer = StructuredMedicalRenderer()
    intent = StructuredIntent(intent="medication_reminder", drug="盤尼西林")

    result = translate_with_structured_fallback(
        "請服用盤尼西林。", guard, backend, structured_intent=intent, structured_renderer=renderer,
    )
    assert result.chosen == "structured_c"
    assert "盤尼西林" in result.hanji_text


def test_full_pipeline_still_raises_when_c_does_not_support_the_intent():
    """候選C只是多一條路，不是把fail closed的門檻降低——不支援的intent
    還是要往外丟UnsafeTranslationError，不能被candidate C的存在吞掉。"""
    guard = ProtectedTokenGuard(person_names={"小明"})
    backend = _FakeBackend({
        "小明先生，你的報告出來了。": "先生，你的報告出來矣。",
        "PERSONA先生，你的報告出來了。": "先生，你的報告出來矣。",
    })
    renderer = StructuredMedicalRenderer()

    with pytest.raises(UnsafeTranslationError):
        translate_with_structured_fallback(
            "小明先生，你的報告出來了。", guard, backend,
            structured_intent=None,  # 沒有定義intent, C幫不上忙
            structured_renderer=renderer,
        )
