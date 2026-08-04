"""
播放優先權佇列 + 狀態機，是 ros_bridge.py 的核心邏輯，刻意獨立成不依賴
rclpy的模組——這台開發機沒有安裝ROS，沒辦法讓ros_bridge.py本身跑過
一次，但佇列/優先權/狀態轉換這些邏輯是純Python，可以先用pytest驗證過，
之後接上真的ROS環境時只要確認pub/sub本身接得上，核心邏輯不用再重新驗證。

建議優先權(照ROS bridge設計)：
  緊急警告 100 > 護理通知 80 > 一般服務回覆 50 > 陪伴聊天 10
高優先權可以中止低優先權的播放，避免機器人還在閒聊時錯過緊急提示。
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from enum import Enum
from typing import Any

PRIORITY_EMERGENCY = 100
PRIORITY_NURSE_ALERT = 80
PRIORITY_GENERAL_SERVICE = 50
PRIORITY_COMPANION_CHAT = 10


class SpeechState(str, Enum):
    QUEUED = "queued"
    VALIDATING = "validating"
    TRANSLATING = "translating"
    SYNTHESIZING = "synthesizing"
    PLAYING = "playing"
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    FAILED = "failed"


@dataclass
class SpeechRequest:
    request_id: str
    priority: int
    brain_response: Any  # assistant_service.brain_response.BrainResponse, 用Any避免循環import
    state: SpeechState = SpeechState.QUEUED


class SpeechRequestQueue:
    """優先權佇列：數字越大優先權越高，同優先權先進先出。"""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, str]] = []
        self._counter = itertools.count()
        self._requests: dict[str, SpeechRequest] = {}
        self._currently_playing: str | None = None

    def enqueue(self, brain_response) -> SpeechRequest:
        req = SpeechRequest(
            request_id=brain_response.request_id, priority=brain_response.priority, brain_response=brain_response,
        )
        self._requests[req.request_id] = req
        heapq.heappush(self._heap, (-req.priority, next(self._counter), req.request_id))
        return req

    def pop_next(self) -> SpeechRequest | None:
        while self._heap:
            _, _, rid = heapq.heappop(self._heap)
            req = self._requests.get(rid)
            if req and req.state == SpeechState.QUEUED:
                return req
        return None

    def should_interrupt_current(self, new_priority: int) -> bool:
        """目前有東西在播放、且新request優先權嚴格更高時回傳True。真正
        停止喇叭輸出是下游播放節點的責任，這個方法只負責判斷「該不該」，
        不負責「怎麼停」。"""
        if self._currently_playing is None:
            return False
        current = self._requests.get(self._currently_playing)
        if current is None:
            return False
        return new_priority > current.priority

    def mark_playing(self, request_id: str) -> None:
        self.set_state(request_id, SpeechState.PLAYING)
        self._currently_playing = request_id

    def mark_finished(self, request_id: str, final_state: SpeechState) -> None:
        self.set_state(request_id, final_state)
        if self._currently_playing == request_id:
            self._currently_playing = None

    def set_state(self, request_id: str, state: SpeechState) -> None:
        if request_id in self._requests:
            self._requests[request_id].state = state

    def get_state(self, request_id: str) -> SpeechState | None:
        req = self._requests.get(request_id)
        return req.state if req else None

    @property
    def currently_playing(self) -> str | None:
        return self._currently_playing
