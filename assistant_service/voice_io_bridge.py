"""
把 yuava22/Interactive-service-robots(規則式、非LLM的病床語音助理)的意圖
判斷結果包裝成BrainResponse，接進已經驗證過的Response Controller管線。

那個repo(voice_io_event_detector套件)長這樣：
  wav檔 -> asr.transcribe_with_whisper() -> 文字
        -> intent_rules.decide_event_and_reply() -> EventDecision(event,
           reply_zh, reply_en)
        -> tts.speak_bilingual_background() -> gTTS中文+英文語音

這裡只借用前兩步(ASR+規則式意圖判斷)當作「大腦」的第一個真實(非手動
填寫)輸入來源，取代gTTS中英文語音，改用我們自己驗證過的
tw_hokkien_tts_pipeline產生台語語音。**reply_en會原樣放進
BrainResponse.response_en**，給multilingual_output.py產生英文補充語音用
(2026-08-04修正：原本這裡完全不用reply_en，導致規則式快速路徑觸發的
案例永遠沒有英文補充語音，跟LLM路徑的行為不一致——使用者實測後要求
「不要再有沒有語音的問題」)。這幾句英文固定回覆是對方repo原本就寫好的
(intent_rules.py)，不是這裡新翻譯的，跟response_zh一樣算是「這條規則式
路徑本身提供的內容」，不需要另外呼叫LLM生成。

刻意設計成duck typing、不在module層級import voice_io_event_detector：
這個套件的核心意圖判斷邏輯(intent_rules.py)本身是零相依的純Python，但
ASR(asr.py)需要openai-whisper、TTS(tts.py)需要gTTS+mpg123——這些跟
assistant_service其他部分無關，不應該變成import這個模組就一定要裝的
硬性相依。event_decision_to_brain_response()只依賴「有event/reply_zh
屬性的物件」這個最小介面，可以用假物件獨立測試轉換邏輯；真的要跑ASR時
(run_from_wav())才delay-import對方套件。

風險判斷的重要前提：這個repo目前只有3種規則式意圖(喝水/上廁所/求助)，
規則本身(intent_rules.py)完全不涉及藥物/劑量/病歷/醫囑內容，所以這裡
固定給risk_level="low"，會走tw_hokkien_tts_pipeline的adaptive A/B/C
(不是StructuredMedicalRenderer，那是給醫囑類高風險內容用的)。這個假設
綁死在這個檔案裡——如果對方repo的intent_rules.py之後新增涉及藥物/醫囑
的規則，這裡必須跟著改，不能假設「規則式(非LLM)輸出」就永遠等於低風險。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol

from assistant_service.brain_response import BrainResponse
from assistant_service.speech_request_queue import (
    PRIORITY_COMPANION_CHAT,
    PRIORITY_GENERAL_SERVICE,
    PRIORITY_NURSE_ALERT,
)


class EventDecisionLike(Protocol):
    event: str | None
    reply_zh: str
    reply_en: str


# event字串 -> (intent, priority)。priority用speech_request_queue既有的
# 優先權常數，跟risk_level是兩件事：risk_level管「這句話能不能讓adaptive
# 翻譯自由決定用字」，priority管「播放佇列裡誰先講」。help_request雖然
# priority拉高(可能是緊急狀況、要插播)，但risk_level還是low，因為翻譯
# 內容本身(「我已通知護理人員，請保持冷靜」)不涉及藥物/醫囑，不需要走
# StructuredMedicalRenderer的候選C。
_EVENT_TO_INTENT_PRIORITY: dict[str | None, tuple[str, int]] = {
    "WATER_REQUEST": ("water_request", PRIORITY_GENERAL_SERVICE),
    "TOILET_REQUEST": ("toilet_request", PRIORITY_GENERAL_SERVICE),
    "HELP_REQUEST": ("help_request", PRIORITY_NURSE_ALERT),
    None: ("unclassified_request", PRIORITY_COMPANION_CHAT),
}


def event_decision_to_brain_response(decision: EventDecisionLike, request_id: str | None = None) -> BrainResponse:
    """把decide_event_and_reply()的輸出轉成BrainResponse。response_zh是
    主要輸出(拿去翻譯成台語)，response_en直接沿用decision.reply_en(對方
    repo原本就寫好的固定英文回覆)，給中英文補充語音的英文那部分用，不需要
    另外呼叫LLM生成。"""
    intent, priority = _EVENT_TO_INTENT_PRIORITY.get(
        decision.event, ("unclassified_request", PRIORITY_COMPANION_CHAT),
    )
    return BrainResponse(
        request_id=request_id or f"voice_io_{uuid.uuid4().hex[:8]}",
        intent=intent,
        risk_level="low",
        language="zh-TW",
        response_zh=decision.reply_zh,
        response_en=decision.reply_en,
        slots={},
        action="speak",
        evidence_ids=[],
        priority=priority,
    )


def run_from_wav(wav_path: str | Path, request_id: str | None = None) -> BrainResponse:
    """端到端：wav檔 -> Whisper ASR -> 規則式意圖判斷 -> BrainResponse。
    需要真的安裝voice_io_event_detector套件(來自
    https://github.com/yuava22/Interactive-service-robots，含
    openai-whisper相依)，import延遲到這裡才做。只是要測試轉換邏輯本身
    (不需要真的跑Whisper)，用event_decision_to_brain_response()配合手動
    建構的EventDecision-like物件即可。"""
    try:
        from voice_io_event_detector.asr import transcribe_with_whisper
        from voice_io_event_detector.intent_rules import decide_event_and_reply
    except ImportError as exc:
        raise ImportError(
            "需要先安裝voice_io_event_detector套件(pip install -e path/to/"
            "Interactive-service-robots，見"
            "https://github.com/yuava22/Interactive-service-robots)才能用"
            "run_from_wav()。"
        ) from exc

    text = transcribe_with_whisper(wav_path)
    decision = decide_event_and_reply(text)
    return event_decision_to_brain_response(decision, request_id=request_id)
