"""
MediaPipe Pose視覺辨識：鏡頭姿態偵測的第二種backend，跟`gesture_bridge.py`
(沿用yuava22官方套件的YOLO-pose `BedsideGestureDetector`)並存，不是取代。
兩者都產生`VisionSignal`(事件代碼+人類可讀描述)這個統一形狀，一起餵進
`multimodal_brain.py`，由LLM大腦判斷最終回應——語音走的規則式快速路徑
是「文字關鍵字比對」，但視覺訊號(尤其是MediaPipe這種只給姿態關鍵點、沒有
語意的原始資料)沒有等價的規則式判斷可以做到跟語音一樣的可靠度，所以視覺
訊號一律送進LLM分類，不直接查表決定最終回覆文字。

**用MediaPipe新版Tasks API(`PoseLandmarker`)，不是舊版`mp.solutions.pose`**
——這次裝的`mediapipe==1.0.0`已經完全移除`mp.solutions`，只剩Tasks API可用，
需要另外下載pose landmarker模型檔(`.task`)，這裡预設抓lite版本(~5.8MB)，
放在`assistant_service/models/`(已經在`.gitignore`的`models/`規則涵蓋，
不進版控，跟YOLO權重的處理方式一致)。

**跟`gesture_bridge.py`(YOLO-pose)的偵測邏輯差異**：YOLO版本的「求助」判斷
是看最近幾幀手腕有沒有明顯**橫向擺動**(揮手動作)；這裡的MediaPipe版本
簡化成「手腕目前的y座標高於肩膀」(單純舉手的姿勢，不要求擺動)——這是刻意
的簡化，不是想模仿對方邏輯做出一樣的判斷準則，兩種backend的判斷標準本來
就不需要一致，因為最終的判斷責任交給LLM(看到描述文字後自己判斷是不是真的
在求助)，這裡的規則只是產生「觀察到什麼」的粗略描述，不是最終決策。

**這個模組沒有實機測試過**：只驗證過在靜態測試圖片上跑起來不crash、輸出
形狀正確，沒有用真人在鏡頭前做實際手勢動作驗證過準確度。

## 修正記錄(2026-09-10)：距離門檻原本是寫死的像素值，不會隨解析度縮放

真人測試回報「鏡頭開著，但做動作完全沒反應」。追查後發現`near_mouth`/
`near_pelvis`原本直接用寫死的像素距離(70px/90px)判斷，但landmark座標
是`landmarks[idx].x/y * w/h`算出來的實際像素位置——瀏覽器`getUserMedia`
預設常給到720p以上的畫面(例如1280x720)，這個解析度下手腕到嘴巴/骨盆的
實際像素距離即使手真的碰到臉，通常也有一兩百像素以上(手掌本身的大小、
手腕landmark是手腕不是指尖)，遠超過70/90px這個門檻，等於在常見解析度
下這兩個手勢幾乎不可能觸發。

`hands_raised`不受影響，因為它比較的是y座標大小關係(舉手過肩)，不是絕對
距離。

修正方式(第一版)：改用「肩寬」當比例基準。

## 修正記錄(2026-09-10 第二版)：真人再次實測仍然沒反應，改參考yuava22套件裡的範例實作

第一版修好後真人測試仍回報「鏡頭開著但動作沒反應」。去看yuava22/
Interactive-service-robots這個repo自己的範例(`examples/nursing_robot_demo/
mediapipe_pose_gesture.py`)怎麼做，發現關鍵差異：**那份參考實作完全沒有
把landmark座標乘上畫面寬高轉成像素**，全程直接用MediaPipe原生回傳的
normalized座標(0-1區間)算距離、門檻也是normalized空間的固定值(例如
0.12/0.14/0.18)——因為normalized座標本身就已經跟解析度無關，不需要
再另外用肩寬換算比例。第一版的「肩寬比例」做法概念上沒錯，但捨近求遠、
多繞了一手轉換，這次直接改成參考實作的方式：全部在normalized空間判斷。

**注意**：那份參考實作用的是MediaPipe舊版`mp.solutions.pose` API，這次
環境裝的`mediapipe==1.0.0`已經拿掉`mp.solutions`(見上面`hasattr(mp,
'solutions')`回傳False的確認)，沒辦法直接搬過去，這裡是把它的**座標系統
選擇+手肘角度輔助判斷**這兩個做法，改寫成用新版Tasks API(`PoseLandmarker`)
也能用的等價邏輯，不是逐行照抄。

另外參考實作還多了：
  - **手肘彎曲角度**當輔助訊號(不是只看手腕位置)，排除手腕剛好飄到某個
    座標、但整隻手臂根本沒有做出對應動作的雜訊姿勢
  - **visibility(可信度)檢查**，landmark可信度太低就不採信那個點的座標，
    避免鏡頭外/被遮擋的肢體產生誤判

這兩點這次也一併採用。**visibility門檻(0.3)是保守估計，MediaPipe Tasks
API的lite模型是否真的會可靠算出這個值還沒實測驗證過**，如果套用後發現
反而完全偵測不到人(可能是這個模型版本沒有正確填visibility)，第一個該
懷疑、該調整或拿掉的就是這個門檻。
"""

from __future__ import annotations

import os
from collections import Counter, deque
from dataclasses import dataclass
from typing import NamedTuple

DEFAULT_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "pose_landmarker_lite.task")
MODEL_DOWNLOAD_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)

# BlazePose(MediaPipe Pose)標準landmark索引，跟YOLO-pose用的COCO 17點不同
_NOSE, _LEFT_SHOULDER, _RIGHT_SHOULDER = 0, 11, 12
_LEFT_ELBOW, _RIGHT_ELBOW = 13, 14
_LEFT_WRIST, _RIGHT_WRIST = 15, 16
_LEFT_HIP, _RIGHT_HIP = 23, 24

_VISIBILITY_THRESHOLD = 0.3


@dataclass(frozen=True)
class VisionSignal:
    """統一的視覺訊號輸出格式，不管背後是YOLO-pose還是MediaPipe Pose，都
    產生同樣形狀的結果，餵進multimodal_brain.py。event保留跟
    voice_io_bridge/gesture_bridge一致的事件代碼慣例(可為None)，
    description_zh是給LLM看的人類可讀描述，是實際拿去分類判斷的主要依據。"""

    event: str | None
    description_zh: str


class LandmarkPoint(NamedTuple):
    """跟MediaPipe Tasks API的NormalizedLandmark同樣欄位(x/y是0-1
    normalized座標，不是像素)，但只留判斷邏輯真的會用到的欄位，方便單元
    測試直接建構，不需要真的import mediapipe。visibility預設1.0(完全
    可信)，方便舊測試/呼叫端不需要每次都手動指定。"""

    x: float
    y: float
    visibility: float = 1.0


def _distance(a: LandmarkPoint, b: LandmarkPoint) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _visible(*points: LandmarkPoint) -> bool:
    return all(p.visibility >= _VISIBILITY_THRESHOLD for p in points)


def _elbow_angle(shoulder: LandmarkPoint, elbow: LandmarkPoint, wrist: LandmarkPoint) -> float:
    """手肘彎曲角度(度)：0度是完全折疊，180度是手臂打直。參考
    yuava22/Interactive-service-robots套件裡`mediapipe_pose_gesture.py`
    範例實作的算法(見模組docstring修正記錄)，用來排除「手腕座標剛好飄到
    某個位置，但整隻手臂根本沒有做出對應動作」的雜訊姿勢。"""
    import math

    ab = (shoulder.x - elbow.x, shoulder.y - elbow.y)
    cb = (wrist.x - elbow.x, wrist.y - elbow.y)
    ab_norm = math.hypot(*ab)
    cb_norm = math.hypot(*cb)
    if ab_norm == 0 or cb_norm == 0:
        return 0.0
    cosine = max(-1.0, min(1.0, (ab[0] * cb[0] + ab[1] * cb[1]) / (ab_norm * cb_norm)))
    return math.degrees(math.acos(cosine))


def _classify_gesture(
    nose: LandmarkPoint,
    left_shoulder: LandmarkPoint,
    right_shoulder: LandmarkPoint,
    left_elbow: LandmarkPoint,
    right_elbow: LandmarkPoint,
    left_wrist: LandmarkPoint,
    right_wrist: LandmarkPoint,
    left_hip: LandmarkPoint,
    right_hip: LandmarkPoint,
) -> tuple[str | None, str]:
    """純幾何判斷邏輯，抽出來獨立於`process_frame()`之外，好處是可以直接
    餵座標做單元測試，不需要真的跑MediaPipe/準備模型檔。全程用normalized
    座標(0-1)判斷，不轉換成像素——見模組docstring 2026-09-10第二版修正
    記錄，這是參考yuava22套件範例實作後改的做法，比第一版的「肩寬比例」
    更直接(normalized座標本身就已經跟解析度無關)。

    左右手臂分開檢查、任一手滿足條件就算(是「或」不是「兩手都要」)。"""
    arms = [
        (left_shoulder, left_elbow, left_wrist, left_hip),
        (right_shoulder, right_elbow, right_wrist, right_hip),
    ]

    # water：手腕靠近臉(用鼻子當代表點)，且手肘有明顯彎曲角度(不是手臂
    # 隨便伸直、手腕剛好路過臉附近那種雜訊姿勢)。門檻數值參考自yuava22
    # 範例實作(mouth-based版本用0.12，這裡用鼻子當代表點所以放寬到0.15，
    # 沒有實機測試校準過)。
    for shoulder, elbow, wrist, _hip in arms:
        if not _visible(shoulder, elbow, wrist, nose):
            continue
        if _distance(wrist, nose) < 0.15 and 30 <= _elbow_angle(shoulder, elbow, wrist) <= 150:
            return "WATER_REQUEST", "使用者的手靠近嘴巴/臉部，可能想喝水"

    # help：手腕明顯舉到頭頂以上(比鼻子還高一截，不只是比肩膀高)，
    # 才跟「手貼著臉」的高度區分開來(2026-09-10第一版單元測試時發現的
    # 邏輯bug：正常人體比例下嘴巴本來就在肩膀以上，比肩膀高不足以區分
    # 兩種手勢)。
    for _shoulder, _elbow, wrist, _hip in arms:
        if not _visible(wrist, nose):
            continue
        if wrist.y < nose.y - 0.05:
            return "HELP_REQUEST", "使用者把手舉到頭頂以上，可能在求助"

    # toilet：手腕靠近骨盆、且位置比肩膀低。
    for shoulder, _elbow, wrist, hip in arms:
        if not _visible(shoulder, wrist, hip):
            continue
        if _distance(wrist, hip) < 0.2 and wrist.y > shoulder.y + 0.05:
            return "TOILET_REQUEST", "使用者的手靠近腰部/骨盆位置，可能想上廁所"

    return None, "偵測到人，但沒有明顯的求助/喝水/如廁動作"


class MediaPipePoseDetector:
    """包一層MediaPipe PoseLandmarker，讓網頁後端可以逐張frame呼叫、維持
    同一個session的事件history(判斷需要看最近幾幀，不是單張frame就能穩定
    判斷)。需要真的裝好mediapipe套件+下載模型檔才能建構。"""

    def __init__(self, model_path: str | None = None):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        path = model_path or DEFAULT_MODEL_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"找不到MediaPipe Pose模型檔({path})，需要先下載：\n"
                f"curl -L -o {path} {MODEL_DOWNLOAD_URL}"
            )
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=path),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.3,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._mp = mp
        self._event_history: deque = deque(maxlen=8)

    def process_frame(self, frame) -> VisionSignal:
        """frame: BGR numpy array(cv2慣例)。"""
        import cv2

        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        result = self._landmarker.detect(mp_image)

        if not result.pose_landmarks:
            self._event_history.append(None)
            return VisionSignal(event=self._stable_event(), description_zh="鏡頭畫面中沒有偵測到人")

        landmarks = result.pose_landmarks[0]

        # 直接用normalized座標(0-1)，不乘上畫面寬高——見模組docstring
        # 2026-09-10第二版修正記錄，跟解析度無關，不需要另外用肩寬換算。
        def point(idx: int) -> LandmarkPoint:
            lm = landmarks[idx]
            return LandmarkPoint(x=lm.x, y=lm.y, visibility=lm.visibility)

        current_event, description = _classify_gesture(
            nose=point(_NOSE),
            left_shoulder=point(_LEFT_SHOULDER),
            right_shoulder=point(_RIGHT_SHOULDER),
            left_elbow=point(_LEFT_ELBOW),
            right_elbow=point(_RIGHT_ELBOW),
            left_wrist=point(_LEFT_WRIST),
            right_wrist=point(_RIGHT_WRIST),
            left_hip=point(_LEFT_HIP),
            right_hip=point(_RIGHT_HIP),
        )

        self._event_history.append(current_event)
        return VisionSignal(event=self._stable_event(), description_zh=description)

    def _stable_event(self) -> str | None:
        counted = Counter(e for e in self._event_history if e is not None)
        if not counted:
            return None
        event, count = counted.most_common(1)[0]
        return event if count >= 4 else None
