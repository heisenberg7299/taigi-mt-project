"""
多模態意圖分類：語音辨識文字(asr_bridge.py)跟鏡頭視覺訊號(gesture_bridge.py
的YOLO-pose、或vision_bridge.py的MediaPipe Pose)統一放進這一個地方一起
判斷，不再讓語音、視覺各自走獨立、互相看不到對方的規則式判斷邏輯。

分類的實際決策交給LLM(brain_llm.OllamaBrain)。唯一的例外：**純語音輸入**
且對得到yuava22規則式意圖(喝水/上廁所/求助關鍵字)時，走原本的快速路徑，
不需要LLM推論延遲——這條路徑本身已經端到端驗證過夠可靠(見
voice_io_bridge.py)，沒有理由為了「統一都用LLM」而故意犧牲掉這個已經
證明可行的快速路徑。除此之外的情況——任何有視覺訊號的輸入、或語音沒對到
規則式關鍵字——一律組合所有可得的訊號一起丟給LLM，由LLM統一判斷
intent/risk_level/response_zh/slots，而不是像之前的gesture_bridge.py那樣
拿視覺事件代碼直接查表決定最終回覆文字。

這樣設計的理由：語音的規則式比對是「使用者講的一句完整的話」，語意本身
已經很明確；但視覺訊號(「手靠近嘴巴」這種姿態描述)本身沒有語意，需要
判斷力去解讀「這代表使用者想做什麼」，這種判斷比固定查表更適合交給LLM，
也更容易在之後結合語音+視覺同時出現時做出比對(例如同時偵測到「舉手」跟
聽到「不用了」，應該怎麼判斷，這種情境查表法完全無法處理)。

**大腦自己標的risk_level/slots一樣不能被信任**，跟brain_llm.py原本的
設計一致，response_controller.py的enforce_deterministic_risk_level()
才是最終防線，這裡的分類判斷只決定「大腦覺得應該回答什麼」，不影響
Response Controller那層獨立的安全把關。
"""

from __future__ import annotations

import importlib.util
import uuid

from assistant_service.brain_llm import OllamaBrain
from assistant_service.brain_response import BrainResponse
from assistant_service.voice_io_bridge import event_decision_to_brain_response


def _voice_io_pkg_available() -> bool:
    return importlib.util.find_spec("voice_io_event_detector") is not None


_brain_singleton: OllamaBrain | None = None


def _default_brain() -> OllamaBrain:
    global _brain_singleton
    if _brain_singleton is None:
        _brain_singleton = OllamaBrain()
    return _brain_singleton


def classify(
    voice_text: str | None = None,
    vision_description: str | None = None,
    request_id: str | None = None,
    brain: OllamaBrain | None = None,
) -> tuple[BrainResponse, str]:
    """把語音文字跟視覺描述(至少要有一個)組合起來，回傳
    (BrainResponse, 分類路徑)。分類路徑是"rule_based_fast_path"(純語音、
    對到規則式關鍵字)或"llm_multimodal"(其餘情況，包含任何視覺訊號)，
    給呼叫端記錄/顯示用，不影響BrainResponse本身的內容。"""
    if not voice_text and not vision_description:
        raise ValueError("voice_text跟vision_description至少要提供一個")

    request_id = request_id or f"multimodal_{uuid.uuid4().hex[:8]}"

    if voice_text and not vision_description and _voice_io_pkg_available():
        from voice_io_event_detector.intent_rules import decide_event_and_reply

        decision = decide_event_and_reply(voice_text)
        if decision.event is not None:
            return event_decision_to_brain_response(decision, request_id=request_id), "rule_based_fast_path"

    combined_parts = []
    if voice_text:
        combined_parts.append(f"使用者說的話：{voice_text}")
    if vision_description:
        combined_parts.append(f"鏡頭觀察到的畫面：{vision_description}")
    combined_text = "\n".join(combined_parts)

    brain = brain or _default_brain()
    brain_response = brain.generate(combined_text, request_id=request_id)
    return brain_response, "llm_multimodal"
