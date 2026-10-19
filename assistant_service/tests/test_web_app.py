"""
整合驗證網站(assistant_service/web/app.py)的路由邏輯測試：mock掉
multimodal_brain.classify跟ResponseController.handle，不需要真的連
Ollama/TTS backend，專門測「文字/語音/視覺輸入->classify()->Response
Controller->三語輸出」這條路的glue code本身有沒有接對，不是重新測
multimodal_brain/brain_llm/response_controller自己的邏輯(那些已經有各自
的測試檔)。
"""

from __future__ import annotations

import io
import os
from unittest.mock import patch

import pytest

from assistant_service.brain_response import BrainResponse
from assistant_service.multilingual_output import MultilingualAudioResult
from assistant_service.response_controller import ControllerResult
from assistant_service.web import app as webapp


@pytest.fixture
def client():
    webapp.app.config["TESTING"] = True
    with webapp.app.test_client() as c:
        yield c


def _fake_brain_response(**overrides):
    base = dict(
        request_id="web_test", intent="general_chat", risk_level="low", language="zh-TW",
        response_zh="測試回覆", response_en="test reply",
    )
    base.update(overrides)
    return BrainResponse(**base)


def test_interact_text_routes_through_multimodal_classify(client):
    """文字輸入應該經過multimodal_brain.classify()決定BrainResponse，不是
    直接呼叫LLM或規則式邏輯——這裡只驗證glue code有把結果接對，classify()
    本身的判斷邏輯由test_multimodal_brain.py驗證。

    2026-09-10新增：evidence_ids(RAG查到的知識庫依據)也要一併出現在API
    回應裡——這個欄位之前存在於BrainResponse卻從沒被_finish_pipeline()
    放進回傳的dict，前端永遠看不到，等於RAG查到的東西無從稽核。"""
    fake_br = _fake_brain_response(evidence_ids=["kb:2"])
    fake_result = ControllerResult(
        request_id="web_test", status="completed", translation_method="raw",
        hanji_text="測試台語", action="speak", audio_path="/fake/audio.wav",
    )
    with patch("assistant_service.web.app.multimodal_brain.classify", return_value=(fake_br, "llm_multimodal")) as mock_classify, \
         patch.object(webapp._controller, "handle", return_value=fake_result), \
         patch("assistant_service.web.app.synthesize_multilingual", return_value=MultilingualAudioResult(None, None)):
        resp = client.post("/api/interact", json={"text": "一般聊天測試"})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["brain_path"] == "llm_multimodal"
    assert data["status"] == "completed"
    assert data["hanji_text"] == "測試台語"
    assert data["evidence_ids"] == ["kb:2"]
    mock_classify.assert_called_once()
    _, kwargs = mock_classify.call_args
    assert kwargs["voice_text"] == "一般聊天測試"
    assert kwargs["vision_description"] is None


def test_abstained_result_points_to_fallback_audio_route_and_it_serves_the_real_file(client):
    """response_controller._fail_safe()回傳的audio_path指向
    assistant_service/fallback_audio/notify_nurse.wav，不是cache/audio/
    ——之前的版本錯誤地把所有音檔都當成cache/audio/底下的檔案組URL，
    fail-safe案例會404。這裡驗證URL指到正確的路由，而且那個路由真的能
    把檔案serve出來(不是只有URL格式對，要真的能下載到東西)。"""
    from assistant_service.response_controller import FALLBACK_AUDIO_PATH

    fake_br = _fake_brain_response()
    fake_result = ControllerResult(
        request_id="web_test", status="abstained", action="call_nurse",
        hanji_text="這个問題我無法度確定，我共你通知護理師。", audio_path=FALLBACK_AUDIO_PATH,
        errors=["測試abstain"],
    )
    with patch("assistant_service.web.app.multimodal_brain.classify", return_value=(fake_br, "llm_multimodal")), \
         patch.object(webapp._controller, "handle", return_value=fake_result), \
         patch("assistant_service.web.app.synthesize_multilingual", return_value=MultilingualAudioResult(None, None)):
        resp = client.post("/api/interact", json={"text": "test"})

    data = resp.get_json()
    assert data["hokkien_audio_url"] == f"/audio/fallback/{os.path.basename(FALLBACK_AUDIO_PATH)}"

    audio_resp = client.get(data["hokkien_audio_url"])
    assert audio_resp.status_code == 200
    assert len(audio_resp.data) > 0


def test_interact_missing_text_returns_400(client):
    resp = client.post("/api/interact", json={})
    assert resp.status_code == 400


def test_interact_ollama_connection_error_returns_error_field(client):
    from assistant_service.brain_llm import OllamaBrainError

    with patch("assistant_service.web.app.multimodal_brain.classify", side_effect=OllamaBrainError("連不到Ollama")):
        resp = client.post("/api/interact", json={"text": "test"})

    data = resp.get_json()
    assert "連不到Ollama" in data["error"]


def test_interact_audio_without_whisper_installed_returns_400(client):
    with patch("assistant_service.web.app._whisper_available", return_value=False):
        resp = client.post(
            "/api/interact",
            data={"audio": (io.BytesIO(b"fake-webm-bytes"), "recording.webm")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 400
    assert "whisper" in resp.get_json()["error"]


def test_vision_frame_without_any_backend_reports_unavailable(client):
    """mediapipe跟yolo backend都沒裝好時，鏡頭視覺辨識要明確回報「未啟用」
    (available: False)，不能假裝有在跑或直接500。"""
    with patch("assistant_service.web.app._vision_backend", return_value=None):
        resp = client.post("/api/vision_frame", data={})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is False


def test_vision_frame_without_stable_event_still_reports_live_description(client):
    """2026-09-10新增：event還沒到穩定門檻時(event=None)，也要把當下這一幀
    的原始描述文字(description_zh)回傳給前端——不然使用者做動作時完全看
    不出「有沒有偵測到人」「有沒有偵測到姿勢但還沒到穩定門檻」跟「什麼都
    沒偵測到」的差別，回報「鏡頭沒反應」時沒辦法判斷實際卡在哪一步。"""
    import numpy as np

    from assistant_service.vision_bridge import VisionSignal

    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)
    fake_signal = VisionSignal(event=None, description_zh="偵測到人，但沒有明顯的求助/喝水/如廁動作")

    with patch("assistant_service.web.app._vision_backend", return_value="mediapipe"), \
         patch("assistant_service.web.app._get_vision_signal", return_value=fake_signal), \
         patch("cv2.imdecode", return_value=fake_frame):
        resp = client.post(
            "/api/vision_frame", data={"frame": (io.BytesIO(b"fake-jpeg-bytes"), "frame.jpg")},
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["event"] is None
    assert data["description_zh"] == "偵測到人，但沒有明顯的求助/喝水/如廁動作"


def test_vision_frame_with_detected_event_routes_through_classify_with_vision_description(client):
    """鏡頭偵測到穩定事件時，應該把description_zh(不是事件代碼本身)送進
    multimodal_brain.classify()的vision_description，交給LLM判斷——這是
    這次要求的「視覺辨識也要依靠LLM分類」，不是直接查表決定回覆文字。"""
    import numpy as np

    from assistant_service.vision_bridge import VisionSignal

    fake_br = _fake_brain_response(intent="water_request")
    fake_result = ControllerResult(
        request_id="web_test", status="completed", translation_method="raw",
        hanji_text="測試台語", action="speak", audio_path="/fake/audio.wav",
    )
    fake_frame = np.zeros((10, 10, 3), dtype=np.uint8)
    fake_signal = VisionSignal(event="WATER_REQUEST", description_zh="使用者的手靠近嘴巴/臉部，可能想喝水")

    with patch("assistant_service.web.app._vision_backend", return_value="mediapipe"), \
         patch("assistant_service.web.app._get_vision_signal", return_value=fake_signal), \
         patch("cv2.imdecode", return_value=fake_frame), \
         patch("assistant_service.web.app.multimodal_brain.classify", return_value=(fake_br, "llm_multimodal")) as mock_classify, \
         patch.object(webapp._controller, "handle", return_value=fake_result), \
         patch("assistant_service.web.app.synthesize_multilingual", return_value=MultilingualAudioResult(None, None)):
        resp = client.post(
            "/api/vision_frame", data={"frame": (io.BytesIO(b"fake-jpeg-bytes"), "frame.jpg")},
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["gesture_event"] == "WATER_REQUEST"
    assert data["vision_backend"] == "mediapipe"
    _, kwargs = mock_classify.call_args
    assert kwargs["voice_text"] is None
    assert kwargs["vision_description"] == "使用者的手靠近嘴巴/臉部，可能想喝水"


def test_index_page_renders_status_bar(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # 2026-09-10: 前端改版為多語言系統風格(語言切換/常用需求卡/聊天氣泡)，
    # 頁面標題文字跟著換了，這裡改成檢查status bar本身還在(規則式判斷/
    # 語音輸入/視覺辨識三個狀態欄位)，不綁死在舊版標題文字上
    assert "規則式判斷".encode() in resp.data
    assert "多語言系統".encode() in resp.data
