"""
病床手勢/物件偵測橋接層：借用yuava22/Interactive-service-robots的
`BedsideGestureDetector`(YOLO姿態+物件偵測，判斷「舉手求助」/「手靠近嘴巴或
杯子=要喝水」/「手靠近骨盆=要上廁所」)，但拿掉他們`run_camera()`裡
`cv2.imshow()`的阻塞式GUI迴圈——這裡要接網頁後端，前端(瀏覽器webcam)自己
顯示畫面，後端只需要逐張frame處理、回傳偵測結果。

跟`voice_io_bridge.py`/`brain_llm.py`一樣的delay-import設計：需要真的裝
`voice_io_event_detector`套件(含ultralytics/opencv-python)+YOLO權重檔
才能用，這個模組本身import不應該因為對方沒裝而整個失敗。

事件->BrainResponse的轉換刻意重用`voice_io_bridge.event_decision_to_
brain_response()`，不重複定義intent/priority對應表：手勢觸發的
WATER_REQUEST/TOILET_REQUEST/HELP_REQUEST語意上跟語音觸發的完全一樣(都是
`intent_rules.py`定義的同3種事件)，只是輸入模態不同，沒理由用不同的風險/
優先權判斷。

**跟對方原始碼的一個差異**：對方`run_camera()`裡呼叫
`decide_event_and_reply(stable_event.lower())`，是把事件代碼(例如
"water_request")直接當作語音辨識文字傳進去——這剛好能動是因為代碼字串本身
包含"water"這個關鍵字，`decide_event_and_reply`用`in`比對才「湊巧」比對
成功，不是真的把代碼轉寫成自然語句。這裡改用明確的代理句子
(`_EVENT_TO_PROXY_TEXT`)，不依賴這種巧合，可讀性也比較好。

**這個模組沒有實機驗證過**：這台開發機沒有YOLO權重檔(對方repo本來就不
commit權重，需要另外下載`yolov8n.pt`/`yolo11n-pose.pt`等放到
`models/`)，也沒有實際接攝影機測試過手勢判斷的準確度——`GestureDetectorSession`
本身能不能正確初始化、`process_frame()`吃真實frame會不會crash，都還沒有
用真實影像驗證過，跟`ros_bridge.py`一樣屬於「照設計寫但沒有實機測試」的
狀態，正式使用前必須先驗證。
"""

from __future__ import annotations

from assistant_service.brain_response import BrainResponse
from assistant_service.voice_io_bridge import event_decision_to_brain_response

# 手勢/物件偵測到的事件代碼 -> 代理句子，餵給decide_event_and_reply()產生
# 跟語音路徑一模一樣的EventDecision(reply_zh/reply_en)，不猜測代碼字串本身
# 是否剛好包含比對用的關鍵字。
_EVENT_TO_PROXY_TEXT = {
    "WATER_REQUEST": "喝水",
    "TOILET_REQUEST": "上廁所",
    "HELP_REQUEST": "求助",
}


def gesture_event_to_brain_response(event: str | None, request_id: str | None = None) -> BrainResponse | None:
    """event是`BedsideGestureDetector.detect_event()`回傳的穩定事件代碼
    (None代表這一幀沒有偵測到穩定手勢，不用產生任何BrainResponse，呼叫方
    應該跳過這一幀，不要送進Response Controller)。"""
    proxy_text = _EVENT_TO_PROXY_TEXT.get(event or "")
    if proxy_text is None:
        return None

    from voice_io_event_detector.intent_rules import decide_event_and_reply

    decision = decide_event_and_reply(proxy_text)
    return event_decision_to_brain_response(decision, request_id=request_id)


class GestureDetectorSession:
    """包一層`BedsideGestureDetector`，讓網頁後端可以逐張frame呼叫、維持
    同一個session的手腕軌跡/事件history(手勢判斷需要看最近幾幀的軌跡，
    不是單張frame就能判斷「舉手」這種動作)。需要真的裝好
    `voice_io_event_detector`套件+YOLO權重檔才能建構，import延遲到
    `__init__`裡才做。"""

    def __init__(self, detection_model=None, pose_model=None):
        from voice_io_event_detector.gesture_detector import BedsideGestureDetector

        self._detector = BedsideGestureDetector(detection_model=detection_model, pose_model=pose_model)

    def process_frame(self, frame):
        """frame: BGR numpy array(cv2慣例，瀏覽器傳來的frame需要先解碼成
        這個格式)。回傳(stable_event, annotated_frame)，annotated_frame是
        畫好姿態/物件框線的畫面，可以直接回傳給前端顯示除錯用。"""
        return self._detector.detect_event(frame)
