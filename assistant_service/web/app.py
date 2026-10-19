"""
整合驗證網站：把assistant_service目前串起來的所有東西放在同一個網頁上實測——
真正的LLM大腦、語音跟視覺訊號統一透過multimodal_brain.classify()分類(不是
語音一套、視覺另一套各自獨立的規則)、Response Controller安全把關、
tw_hokkien_tts_pipeline台語輸出、multilingual_output的中英文補充語音，
以及鏡頭視覺辨識(MediaPipe Pose優先，YOLO-pose當備援)。

跟live_test/(單純zh->台語翻譯+TTS的簡單demo，沒有大腦/風險判斷這些層)不同，
這裡驗證的是使用者要求的「完整輸入(語音/文字/視覺) -> 大腦 -> 安全翻譯 ->
三語輸出」整條路，是這次整合的驗證介面。

前置需求：
  1. ollama serve
     (已pull過hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M
     跟qwen2.5:7b-instruct)
  2. TTS_BACKEND=neurlang python3 live_test/tts_backend.py（port 5010）
  3. pip install openai-whisper gtts mediapipe（語音輸入/中英文補充語音
     輸出/MediaPipe視覺辨識要用）
  4. (選用) pip install -e path/to/Interactive-service-robots
     （yuava22/Interactive-service-robots，裝了才會啟用規則式快速路徑+
     YOLO-pose視覺辨識備援；沒裝的話純語音全部走LLM大腦，視覺辨識則看
     MediaPipe有沒有裝，這是刻意設計的降級行為，不是bug，見
     _voice_io_pkg_available()/_vision_backend()）

啟動：python3 -m assistant_service.web.app
瀏覽器：http://127.0.0.1:5020
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from flask import Flask, jsonify, render_template, request, send_from_directory  # noqa: E402

from assistant_service import multimodal_brain, tts_router  # noqa: E402
from assistant_service.brain_llm import OllamaBrainError  # noqa: E402
from assistant_service.multilingual_output import synthesize_multilingual  # noqa: E402
from assistant_service.response_controller import FALLBACK_AUDIO_PATH, ResponseController  # noqa: E402
from assistant_service.vision_bridge import DEFAULT_MODEL_PATH as MEDIAPIPE_MODEL_PATH  # noqa: E402
from scripts.eval_translation_safety import (  # noqa: E402
    DEVICE_LEXICON,
    DRUG_LEXICON,
    MEDICAL_TITLE_LEXICON,
    PERSON_NAMES,
)
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard  # noqa: E402
from tw_hokkien_tts_pipeline.structured_renderer import StructuredMedicalRenderer  # noqa: E402
from tw_hokkien_tts_pipeline.translate import TaigiLlamaTranslationBackend  # noqa: E402

app = Flask(__name__)

_guard = ProtectedTokenGuard(
    drug_lexicon=DRUG_LEXICON,
    person_names=PERSON_NAMES,
    medical_title_lexicon=MEDICAL_TITLE_LEXICON,
    device_lexicon=DEVICE_LEXICON,
)
_translation_backend = TaigiLlamaTranslationBackend()
_renderer = StructuredMedicalRenderer()
_controller = ResponseController(
    guard=_guard, translation_backend=_translation_backend, renderer=_renderer, tts_router=tts_router,
)


def _voice_io_pkg_available() -> bool:
    """yuava22/Interactive-service-robots是不是有裝(pip install -e)。沒裝
    時規則式快速路徑會停用，純語音全部走LLM大腦——這是刻意的降級路徑，
    不是錯誤，因為對方套件是選用的外部相依(私有repo, 不vendor進這個專案，
    見assistant_service/README.md)。"""
    return importlib.util.find_spec("voice_io_event_detector") is not None


def _whisper_available() -> bool:
    return importlib.util.find_spec("whisper") is not None


def _vision_backend() -> str | None:
    """決定鏡頭視覺辨識要用哪個backend：MediaPipe Pose優先(這次新加的)，
    沒裝好(套件或模型檔缺任一個)就退回YOLO-pose(舊的gesture_bridge.py，
    需要yuava22套件+ultralytics)，兩個都沒有就回傳None(前端會顯示鏡頭
    功能停用)。"""
    if importlib.util.find_spec("mediapipe") is not None and os.path.exists(MEDIAPIPE_MODEL_PATH):
        return "mediapipe"
    if (
        _voice_io_pkg_available()
        and importlib.util.find_spec("ultralytics") is not None
        and importlib.util.find_spec("cv2") is not None
    ):
        return "yolo"
    return None


def _hokkien_audio_url(path: str | None) -> str | None:
    """result.audio_path可能指向兩個不同目錄：一般成功案例在
    assistant_service/cache/audio/，fail-safe(rejected/abstained)的固定
    回覆音檔在assistant_service/fallback_audio/(見response_controller.py
    的FALLBACK_AUDIO_PATH)——這裡兩個路由分開serve，URL要對應到正確目錄，
    不能都假設是cache/audio/(這是先前版本的bug：fail-safe案例的音檔會
    404，因為fallback_audio/notify_nurse.wav沒有被cache/audio/那個路由
    serve到)。"""
    if not path:
        return None
    if os.path.basename(path) == os.path.basename(FALLBACK_AUDIO_PATH):
        return f"/audio/fallback/{os.path.basename(path)}"
    return f"/audio/hokkien/{os.path.basename(path)}"


def _finish_pipeline(brain_response, recognized_text: str, detected_language: str | None, brain_path: str) -> dict:
    """給定一個已經決定好的BrainResponse(不管是文字/語音/視覺，都是經過
    _run_pipeline()裡的multimodal_brain.classify()決定的)，跑完Response
    Controller+三語輸出，組成回傳給前端的結果dict。"""
    result = _controller.handle(brain_response)
    multi = synthesize_multilingual(brain_response, result)

    return {
        "request_id": brain_response.request_id,
        "recognized_text": recognized_text,
        "detected_language": detected_language,
        "brain_path": brain_path,
        "intent": brain_response.intent,
        "risk_level": brain_response.risk_level,
        "evidence_ids": brain_response.evidence_ids,
        "status": result.status,
        "translation_method": result.translation_method,
        "hanji_text": result.hanji_text,
        "action": result.action,
        "safety": result.safety,
        "errors": result.errors,
        "hokkien_audio_url": _hokkien_audio_url(result.audio_path),
        "zh_audio_url": f"/audio/multilingual/{os.path.basename(multi.zh_audio_path)}" if multi.zh_audio_path else None,
        "en_audio_url": f"/audio/multilingual/{os.path.basename(multi.en_audio_path)}" if multi.en_audio_path else None,
        # 2026-09-10新增：前端依語言模式切換顯示文字用，跟對應音檔內容
        # 保證一致(包含fail-safe時顯示固定回覆句，不是被擋下來的原始內容)
        "zh_text": multi.zh_text,
        "en_text": multi.en_text,
    }


def _run_pipeline(
    user_text: str | None = None, detected_language: str | None = None, vision_description: str | None = None,
) -> dict:
    """語音/文字/視覺輸入統一從這裡經過multimodal_brain.classify()決定
    BrainResponse——不再各自維護獨立的規則式判斷邏輯(見
    multimodal_brain.py docstring)。"""
    request_id = f"web_{uuid.uuid4().hex[:8]}"
    try:
        brain_response, brain_path = multimodal_brain.classify(
            voice_text=user_text, vision_description=vision_description, request_id=request_id,
        )
    except OllamaBrainError as exc:
        return {"error": str(exc)}
    recognized_text = user_text or f"(視覺: {vision_description})"
    return _finish_pipeline(brain_response, recognized_text, detected_language, brain_path)


@app.route("/")
def index():
    return render_template(
        "index.html",
        voice_io_available=_voice_io_pkg_available(),
        whisper_available=_whisper_available(),
        vision_backend=_vision_backend(),
    )


@app.route("/api/interact", methods=["POST"])
def interact():
    if "audio" in request.files:
        if not _whisper_available():
            return jsonify({"error": "後端沒有裝openai-whisper，無法辨識語音(pip install openai-whisper)"}), 400
        from assistant_service.asr_bridge import transcribe_bilingual

        audio_file = request.files["audio"]
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            audio_file.save(tmp.name)
            tmp_path = tmp.name
        try:
            transcription = transcribe_bilingual(tmp_path)
        finally:
            os.unlink(tmp_path)

        if not transcription.text:
            return jsonify({"error": "沒有辨識出任何文字，請再說一次"}), 200
        return jsonify(_run_pipeline(transcription.text, detected_language=transcription.detected_language))

    payload = request.get_json(silent=True) or {}
    user_text = (payload.get("text") or "").strip()
    if not user_text:
        return jsonify({"error": "請輸入文字或錄音"}), 400
    return jsonify(_run_pipeline(user_text))


@app.route("/api/vision_frame", methods=["POST"])
def vision_frame():
    """接收單張webcam frame，跑視覺辨識(MediaPipe Pose優先，YOLO-pose當
    備援，見_vision_backend())。任何依賴沒裝好都直接回傳提示訊息而不是
    500錯誤——鏡頭視覺辨識本來就是選用功能，缺少依賴是預期狀況。

    不管哪個backend，偵測到的訊號都送進multimodal_brain.classify()交給
    LLM判斷，不像先前版本那樣直接拿YOLO的事件代碼查表決定最終回覆文字
    ——這是這次要求的「視覺辨識也要依靠LLM分類」，兩個backend產生的
    VisionSignal(event, description_zh)形狀一致，下游邏輯不需要知道
    訊號實際上是哪個backend產生的。"""
    backend = _vision_backend()
    if backend is None:
        return jsonify({"available": False, "reason": "沒有可用的視覺辨識backend(mediapipe或yolo都沒裝好)"}), 200

    import numpy as np
    import cv2

    file = request.files.get("frame")
    if file is None:
        return jsonify({"error": "缺少frame"}), 400
    data = np.frombuffer(file.read(), dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"error": "frame解碼失敗"}), 400

    signal = _get_vision_signal(backend, frame)
    if signal is None:  # 模型/權重檔缺失，backend初始化失敗
        return jsonify({"available": False, "reason": f"{backend} backend初始化失敗，見伺服器log"}), 200

    if signal.event is None:
        # 2026-09-10新增description欄位：原本event=None時完全不回傳
        # signal.description_zh，前端只能顯示「監控中」，使用者做動作時
        # 完全看不出「有沒有偵測到人」「有沒有偵測到姿勢但還沒到穩定門檻」
        # 「還是根本什麼都沒偵測到」這三種情況的差異，回報「沒反應」時
        # 我方沒辦法判斷卡在哪一步。把每一幀的原始描述文字回傳，讓使用者
        # 自己就能即時看到偵測狀況，不用等到「穩定觸發」那一刻才有畫面。
        return jsonify({
            "available": True, "backend": backend, "event": None,
            "description_zh": signal.description_zh,
        })

    result = _run_pipeline(vision_description=signal.description_zh, detected_language=f"vision:{backend}")
    result["gesture_event"] = signal.event
    result["vision_backend"] = backend
    return jsonify(result)


def _get_vision_signal(backend: str, frame):
    """依backend選擇對應的偵測session(每個backend各自維護一個process級
    的session，保留跨frame的事件history，判斷需要看最近幾幀不是單張frame
    就能穩定判斷)。回傳VisionSignal，初始化失敗回傳None。"""
    if backend == "mediapipe":
        if "mediapipe_session" not in _get_vision_signal.__dict__:
            from assistant_service.vision_bridge import MediaPipePoseDetector

            try:
                _get_vision_signal.mediapipe_session = MediaPipePoseDetector()
            except FileNotFoundError:
                return None
        return _get_vision_signal.mediapipe_session.process_frame(frame)

    if "yolo_session" not in _get_vision_signal.__dict__:
        from assistant_service.gesture_bridge import GestureDetectorSession
        from assistant_service.vision_bridge import VisionSignal

        try:
            _get_vision_signal.yolo_session = GestureDetectorSession()
        except FileNotFoundError:
            return None
        _get_vision_signal.VisionSignal = VisionSignal

    stable_event, _annotated = _get_vision_signal.yolo_session.process_frame(frame)
    description = f"YOLO姿態偵測到事件代碼：{stable_event}" if stable_event else "沒有偵測到明顯動作"
    return _get_vision_signal.VisionSignal(event=stable_event, description_zh=description)


@app.route("/audio/hokkien/<path:filename>")
def hokkien_audio(filename):
    return send_from_directory(os.path.join(ROOT, "assistant_service", "cache", "audio"), filename)


@app.route("/audio/multilingual/<path:filename>")
def multilingual_audio(filename):
    return send_from_directory(os.path.join(ROOT, "assistant_service", "cache", "multilingual_audio"), filename)


@app.route("/audio/fallback/<path:filename>")
def fallback_audio_route(filename):
    return send_from_directory(os.path.dirname(FALLBACK_AUDIO_PATH), filename)


if __name__ == "__main__":
    print("整合驗證網站準備好了。")
    print(f"規則式快速路徑(yuava22 intent_rules，純語音才會用到): {'啟用' if _voice_io_pkg_available() else '停用(套件沒裝，全部走LLM大腦)'}")
    print(f"語音輸入(whisper): {'啟用' if _whisper_available() else '停用(pip install openai-whisper)'}")
    print(f"視覺辨識backend: {_vision_backend() or '停用(mediapipe跟yolo都沒裝好)'}")
    print("本機瀏覽器：http://127.0.0.1:5020")
    app.run(host="0.0.0.0", port=5020, debug=False)
