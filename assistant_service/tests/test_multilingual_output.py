"""
multilingual_output測試：mock掉`_cached_gtts()`本身(不是底層的gtts.gTTS)，
讓「什麼情況該不該產生中英文音檔」這個orchestration邏輯的測試完全不需要
安裝gtts套件——這是特意的設計，跟`response_controller.py`測試用假
TranslationBackend/假TTS router是同樣的原則：邏輯測試不應該被「有沒有裝
某個第三方套件」這種環境因素卡住。真的呼叫gTTS產生音檔的smoke test在檔案
最下面，用importlib skip判斷gtts有沒有裝。
"""

from __future__ import annotations

import importlib.util
from unittest.mock import patch

import pytest

from assistant_service.brain_response import BrainResponse
from assistant_service.multilingual_output import CACHE_DIR, synthesize_multilingual
from assistant_service.response_controller import (
    FALLBACK_SENTENCE_EN,
    FALLBACK_SENTENCE_HAN,
    FALLBACK_SENTENCE_ZH,
    ControllerResult,
)


def _br(**overrides) -> BrainResponse:
    base = dict(
        request_id="r1", intent="general_chat", risk_level="low", language="zh-TW",
        response_zh="我已經幫你倒水了。", response_en="I've poured you some water.",
    )
    base.update(overrides)
    return BrainResponse(**base)


def _fake_cached_gtts(text: str, lang: str) -> str:
    return str(CACHE_DIR / f"fake_{lang}.mp3")


def test_completed_speak_produces_both_zh_and_en_audio():
    controller_result = ControllerResult(request_id="r1", status="completed", action="speak")
    with patch("assistant_service.multilingual_output._cached_gtts", side_effect=_fake_cached_gtts):
        result = synthesize_multilingual(_br(), controller_result)

    assert result.zh_audio_path == str(CACHE_DIR / "fake_zh-TW.mp3")
    assert result.en_audio_path == str(CACHE_DIR / "fake_en.mp3")


def test_completed_speak_returns_zh_en_text_matching_the_audio():
    """2026-09-10新增：前端要依語言模式顯示對應文字(不能永遠只顯示台語
    漢字)，這裡確認回傳的zh_text/en_text就是實際拿去生成音檔的那份文字，
    不是另外重新翻譯或留空。"""
    br = _br()
    controller_result = ControllerResult(request_id="r1", status="completed", action="speak")
    with patch("assistant_service.multilingual_output._cached_gtts", side_effect=_fake_cached_gtts):
        result = synthesize_multilingual(br, controller_result)

    assert result.zh_text == br.response_zh
    assert result.en_text == br.response_en


def test_missing_response_en_skips_english_audio_without_error():
    br = _br(response_en=None)
    controller_result = ControllerResult(request_id="r1", status="completed", action="speak")
    with patch("assistant_service.multilingual_output._cached_gtts", side_effect=_fake_cached_gtts) as mock_gtts:
        result = synthesize_multilingual(br, controller_result)

    assert result.zh_audio_path is not None
    assert result.en_audio_path is None
    mock_gtts.assert_called_once_with(br.response_zh, "zh-TW")  # en完全沒被呼叫過


def test_abstained_status_produces_fixed_fallback_zh_and_en_not_brain_responses_own_text():
    """fail-safe時三語都要有聲音，但中英文用固定翻譯好的
    FALLBACK_SENTENCE_ZH/EN，不是brain_response原本的response_zh/
    response_en——因為進到fail-safe代表大腦原本要講的內容已經被判定不
    安全/跟slots不一致，中英文語音不能講出那份被擋下來的內容，否則等於
    讓台語那邊的安全把關失去意義。"""
    br = _br(response_zh="這是被擋下來、不該被念出來的原始內容", response_en="This blocked content should not be spoken")
    controller_result = ControllerResult(
        request_id="r1", status="abstained", action="call_nurse", hanji_text=FALLBACK_SENTENCE_HAN,
    )
    with patch("assistant_service.multilingual_output._cached_gtts", side_effect=_fake_cached_gtts) as mock_gtts:
        result = synthesize_multilingual(br, controller_result)

    assert result.zh_audio_path is not None
    assert result.en_audio_path is not None
    mock_gtts.assert_any_call(FALLBACK_SENTENCE_ZH, "zh-TW")
    mock_gtts.assert_any_call(FALLBACK_SENTENCE_EN, "en")
    # 絕對不能把brain_response原本被擋下來的文字拿去合成語音
    assert br.response_zh not in [c.args[0] for c in mock_gtts.call_args_list]
    assert br.response_en not in [c.args[0] for c in mock_gtts.call_args_list]
    # 回傳給前端顯示的文字，也要是固定回覆句，不能顯示被擋下來的原文
    assert result.zh_text == FALLBACK_SENTENCE_ZH
    assert result.en_text == FALLBACK_SENTENCE_EN


def test_rejected_status_also_produces_fixed_fallback_audio():
    """status="rejected"(格式驗證失敗)跟"abstained"(翻譯/安全問題)一樣，
    _fail_safe()都會設hanji_text=FALLBACK_SENTENCE_HAN，這裡判斷用
    hanji_text而不是status字串，兩種status都要能觸發固定回覆的三語音檔。"""
    controller_result = ControllerResult(
        request_id="r1", status="rejected", action="call_nurse", hanji_text=FALLBACK_SENTENCE_HAN,
    )
    with patch("assistant_service.multilingual_output._cached_gtts", side_effect=_fake_cached_gtts):
        result = synthesize_multilingual(_br(), controller_result)

    assert result.zh_audio_path is not None
    assert result.en_audio_path is not None


def test_non_speak_action_without_fallback_text_produces_no_multilingual_audio():
    """action不是"speak"、也不是fail-safe固定回覆(hanji_text不是
    FALLBACK_SENTENCE_HAN)的情況——例如大腦自己指定action="call_nurse"
    且沒有翻譯內容——沒有東西可以念，中英文都應該是None。"""
    controller_result = ControllerResult(request_id="r1", status="completed", action="call_nurse")
    with patch("assistant_service.multilingual_output._cached_gtts", side_effect=_fake_cached_gtts) as mock_gtts:
        result = synthesize_multilingual(_br(), controller_result)

    assert result.zh_audio_path is None
    assert result.en_audio_path is None
    mock_gtts.assert_not_called()


_HAS_GTTS = importlib.util.find_spec("gtts") is not None


@pytest.mark.skipif(not _HAS_GTTS, reason="gtts沒有安裝(pip install gtts)")
def test_real_gtts_produces_playable_mp3_files():
    controller_result = ControllerResult(request_id="r1", status="completed", action="speak")
    result = synthesize_multilingual(_br(), controller_result)

    import os

    assert os.path.getsize(result.zh_audio_path) > 0
    assert os.path.getsize(result.en_audio_path) > 0
