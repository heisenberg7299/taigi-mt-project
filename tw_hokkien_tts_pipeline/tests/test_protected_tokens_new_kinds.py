"""
測試2026-08-17新增的四個Protected Token類別: TITLE(醫療職稱)、DEVICE
(醫療器材)、ROOM(病房/床號/診間)、TIME(時刻)。

背景: 原本只有DRUG/PERSON/DOSE三類, 涵蓋不了「呼吸治療師被吃掉」「病房號
講錯」這類同樣可能造成醫療風險的實體, 見protected_tokens.py模組docstring
的完整分析。這裡的測試重點:
  1. 四個新類別各自的偵測規則(詞庫比對 or 正則)是否正確
  2. 新類別跟舊類別混在同一句時, 佔位符/還原邏輯依然正確(不會互相干擾)
  3. kind名稱刻意不用底線(ROOM不是ROOM_ID, TITLE不是MEDICAL_TITLE)這個
     設計決策有沒有被遵守——佔位符必須是純大寫英文字母, 見模組docstring
"""

from __future__ import annotations

import re

from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard, _KIND_NAMES


def test_kind_names_are_pure_letters_no_underscore():
    """佔位符格式的核心限制: kind名稱本身不能含底線/數字, 不然拼出來的
    佔位符(kind+字母尾碼)就不是純大寫英文單字了, 見模組docstring說明。"""
    for kind in _KIND_NAMES:
        assert re.fullmatch(r"[A-Z]+", kind), f"{kind!r} 不是純大寫英文字母, 違反佔位符格式限制"


def test_medical_title_detected_and_masked():
    guard = ProtectedTokenGuard(medical_title_lexicon={"呼吸治療師": None, "護理師": "hōo-lí-su"})
    result = guard.mask("請呼吸治療師跟護理師一起過來。")
    kinds = [s.kind for s in result.spans]
    assert kinds == ["TITLE", "TITLE"]
    assert "呼吸治療師" not in result.masked_text
    assert "護理師" not in result.masked_text
    assert re.fullmatch(r"[A-Z]+", result.spans[0].placeholder)


def test_device_detected_and_masked():
    guard = ProtectedTokenGuard(device_lexicon={"呼吸器": None, "輪椅": "lián-í"})
    result = guard.mask("幫忙把呼吸器接上, 再推輪椅過來。")
    kinds = [s.kind for s in result.spans]
    assert kinds == ["DEVICE", "DEVICE"]
    assert result.spans[1].tailo == "lián-í"


def test_room_id_regex_variants():
    guard = ProtectedTokenGuard()
    cases = ["603號病房", "5床", "A3病房", "302室", "9號診間"]
    for text in cases:
        result = guard.mask(f"病人在{text}。")
        assert len(result.spans) == 1, f"{text!r} 應該被偵測為一個ROOM span"
        assert result.spans[0].kind == "ROOM"
        assert result.spans[0].original == text


def test_time_regex_variants():
    guard = ProtectedTokenGuard()
    cases = ["早上八點半", "下午三點整", "九點三十分", "晚上十點", "14:30"]
    for text in cases:
        result = guard.mask(f"約{text}量血壓。")
        assert len(result.spans) == 1, f"{text!r} 應該被偵測為一個TIME span"
        assert result.spans[0].kind == "TIME"
        assert result.spans[0].original == text


def test_room_and_dose_regex_do_not_cross_match():
    """病房號("603號病房")跟劑量("120毫克")的正則不能互相誤吃對方——
    確認兩個規則分開跑之後, 病房號沒有被DOSE正則裡的\\d+誤判成劑量開頭。"""
    guard = ProtectedTokenGuard()
    result = guard.mask("在603號病房服用120毫克。")
    by_kind = {s.kind: s.original for s in result.spans}
    assert by_kind["ROOM"] == "603號病房"
    assert by_kind["DOSE"] == "120毫克"


def test_all_seven_kinds_together_round_trip():
    guard = ProtectedTokenGuard(
        drug_lexicon={"盤尼西林": "puân-nî-se-lîm"},
        person_names={"王小明"},
        medical_title_lexicon={"呼吸治療師": None},
        device_lexicon={"呼吸器": None},
    )
    text = "請呼吸治療師幫王小明在603號病房用呼吸器，早上八點半服用盤尼西林120毫克。"
    result = guard.mask(text)

    kinds_present = {s.kind for s in result.spans}
    assert kinds_present == {"TITLE", "PERSON", "ROOM", "DEVICE", "TIME", "DRUG", "DOSE"}

    # 每個佔位符在masked_text裡都是獨立、可辨識的token, 不會互相污染
    for span in result.spans:
        assert span.placeholder in result.masked_text
        assert span.original not in result.masked_text

    # 還原成中文要逐字等於原文
    restored = guard.unmask_text(result.masked_text, result.spans)
    assert restored == text

    # coverage只看DRUG/TITLE/DEVICE三個詞庫類別: 1個DRUG有台羅、TITLE跟
    # DEVICE都沒有台羅(tailo=None), 所以是1/3
    assert abs(guard.coverage(result.spans) - (1 / 3)) < 1e-9


def test_coverage_ignores_room_and_time_and_dose():
    """ROOM/TIME/DOSE是正則偵測、非詞庫比對類別, 不該影響coverage()——
    即使句子裡完全沒有DRUG/TITLE/DEVICE, coverage也不該被這些類別拉低。"""
    guard = ProtectedTokenGuard()
    result = guard.mask("在603號病房，早上八點量血壓，服用120毫克藥物。")
    assert guard.coverage(result.spans) == 1.0
