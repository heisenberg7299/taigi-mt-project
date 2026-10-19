"""
vision_bridge(MediaPipe Pose)測試。需要mediapipe套件+下載好的pose
landmarker模型檔(見vision_bridge.DEFAULT_MODEL_PATH)才會跑，缺任一個就
整組skip。用ultralytics內建的測試圖片(zidane.jpg)當輸入，跟
test_gesture_bridge.py(YOLO-pose版本)用同一張圖，方便比較兩個backend
在同一張圖上的行為。
"""

from __future__ import annotations

import importlib.util
import os

import pytest

from assistant_service.vision_bridge import DEFAULT_MODEL_PATH

_HAS_MEDIAPIPE = importlib.util.find_spec("mediapipe") is not None
_HAS_MODEL = os.path.exists(DEFAULT_MODEL_PATH)

pytestmark = pytest.mark.skipif(
    not (_HAS_MEDIAPIPE and _HAS_MODEL),
    reason=f"需要mediapipe套件+pose landmarker模型檔({DEFAULT_MODEL_PATH})都到位才會跑",
)


def _test_frame():
    import cv2
    from ultralytics.utils import ASSETS

    return cv2.imread(str(ASSETS / "zidane.jpg"))


def test_detector_initializes_and_processes_real_frame_without_crashing():
    from assistant_service.vision_bridge import MediaPipePoseDetector, VisionSignal

    detector = MediaPipePoseDetector()
    signal = detector.process_frame(_test_frame())

    assert isinstance(signal, VisionSignal)
    assert signal.description_zh  # 不是空字串


def test_stable_event_requires_multiple_consistent_frames():
    """單一frame不應該立刻回傳穩定事件(跟YOLO版本一樣的「連續N幀才算穩定」
    設計，避免單一幀的雜訊誤判)。"""
    from assistant_service.vision_bridge import MediaPipePoseDetector

    detector = MediaPipePoseDetector()
    signal = detector.process_frame(_test_frame())

    assert signal.event is None


def test_missing_model_file_raises_file_not_found_with_actionable_message():
    from assistant_service.vision_bridge import MediaPipePoseDetector

    with pytest.raises(FileNotFoundError, match="curl"):
        MediaPipePoseDetector(model_path="/nonexistent/path/model.task")
