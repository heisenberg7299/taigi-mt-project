"""測試lexicon_schema.py的雙向轉換(扁平dict <-> LexiconTerm結構)在
verified/None語意上的一致性——這是這次升級最容易出錯、也最重要的地方:
「還沒驗證」不能在轉換過程中不小心變成「已驗證但是空的」。"""

from __future__ import annotations

from tw_hokkien_tts_pipeline.lexicon_schema import (
    LexiconEntry,
    LexiconTerm,
    ReadingType,
    RiskLevel,
    from_flat_dict,
    primary_tailo,
    to_flat_dict,
)


def test_from_flat_dict_marks_verified_only_when_reading_present():
    flat = {"盤尼西林": "puân-nî-se-lîm", "胰島素": None}
    terms = from_flat_dict(flat, domain="medical", risk=RiskLevel.CRITICAL)

    assert terms["盤尼西林"].candidates[0].verified is True
    assert terms["盤尼西林"].candidates[0].tailo == "puân-nî-se-lîm"
    assert terms["胰島素"].candidates[0].verified is False
    assert terms["胰島素"].candidates[0].tailo is None

    # domain/risk要正確帶入每個候選
    assert terms["盤尼西林"].candidates[0].domain == "medical"
    assert terms["盤尼西林"].candidates[0].risk == RiskLevel.CRITICAL


def test_round_trip_flat_to_structured_to_flat_is_lossless_for_values():
    flat = {"盤尼西林": "puân-nî-se-lîm", "胰島素": None, "普拿疼": "phóo-ná-thàng"}
    terms = from_flat_dict(flat)
    restored = to_flat_dict(terms)
    assert restored == flat


def test_primary_tailo_prefers_first_verified_candidate():
    term = LexiconTerm(
        hanji="呼吸器",
        candidates=[
            LexiconEntry(tailo=None, verified=False, source="manual_guess"),
            LexiconEntry(tailo="honn-khip-khì", verified=True, source="moe_dict"),
        ],
    )
    assert primary_tailo(term) == "honn-khip-khì"


def test_primary_tailo_never_returns_unverified_reading():
    """就算有候選讀音, 只要沒verified就不能被當成「有讀音」回傳——
    寧可讓呼叫端知道缺讀音, 也不要塞一個沒驗證過的猜測進生產環境。"""
    term = LexiconTerm(
        hanji="某藥",
        candidates=[LexiconEntry(tailo="猜的讀音", verified=False, source="unverified_guess")],
    )
    assert primary_tailo(term) is None


def test_primary_tailo_no_candidates_returns_none():
    term = LexiconTerm(hanji="某詞", candidates=[])
    assert primary_tailo(term) is None


def test_reading_type_and_domain_defaults():
    entry = LexiconEntry(tailo="test")
    assert entry.reading_type == ReadingType.UNKNOWN
    assert entry.domain == "general"
    assert entry.risk == RiskLevel.LOW
    assert entry.verified is False


def test_verified_candidates_filters_out_none_tailo_even_if_flagged_verified():
    """防呆: 即使有人不小心把verified=True但tailo是None的錯誤資料放進去,
    verified_candidates()也不該把它當成可用候選(避免下游拿到None當讀音)。"""
    term = LexiconTerm(
        hanji="某詞",
        candidates=[LexiconEntry(tailo=None, verified=True, source="bad_data")],
    )
    assert term.verified_candidates() == []
    assert primary_tailo(term) is None
