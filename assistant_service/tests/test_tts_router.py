"""
tts_router.py測試：這個模組先前完全沒有測試覆蓋(2026-09-10查證時發現)，
雖然`test_response_controller.py`/`test_voice_io_bridge.py`有提到
"tts_router"這個字，但用的都是`_FakeTTSRouter`測試替身，從來沒有真的
測過`load_approved_sentences()`/`is_approved_common_sentence()`/
`route_and_synthesize()`這幾個函式本身的邏輯。

mock掉`_call_backend()`(對127.0.0.1:5010/5011的網路呼叫)，讓測試不需要
真的啟動neurlang/meralion backend process就能跑；用`monkeypatch`把
`CACHE_DIR`/`APPROVED_SENTENCES_PATH`導到`tmp_path`，避免測試寫真的快取
檔案汙染repo裡的`cache/`目錄。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from assistant_service import tts_router

_REAL_APPROVED_SENTENCES_PATH = Path(__file__).resolve().parent.parent / "cache" / "approved_sentences.json"


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """每個測試都用獨立的暫存目錄當快取/審核清單路徑，測試之間不共用
    狀態、也不會動到repo裡真正的cache/audio跟approved_sentences.json。"""
    cache_dir = tmp_path / "audio"
    cache_dir.mkdir()
    approved_path = tmp_path / "approved_sentences.json"
    monkeypatch.setattr(tts_router, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(tts_router, "APPROVED_SENTENCES_PATH", approved_path)
    return cache_dir, approved_path


def test_load_approved_sentences_returns_empty_set_when_file_missing():
    assert tts_router.load_approved_sentences() == set()


def test_load_approved_sentences_reads_real_repo_file_and_contains_expected_entries():
    """2026-09-10前這份清單是空的，代表MERaLiON路徑從來沒被觸發過——這裡
    直接讀repo裡真正的`cache/approved_sentences.json`(不用isolated fixture
    導到的暫存路徑)，確認實際補上的4句常用句都在，這個路由機制才算真的
    生效，不是空機制。"""
    with open(_REAL_APPROVED_SENTENCES_PATH, encoding="utf-8") as f:
        entries = set(json.load(f))
    assert len(entries) >= 4
    assert "這个問題我無法度確定，我共你通知護理師。" in entries


def test_is_approved_common_sentence_true_for_listed_sentence(_isolated_cache):
    _cache_dir, approved_path = _isolated_cache
    approved_path.write_text(json.dumps(["固定句A"], ensure_ascii=False), encoding="utf-8")
    assert tts_router.is_approved_common_sentence("固定句A") is True
    assert tts_router.is_approved_common_sentence("沒列出的句子") is False


def test_route_and_synthesize_uses_meralion_for_approved_sentence(_isolated_cache):
    _cache_dir, approved_path = _isolated_cache
    approved_path.write_text(json.dumps(["固定句A"], ensure_ascii=False), encoding="utf-8")

    with patch.object(tts_router, "_call_backend", return_value=b"fake-wav-bytes") as mock_call:
        result = tts_router.route_and_synthesize("固定句A")

    mock_call.assert_called_once_with("固定句A", "meralion")
    assert result.backend == "meralion_fresh_cached"
    assert result.from_cache is False
    assert result.audio_path.read_bytes() == b"fake-wav-bytes"


def test_route_and_synthesize_uses_neurlang_for_unapproved_sentence(_isolated_cache):
    with patch.object(tts_router, "_call_backend", return_value=b"fake-wav-bytes") as mock_call:
        result = tts_router.route_and_synthesize("隨便一句動態生成的話")

    mock_call.assert_called_once_with("隨便一句動態生成的話", "neurlang")
    assert result.backend == "neurlang_realtime"
    assert result.from_cache is False


def test_force_meralion_env_var_overrides_default_routing_for_any_sentence(_isolated_cache, monkeypatch):
    """2026-10-19新增：使用者在了解硬碟/RAM/速度代價後，明確要求台語輸出
    全部改用MERaLiON，不受approved_sentences清單限制。預設(環境變數沒設)
    不受影響，見下一個測試。"""
    monkeypatch.setenv("ASSISTANT_SERVICE_FORCE_MERALION", "1")

    with patch.object(tts_router, "_call_backend", return_value=b"fake-wav-bytes") as mock_call:
        result = tts_router.route_and_synthesize("完全沒在approved清單裡的隨便一句話")

    mock_call.assert_called_once_with("完全沒在approved清單裡的隨便一句話", "meralion")
    assert result.backend == "meralion_fresh_cached"


def test_force_meralion_env_var_defaults_to_off(_isolated_cache, monkeypatch):
    """沒設這個環境變數(或值不是"1")時，行為要跟這個選項加入之前完全
    一樣——不想承擔MERaLiON效能代價的人不該被意外影響。"""
    monkeypatch.delenv("ASSISTANT_SERVICE_FORCE_MERALION", raising=False)
    with patch.object(tts_router, "_call_backend", return_value=b"fake-wav-bytes") as mock_call:
        result = tts_router.route_and_synthesize("預設行為應該是neurlang")
    mock_call.assert_called_once_with("預設行為應該是neurlang", "neurlang")
    assert result.backend == "neurlang_realtime"


def test_route_and_synthesize_hits_cache_on_second_call_without_calling_backend_again(_isolated_cache):
    """第二次問同一句話(不管approved與否)應該直接命中快取，不用重新呼叫
    任何TTS backend——見tts_router.py docstring路由規則第1條。這句話不在
    approved清單裡、也沒開FORCE_MERALION，所以兩次都該是neurlang，快取
    命中的標籤也該誠實反映這一點(不是像修正前那樣不管哪個backend生成的
    都寫死"meralion_cached")。"""
    with patch.object(tts_router, "_call_backend", return_value=b"fake-wav-bytes") as mock_call:
        first = tts_router.route_and_synthesize("重複問的話")
        second = tts_router.route_and_synthesize("重複問的話")

    mock_call.assert_called_once()  # 只呼叫過一次，第二次直接命中快取
    assert first.audio_path == second.audio_path
    assert second.from_cache is True
    assert second.backend == "neurlang_cached"


def test_switching_to_force_meralion_does_not_reuse_stale_neurlang_cache(_isolated_cache, monkeypatch):
    """2026-10-19迴歸測試：這是使用者實際回報「網頁版聲音聽起來跟比較
    工具不一樣」的根因。情境：某句話先在FORCE_MERALION關閉的狀態下被
    neurlang生成並快取，之後才開啟FORCE_MERALION——修正前會直接命中
    那個舊的neurlang快取(快取key不分backend)，使用者以為自己聽到
    MERaLiON的聲音，實際上聽到的是舊的neurlang聲音。"""
    monkeypatch.delenv("ASSISTANT_SERVICE_FORCE_MERALION", raising=False)
    with patch.object(tts_router, "_call_backend", return_value=b"neurlang-version") as mock_call:
        before = tts_router.route_and_synthesize("同一句話之後會切換引擎")
    assert before.backend == "neurlang_realtime"
    mock_call.assert_called_once_with("同一句話之後會切換引擎", "neurlang")

    monkeypatch.setenv("ASSISTANT_SERVICE_FORCE_MERALION", "1")
    with patch.object(tts_router, "_call_backend", return_value=b"meralion-version") as mock_call:
        after = tts_router.route_and_synthesize("同一句話之後會切換引擎")

    mock_call.assert_called_once_with("同一句話之後會切換引擎", "meralion")  # 真的重新呼叫了MERaLiON，不是沿用舊快取
    assert after.backend == "meralion_fresh_cached"
    assert after.from_cache is False
    assert after.audio_path != before.audio_path  # 兩個backend各自存成不同的快取檔案
    assert after.audio_path.read_bytes() == b"meralion-version"
    assert before.audio_path.read_bytes() == b"neurlang-version"  # 舊的neurlang快取沒有被覆蓋掉，仍然存在


def test_cache_key_is_stable_and_content_addressed():
    assert tts_router._cache_key("neurlang", "同一句話") == tts_router._cache_key("neurlang", "同一句話")
    assert tts_router._cache_key("neurlang", "句子A") != tts_router._cache_key("neurlang", "句子B")
    assert tts_router._cache_key("neurlang", "同一句話") != tts_router._cache_key("meralion", "同一句話")
