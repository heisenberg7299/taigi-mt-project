"""SpeechRequestQueue測試——這部分不依賴rclpy，可以完整驗證，跟
ros_bridge.py本身(需要真的ROS環境，這裡沒有裝)分開。"""

from __future__ import annotations

from dataclasses import dataclass

from assistant_service.speech_request_queue import (
    PRIORITY_COMPANION_CHAT,
    PRIORITY_EMERGENCY,
    PRIORITY_NURSE_ALERT,
    SpeechRequestQueue,
    SpeechState,
)


@dataclass
class _FakeBrainResponse:
    request_id: str
    priority: int


def test_higher_priority_popped_first_regardless_of_enqueue_order():
    q = SpeechRequestQueue()
    q.enqueue(_FakeBrainResponse("chat", PRIORITY_COMPANION_CHAT))
    q.enqueue(_FakeBrainResponse("emergency", PRIORITY_EMERGENCY))
    q.enqueue(_FakeBrainResponse("nurse", PRIORITY_NURSE_ALERT))

    assert q.pop_next().request_id == "emergency"
    assert q.pop_next().request_id == "nurse"
    assert q.pop_next().request_id == "chat"
    assert q.pop_next() is None


def test_same_priority_is_first_in_first_out():
    q = SpeechRequestQueue()
    q.enqueue(_FakeBrainResponse("a", 50))
    q.enqueue(_FakeBrainResponse("b", 50))

    assert q.pop_next().request_id == "a"
    assert q.pop_next().request_id == "b"


def test_should_interrupt_current_when_new_request_has_higher_priority():
    q = SpeechRequestQueue()
    chat = q.enqueue(_FakeBrainResponse("chat", PRIORITY_COMPANION_CHAT))
    q.mark_playing(chat.request_id)

    assert q.should_interrupt_current(PRIORITY_EMERGENCY) is True
    assert q.should_interrupt_current(PRIORITY_COMPANION_CHAT) is False  # 同優先權不算"更高"，不中止


def test_should_not_interrupt_when_nothing_playing():
    q = SpeechRequestQueue()
    assert q.should_interrupt_current(PRIORITY_EMERGENCY) is False


def test_state_transitions_and_currently_playing_tracking():
    q = SpeechRequestQueue()
    q.enqueue(_FakeBrainResponse("r1", 50))
    assert q.get_state("r1") == SpeechState.QUEUED

    q.mark_playing("r1")
    assert q.get_state("r1") == SpeechState.PLAYING
    assert q.currently_playing == "r1"

    q.mark_finished("r1", SpeechState.COMPLETED)
    assert q.get_state("r1") == SpeechState.COMPLETED
    assert q.currently_playing is None


def test_abstained_requests_also_clear_currently_playing():
    q = SpeechRequestQueue()
    q.enqueue(_FakeBrainResponse("r1", 80))
    q.mark_playing("r1")
    q.mark_finished("r1", SpeechState.ABSTAINED)

    assert q.get_state("r1") == SpeechState.ABSTAINED
    assert q.currently_playing is None
