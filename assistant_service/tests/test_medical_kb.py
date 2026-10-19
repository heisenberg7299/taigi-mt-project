"""medical_kb.py測試：真的建記憶體SQLite跑查詢(輕量、不需要mock)，驗證
FAQ/一般知識庫的關鍵字比對邏輯，以及查無結果時的正確行為。"""

from __future__ import annotations

import threading

from assistant_service.medical_kb import MedicalKnowledgeBase


def test_faq_keyword_match_found():
    kb = MedicalKnowledgeBase()
    results = kb.search("皮膚癢怎麼辦")
    assert any(r.answer.startswith("不要抓") for r in results)


def test_knowledge_table_keyword_match_via_keywords_column():
    """「血壓正常值是多少」這個問題本身沒有直接在knowledge表的question
    欄位裡完整出現(FAQ表裡沒有這筆)，要能透過keywords欄位比對到。"""
    kb = MedicalKnowledgeBase()
    results = kb.search("血壓正常值")
    assert any("收縮壓" in r.answer for r in results)


def test_matches_when_query_reorders_keyword_characters():
    """2026-09-10迴歸測試：真人實測發現「我腹部右下方陣痛會跑很久正常嗎」
    查不到知識庫裡的「右下腹痛」條目(kb:8)，因為「腹部右下方」跟「右下腹」
    用字順序不同，子字串比對(不管哪個方向)都不會命中——這正是使用者質疑
    「RAG防幻覺的意義何在」的具體案例：知識庫明明收錄了這個主題，換個
    自然的問法就完全查不到。字元集合重疊的備援比對修好後，這句話應該要
    查到這筆條目。"""
    kb = MedicalKnowledgeBase()
    results = kb.search("我腹部右下方陣痛會跑很久正常嗎")
    assert any(r.id == "kb:8" for r in results)
    assert any("闌尾炎" in r.answer for r in results)


def test_short_keyword_fuzzy_match_does_not_false_positive_on_unrelated_query():
    """字元集合重疊備援比對只在關鍵字很短(≤6字)時啟用，且要求關鍵字
    「每一個字」都出現在query裡——不是隨便有幾個字重疊就算數，避免無關
    的長句子巧合湊出誤判。"""
    kb = MedicalKnowledgeBase()
    results = kb.search("今天天氣真好，我想出去外面走走透透氣")
    assert results == []


def test_matches_even_when_query_wraps_the_question_in_extra_text():
    """2026-09-10迴歸測試：real-world的query不會是知識庫question的精準
    複製，`multimodal_brain.py`實際組給brain_llm.py的文字長這樣：
    「使用者說的話：血壓正常值是多少」，前面多包了一層前綴——第一版
    search()的LIKE比對方向搞反，這種情況完全查不到，導致RAG實際上路後
    evidence_ids永遠是空的(用真實Ollama請求測出來的，不是憑空猜的)，
    這裡鎖住這個情境不能再回歸。"""
    kb = MedicalKnowledgeBase()
    results = kb.search("使用者說的話：血壓正常值是多少")
    assert any(r.id == "kb:2" for r in results)


def test_no_match_returns_empty_list_not_none_or_exception():
    kb = MedicalKnowledgeBase()
    results = kb.search("今天天氣如何")
    assert results == []


def test_empty_query_returns_empty_list():
    kb = MedicalKnowledgeBase()
    assert kb.search("") == []
    assert kb.search("   ") == []


def test_entry_ids_are_unique_and_prefixed_by_source_table():
    """faq跟knowledge兩張表各自的自增id可能撞號(都從1開始)，entry.id要用
    `faq:`/`kb:`前綴區分，不然evidence_ids可能誤把兩個不同來源的條目
    當成同一筆。"""
    kb = MedicalKnowledgeBase()
    faq_results = kb.search("皮膚癢怎麼辦")
    kb_results = kb.search("忘記吃藥怎麼辦")
    assert all(r.id.startswith("faq:") for r in faq_results)
    assert all(r.id.startswith("kb:") for r in kb_results)


def test_hypertension_stage1_range_matches_current_guideline_not_outdated_one():
    """2026-09-10查證：原本抄自參考範例的「第一級高血壓140-159/90-99」是
    舊版WHO/JNC7標準，現行AHA/ACC 2017指引(2025-08重新確認)跟台灣自
    2022-05起跟進的標準是130-139/80-89。這裡鎖住修正後的數字，避免之後
    不小心又抄回舊數字。"""
    kb = MedicalKnowledgeBase()
    results = kb.search("血壓正常值是多少")
    answer = next(r.answer for r in results if r.id == "kb:2")
    assert "130-139/80-89" in answer
    assert "140-159" not in answer


def test_stroke_golden_window_matches_current_guideline_not_outdated_3_hours():
    """2026-09-10查證：原本的「黃金治療時間3小時」是過時數字，美國中風
    協會現行tPA治療時間窗是4.5小時，寫3小時可能誤導超過3小時但仍在
    4.5小時內的人放棄就醫。"""
    kb = MedicalKnowledgeBase()
    results = kb.search("中風前兆有哪些")
    answer = next(r.answer for r in results if r.id == "kb:5")
    assert "4.5小時" in answer
    assert "3小時" not in answer


def test_severe_hypoglycemia_caveat_present():
    """15-15法則只適用一般低血糖，嚴重低血糖(<55 mg/dL)需要升糖素治療，
    不是靠吃糖——這個但書2026-09-10查證後補上，要確保不會被之後的編輯
    不小心刪掉。"""
    kb = MedicalKnowledgeBase()
    results = kb.search("低血糖怎麼辦")
    answer = next(r.answer for r in results if r.id == "kb:4")
    assert "55" in answer
    assert "升糖素" in answer


def test_search_result_limit_is_respected():
    kb = MedicalKnowledgeBase()
    results = kb.search("怎麼辦", limit=2)
    # FAQ跟knowledge各自最多limit筆，合併起來最多2*limit筆
    assert len(results) <= 4


def test_search_works_when_called_from_a_different_thread_than_the_constructor():
    """2026-09-10迴歸測試：這個物件是brain_llm.py裡的process級singleton，
    Flask開發伺服器會用不同執行緒處理不同request——實測時真的撞到
    `sqlite3.ProgrammingError: SQLite objects created in a thread can only
    be used in that same thread`，整個/api/interact直接500，使用者看起來
    像是「問了沒反應」。這裡故意在建構物件的執行緒之外的另一個執行緒呼叫
    search()，確認不會再拋這個例外(check_same_thread=False + Lock，見
    MedicalKnowledgeBase docstring的修正記錄)。"""
    kb = MedicalKnowledgeBase()  # 建構在目前這個(pytest主)執行緒
    result_holder: dict = {}

    def _search_in_other_thread():
        try:
            result_holder["results"] = kb.search("皮膚癢怎麼辦")
        except Exception as exc:  # noqa: BLE001 - 測試就是要抓任何例外，不能漏放過
            result_holder["error"] = exc

    thread = threading.Thread(target=_search_in_other_thread)
    thread.start()
    thread.join(timeout=5)

    assert "error" not in result_holder, f"跨執行緒查詢拋出例外: {result_holder.get('error')}"
    assert any(r.answer.startswith("不要抓") for r in result_holder["results"])


def test_concurrent_searches_from_multiple_threads_do_not_crash_or_corrupt_results():
    """多個執行緒同時查詢(模擬Flask同時處理多個request)，每個執行緒都要
    拿到正確、不受其他執行緒干擾的結果，且都不能拋例外。"""
    kb = MedicalKnowledgeBase()
    errors: list[Exception] = []
    outputs: list[list] = []
    lock = threading.Lock()

    def _worker():
        try:
            r = kb.search("血壓正常值")
        except Exception as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
            return
        with lock:
            outputs.append(r)

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, f"並行查詢時發生例外: {errors}"
    assert len(outputs) == 8
    for r in outputs:
        assert any("收縮壓" in e.answer for e in r)
