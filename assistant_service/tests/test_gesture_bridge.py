"""
gesture_bridge測試。`gesture_event_to_brain_response()`的事件->
BrainResponse轉換邏輯只依賴`voice_io_event_detector.intent_rules`(零重
依賴的純Python)，套件沒裝時整組skip；`GestureDetectorSession`本身需要
YOLO權重檔+ultralytics，這裡沒有實機測試(見gesture_bridge.py docstring)。
"""

from __future__ import annotations

import importlib.util

import pytest

_HAS_VOICE_IO_PKG = importlib.util.find_spec("voice_io_event_detector") is not None

pytestmark = pytest.mark.skipif(
    not _HAS_VOICE_IO_PKG,
    reason="需要先pip install -e path/to/Interactive-service-robots(voice_io_event_detector套件)",
)


def test_water_gesture_maps_to_same_intent_as_voice_path():
    from assistant_service.gesture_bridge import gesture_event_to_brain_response

    br = gesture_event_to_brain_response("WATER_REQUEST", request_id="gesture_1")

    assert br is not None
    assert br.request_id == "gesture_1"
    assert br.intent == "water_request"
    assert br.risk_level == "low"
    assert br.is_valid


def test_unknown_or_none_event_returns_none():
    from assistant_service.gesture_bridge import gesture_event_to_brain_response

    assert gesture_event_to_brain_response(None) is None
    assert gesture_event_to_brain_response("SOME_UNKNOWN_EVENT") is None
