"""
多個同類 Protected Token 的完整性測試：驗證每個pipeline階段都不會發生
遺失、重複、改序、或類別互換。

背景：舊格式是 __DRUG_0__ 這種底線+數字, 改成 DRUGA/PERSONB/DOSEC 這種
純大寫字母格式後(見 protected_tokens.py 的說明), 有兩個新的風險是舊格式
沒有的:
  1. 同類字母超過26個時, "DRUGA" 會是 "DRUGAA" 的前綴字串
  2. 中文原句常見「藥名+劑量」緊接在一起沒有分隔字元 (例如「盤尼西林120毫克」),
     遮罩後兩個佔位符會黏在一起變成 "DRUGADOSEA", 如果還原時對每個佔位符
     各自處理(不管是簡單str.replace()或加邊界正則)都會因為鄰居也是A-Z
     字母而出錯——這個案例在開發過程中實際測到過, 不是純假設。
這個檔案的測試就是針對這兩種情況寫的。
"""

from __future__ import annotations

from pathlib import Path

from tw_hokkien_tts_pipeline.config import PipelineConfig
from tw_hokkien_tts_pipeline.pipeline import Pipeline
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard, index_to_letter_suffix


def test_index_to_letter_suffix_no_wraparound_collision():
    # 0-25 應該是 A-Z
    assert [index_to_letter_suffix(i) for i in range(26)] == [chr(ord("A") + i) for i in range(26)]
    # 第27個(index=26)不能折返變回 "A"(那樣會跟第1個的映射衝突), 要進位成 "AA"
    assert index_to_letter_suffix(26) == "AA"
    assert index_to_letter_suffix(27) == "AB"
    # 所有輸出兩兩不重複 (100個內)
    suffixes = [index_to_letter_suffix(i) for i in range(100)]
    assert len(suffixes) == len(set(suffixes))


def test_multiple_same_kind_tokens_get_distinct_placeholders():
    guard = ProtectedTokenGuard(
        drug_lexicon={
            "盤尼西林": "puân-nî-se-lîm",
            "普拿疼": "phóo-ná-thàng",
        },
        person_names={"王先生", "陳小姐"},
    )
    text = "請通知王先生跟陳小姐，盤尼西林跟普拿疼都要準時服用200毫克跟50毫克。"
    mask_result = guard.mask(text)

    by_kind: dict[str, list[str]] = {}
    for span in mask_result.spans:
        by_kind.setdefault(span.kind, []).append(span.placeholder)

    # 同一類別的多個實體要依序拿到不同字母, 不能共用、不能覆蓋
    assert by_kind["DRUG"] == ["DRUGA", "DRUGB"]
    assert by_kind["PERSON"] == ["PERSONA", "PERSONB"]
    assert by_kind["DOSE"] == ["DOSEA", "DOSEB"]

    # 佔位符彼此不重複 (無遺失也無重複配對)
    all_placeholders = [s.placeholder for s in mask_result.spans]
    assert len(all_placeholders) == len(set(all_placeholders))

    # 原文的敏感詞應該從masked_text完全消失, 不留殘餘
    for span in mask_result.spans:
        assert span.original not in mask_result.masked_text


def test_multiple_same_kind_tokens_round_trip_no_loss_reorder_or_swap():
    guard = ProtectedTokenGuard(
        drug_lexicon={
            "盤尼西林": "puân-nî-se-lîm",
            "普拿疼": "phóo-ná-thàng",
        },
        person_names={"王先生", "陳小姐"},
    )
    text = "請通知王先生跟陳小姐，盤尼西林跟普拿疼都要準時服用200毫克跟50毫克。"
    mask_result = guard.mask(text)

    # 還原成中文應該逐字完全等於原文 (驗證沒有遺失/重複/改序/類型互換)
    restored_hanji = guard.unmask_text(mask_result.masked_text, mask_result.spans)
    assert restored_hanji == text

    # 還原成台羅: 兩個藥名都有詞庫讀音，且相對順序要跟原文一致 (沒有改序)
    restored_tailo = guard.unmask_to_tailo(mask_result.masked_text, mask_result.spans)
    assert "puân-nî-se-lîm" in restored_tailo
    assert "phóo-ná-thàng" in restored_tailo
    assert restored_tailo.index("puân-nî-se-lîm") < restored_tailo.index("phóo-ná-thàng")
    # 人名/劑量沒有台羅詞庫，應該fallback回原文，不能憑空消失或被其他類別的值取代
    assert "王先生" in restored_tailo
    assert "陳小姐" in restored_tailo
    assert restored_tailo.index("王先生") < restored_tailo.index("陳小姐")
    assert "200毫克" in restored_tailo
    assert "50毫克" in restored_tailo
    assert restored_tailo.index("200毫克") < restored_tailo.index("50毫克")


def test_adjacent_placeholders_without_delimiter_do_not_corrupt_each_other():
    """藥名+劑量緊接在一起沒有分隔字元(中文常見語序)時, 遮罩後兩個佔位符
    會黏在一起(DRUGADOSEA)。這是實際測到過的bug case, 不是假設情境。"""
    guard = ProtectedTokenGuard(drug_lexicon={"盤尼西林": "puân-nî-se-lîm"})
    text = "服用盤尼西林120毫克。"
    mask_result = guard.mask(text)

    # 確認兩個佔位符確實黏在一起、中間沒有任何分隔字元
    assert "DRUGADOSEA" in mask_result.masked_text

    restored = guard.unmask_text(mask_result.masked_text, mask_result.spans)
    assert restored == text

    restored_tailo = guard.unmask_to_tailo(mask_result.masked_text, mask_result.spans)
    assert "puân-nî-se-lîm" in restored_tailo
    assert "120毫克" in restored_tailo
    # 藥名台羅要在劑量前面(順序不能錯亂), 且兩者不能黏成一個無法辨識的字串
    assert restored_tailo.index("puân-nî-se-lîm") < restored_tailo.index("120毫克")


def test_pipeline_end_to_end_multiple_protected_tokens(tmp_path: Path):
    """完整跑一次pipeline(mock翻譯/斷詞 + neurlang真實TTS層邏輯共用的
    hanji_text組裝), 確認多個同類保護詞在真正的pipeline.run()裡也不會
    遺失、重複、改序或類別互換, 不是只有 ProtectedTokenGuard 單獨測試過。"""
    config = PipelineConfig(output_dir=tmp_path)
    pipeline = Pipeline(
        config=config,
        drug_lexicon={"盤尼西林": "puân-nî-se-lîm", "普拿疼": "phóo-ná-thàng"},
    )
    result = pipeline.run("請記得服用盤尼西林跟普拿疼。", out_filename="test_multi.wav")

    # hanji_text (給neurlang用) 應該兩個藥名都還原、沒有佔位符殘留
    assert "盤尼西林" in result.hanji_text
    assert "普拿疼" in result.hanji_text
    assert "DRUGA" not in result.hanji_text
    assert "DRUGB" not in result.hanji_text
    assert result.hanji_text.index("盤尼西林") < result.hanji_text.index("普拿疼")

    # romanization.text (給吃台羅的backend用) 應該兩個藥名的台羅都出現
    assert "puân-nî-se-lîm" in result.romanization.text
    assert "phóo-ná-thàng" in result.romanization.text
