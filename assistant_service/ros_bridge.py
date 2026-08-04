"""
brain_tts_bridge.py：在人機互動電腦A上跑的ROS2節點，訂閱 /assistant_response
(std_msgs/String，內容是BrainResponse JSON)，呼叫本機 Response Controller，
發布 /tts/status、完成時 /tts/audio_ready、abstain時額外 /nurse_alert。

**這個檔案沒有在真的ROS環境裡測試過**——這台開發機沒有安裝rclpy，
`import rclpy` 會直接失敗。這不是筆誤或疏忽，是刻意的：`BrainTTSBridge.
__init__` 在偵測到rclpy不存在時會主動raise RuntimeError，而不是靜默降級
成什麼都不做卻讓人以為它在正常運作。正式部署到機器人上之前，這支檔案
必須先在真的ROS2環境裡跑過至少一次端到端測試，確認：
  1. pub/sub的topic名稱/訊息型別跟機器人其他節點對得上
  2. QoS設定(這裡用預設值，實際機器人環境可能需要調整reliability/
     durability，尤其是/nurse_alert這種不能漏掉的訊息)
  3. rclpy的API用法本身正確(這裡是照一般ROS2慣例寫的，沒有實機驗證過
     確切語法)

核心邏輯(優先權佇列、狀態機)已經獨立成 speech_request_queue.py，那部分
不依賴rclpy，已經用pytest驗證過，見 tests/test_speech_request_queue.py。
這個檔案只是把那個邏輯接上ROS的pub/sub，接線本身沒有驗證過。

播放優先權(照建議)：緊急警告100 > 護理通知80 > 一般服務回覆50 > 陪伴聊天10。
高優先權進來時會發布interrupting_lower_priority狀態，但實際停止喇叭輸出
是下游播放節點的責任，不在這個bridge的範圍內。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
except ImportError:
    rclpy = None
    Node = object
    String = None

from assistant_service.brain_response import BrainResponse  # noqa: E402
from assistant_service.response_controller import ResponseController  # noqa: E402
from assistant_service.speech_request_queue import SpeechRequestQueue, SpeechState  # noqa: E402


class BrainTTSBridge(Node):
    def __init__(self, controller: ResponseController):
        if rclpy is None:
            raise RuntimeError(
                "rclpy 沒有安裝, BrainTTSBridge 需要真的ROS2環境才能執行。"
                "這個限制是刻意的——寧可明確報錯, 也不要讓人在沒有ROS的機器上"
                "誤以為執行這段程式碼會有任何實際效果。"
            )
        super().__init__("brain_tts_bridge")
        self.controller = controller
        self.queue = SpeechRequestQueue()

        self._sub = self.create_subscription(String, "/assistant_response", self._on_assistant_response, 10)
        self._status_pub = self.create_publisher(String, "/tts/status", 10)
        self._audio_ready_pub = self.create_publisher(String, "/tts/audio_ready", 10)
        self._nurse_alert_pub = self.create_publisher(String, "/nurse_alert", 10)

    def _on_assistant_response(self, msg) -> None:
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().error(f"/assistant_response 收到非法JSON: {exc}")
            return

        brain_response = BrainResponse.from_dict(data)
        req = self.queue.enqueue(brain_response)

        if self.queue.should_interrupt_current(brain_response.priority):
            self._publish_status(req.request_id, "interrupting_lower_priority")
            # 實際中止喇叭播放是下游播放節點的責任, 這裡只負責通知狀態

        self._publish_status(req.request_id, SpeechState.VALIDATING.value)
        self.queue.set_state(req.request_id, SpeechState.TRANSLATING)
        result = self.controller.handle(brain_response)

        if result.status == "abstained":
            self.queue.mark_finished(req.request_id, SpeechState.ABSTAINED)
            self._publish_status(req.request_id, SpeechState.ABSTAINED.value)
            self._nurse_alert_pub.publish(String(data=json.dumps(
                {"request_id": req.request_id, "reason": result.errors}, ensure_ascii=False,
            )))
            return

        if result.status == "rejected":
            self.queue.mark_finished(req.request_id, SpeechState.FAILED)
            self._publish_status(req.request_id, SpeechState.FAILED.value)
            return

        self._publish_status(req.request_id, SpeechState.SYNTHESIZING.value)
        self.queue.mark_playing(req.request_id)
        self._publish_status(req.request_id, SpeechState.PLAYING.value)
        self._audio_ready_pub.publish(String(data=json.dumps({
            "request_id": req.request_id,
            "audio_path": result.audio_path,
            "translation_method": result.translation_method,
        }, ensure_ascii=False)))
        self.queue.mark_finished(req.request_id, SpeechState.COMPLETED)
        self._publish_status(req.request_id, SpeechState.COMPLETED.value)

    def _publish_status(self, request_id: str, state: str) -> None:
        self._status_pub.publish(String(data=json.dumps(
            {"request_id": request_id, "state": state}, ensure_ascii=False,
        )))


def main() -> None:
    from assistant_service import tts_router
    from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard
    from tw_hokkien_tts_pipeline.structured_renderer import StructuredMedicalRenderer
    from tw_hokkien_tts_pipeline.translate import TaigiLlamaTranslationBackend
    from scripts.eval_translation_safety import DRUG_LEXICON, PERSON_NAMES

    rclpy.init()
    guard = ProtectedTokenGuard(drug_lexicon=DRUG_LEXICON, person_names=PERSON_NAMES)
    backend = TaigiLlamaTranslationBackend()
    controller = ResponseController(
        guard=guard, translation_backend=backend,
        renderer=StructuredMedicalRenderer(), tts_router=tts_router,
    )
    node = BrainTTSBridge(controller)
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
