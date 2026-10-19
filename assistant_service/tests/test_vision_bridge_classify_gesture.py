"""
`_classify_gesture()`是vision_bridge.py裡抽出來的純幾何判斷邏輯，不依賴
mediapipe套件或pose landmarker模型檔，所以獨立成這個檔案、不套用
test_vision_bridge.py那個「沒裝mediapipe/模型檔就整組skip」的pytestmark，
永遠會跑。

2026-09-10第二版修正：改用normalized座標(0-1，跟MediaPipe原生輸出一致)
判斷，不再乘上畫面寬高轉成像素——這個做法本身就跟解析度無關，不需要像
第一版那樣另外用肩寬換算比例(見vision_bridge.py模組docstring的完整修正
記錄)。這裡的座標都是隨手指定的簡單數字，只是用來驗證幾何判斷邏輯本身
對不對，不是在模擬真實人體比例。
"""

from __future__ import annotations

from assistant_service.vision_bridge import LandmarkPoint, _classify_gesture

# 一組固定的「身體骨架」基準點(鼻子/肩膀/骨盆)，各測試案例只改手腕/手肘
# 的位置來觸發不同手勢，其餘部位維持這組基準值不變。
_NOSE = LandmarkPoint(0.5, 0.10)
_LEFT_SHOULDER = LandmarkPoint(0.4, 0.30)
_RIGHT_SHOULDER = LandmarkPoint(0.6, 0.30)
_LEFT_HIP = LandmarkPoint(0.45, 0.65)
_RIGHT_HIP = LandmarkPoint(0.55, 0.65)
_RESTING_WRIST = LandmarkPoint(0.2, 0.60)  # 手垂在身體側邊，不靠近任何目標點
_RESTING_ELBOW = LandmarkPoint(0.25, 0.45)


def _base_kwargs(**overrides) -> dict:
    kwargs = dict(
        nose=_NOSE,
        left_shoulder=_LEFT_SHOULDER,
        right_shoulder=_RIGHT_SHOULDER,
        left_elbow=_RESTING_ELBOW,
        right_elbow=_RESTING_ELBOW,
        left_wrist=_RESTING_WRIST,
        right_wrist=_RESTING_WRIST,
        left_hip=_LEFT_HIP,
        right_hip=_RIGHT_HIP,
    )
    kwargs.update(overrides)
    return kwargs


def test_hand_near_mouth_with_bent_elbow_detected_as_water_request():
    """手腕靠近鼻子(代表嘴巴/臉部)、手肘呈45度左右的自然彎曲角度。"""
    event, _ = _classify_gesture(
        **_base_kwargs(
            right_elbow=LandmarkPoint(0.7, 0.30),
            right_wrist=LandmarkPoint(0.52, 0.12),
        )
    )
    assert event == "WATER_REQUEST"


def test_hand_near_mouth_but_arm_fully_straight_not_detected():
    """手腕座標剛好靠近鼻子，但手肘幾乎沒有彎曲(角度接近0度)——這種姿勢
    不像真的在喝水，是雜訊姿勢，不應該誤判。手肘角度檢查存在的意義就是
    排除這種案例(參考yuava22套件範例實作的做法，見模組docstring)。"""
    event, _ = _classify_gesture(
        **_base_kwargs(
            right_elbow=LandmarkPoint(0.51, 0.11),  # 幾乎跟wrist/shoulder共線
            right_wrist=LandmarkPoint(0.52, 0.12),
        )
    )
    assert event != "WATER_REQUEST"


def test_hand_raised_above_head_detected_as_help_request():
    """手腕明顯舉到頭頂以上(比鼻子高一大截)，且離臉不夠近(不會先被
    water規則攔截)。"""
    event, _ = _classify_gesture(**_base_kwargs(right_wrist=LandmarkPoint(0.65, -0.05)))
    assert event == "HELP_REQUEST"


def test_hand_near_hip_and_below_shoulder_detected_as_toilet_request():
    event, _ = _classify_gesture(**_base_kwargs(right_wrist=LandmarkPoint(0.58, 0.62)))
    assert event == "TOILET_REQUEST"


def test_no_gesture_when_hands_rest_at_sides():
    event, description = _classify_gesture(**_base_kwargs())
    assert event is None
    assert "沒有明顯" in description


def test_low_visibility_wrist_is_not_trusted():
    """手腕座標看起來像在喝水，但visibility很低(例如手被鏡頭邊緣切到、
    追蹤不穩)，不應該採信這個座標去判斷手勢。"""
    event, _ = _classify_gesture(
        **_base_kwargs(
            right_elbow=LandmarkPoint(0.7, 0.30),
            right_wrist=LandmarkPoint(0.52, 0.12, visibility=0.05),
        )
    )
    assert event is None


def test_either_arm_can_trigger_gesture_independently():
    """左手做出喝水動作也該被偵測到，不是只看右手。"""
    event, _ = _classify_gesture(
        **_base_kwargs(
            left_elbow=LandmarkPoint(0.3, 0.30),
            left_wrist=LandmarkPoint(0.48, 0.12),
        )
    )
    assert event == "WATER_REQUEST"
