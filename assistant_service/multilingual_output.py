"""
中英文補充語音輸出：主線的安全驗證(Protected Token+安全檢查+slots交叉比對)
只發生在中文(`response_zh`)->台語(`hanji_text`)這條路，`ResponseController`
回傳的`audio_path`是唯一經過完整安全把關的音檔。

這裡額外用gTTS產生中文跟英文語音，給聽不懂台語的家屬/工作人員參考用，是
補充輸出，**不是安全驗證過的通道**：
  - 中文音檔：直接念已經通過「翻譯前」slots交叉比對的`response_zh`原文，
    沒有再翻譯，沿用的是已經檢查過的文字。
  - 英文音檔：念`response_en`，是LLM(`brain_llm.py`)在同一次生成順便給的
    翻譯，**沒有經過跟`response_zh`->`hanji_text`同等的Protected Token/
    安全檢查**——如果`response_en`把藥名/劑量翻丟了，這裡不會發現，純粹
    是輔助聆聽用，不能當成跟台語音檔同等可信的輸出。

**fail-safe(status="abstained"/"rejected")時三語都要有**：台語播放固定句
`FALLBACK_SENTENCE_HAN`，這裡中文/英文改用同樣固定翻譯好的
`FALLBACK_SENTENCE_ZH`/`FALLBACK_SENTENCE_EN`(不是brain_response原本的
response_zh/response_en)——因為進到fail-safe代表大腦原本要講的內容已經
被判定不安全/跟slots不一致，如果中英文語音講出那份被擋下來的內容，等於
讓台語那邊的安全把關失去意義。三句固定句意思一致，但**都還沒經過母語者
審核**，見response_controller.py。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from assistant_service.brain_response import BrainResponse
from assistant_service.response_controller import (
    FALLBACK_SENTENCE_EN,
    FALLBACK_SENTENCE_HAN,
    FALLBACK_SENTENCE_ZH,
    ControllerResult,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = Path(os.path.join(_HERE, "cache", "multilingual_audio"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class MultilingualAudioResult:
    zh_audio_path: str | None
    en_audio_path: str | None
    # 2026-09-10新增：前端要依語言模式顯示對應文字(不能永遠只顯示台語
    # 漢字)，這裡把「實際拿去生成zh/en音檔的那份文字」一併回傳，保證畫面
    # 顯示的文字跟播放的語音內容一致(包含fail-safe時要顯示固定回覆句，
    # 不是brain_response原本被擋下來的內容)。預設None，向後相容既有
    # 只用位置參數建構(None, None)的呼叫端/測試。
    zh_text: str | None = None
    en_text: str | None = None


def _cache_key(lang: str, text: str) -> str:
    return hashlib.sha256(f"{lang}:{text}".encode("utf-8")).hexdigest()


def _cached_gtts(text: str, lang: str) -> str:
    path = CACHE_DIR / f"{_cache_key(lang, text)}.mp3"
    if not path.exists():
        from gtts import gTTS

        gTTS(text=text, lang=lang).save(str(path))
    return str(path)


def synthesize_multilingual(brain_response: BrainResponse, controller_result: ControllerResult) -> MultilingualAudioResult:
    if controller_result.hanji_text == FALLBACK_SENTENCE_HAN:
        # fail-safe路徑(不管status是abstained還是rejected)：用固定翻譯好
        # 的中英文句子，不是brain_response原本(已經被判定不安全)的
        # response_zh/response_en。這個分支要放在action檢查之前——
        # _fail_safe()回傳的action固定是"call_nurse"不是"speak"，但台語
        # 那邊照樣會播放固定回覆音檔(見response_controller._fail_safe)，
        # 中英文語音也要跟著一致有聲音，不能因為action不是"speak"就跳過。
        zh_path = _cached_gtts(FALLBACK_SENTENCE_ZH, "zh-TW")
        en_path = _cached_gtts(FALLBACK_SENTENCE_EN, "en")
        return MultilingualAudioResult(
            zh_audio_path=zh_path, en_audio_path=en_path,
            zh_text=FALLBACK_SENTENCE_ZH, en_text=FALLBACK_SENTENCE_EN,
        )

    if controller_result.status != "completed" or controller_result.action != "speak":
        return MultilingualAudioResult(zh_audio_path=None, en_audio_path=None)

    zh_path = _cached_gtts(brain_response.response_zh, "zh-TW") if brain_response.response_zh else None
    en_path = _cached_gtts(brain_response.response_en, "en") if brain_response.response_en else None
    return MultilingualAudioResult(
        zh_audio_path=zh_path, en_audio_path=en_path,
        zh_text=brain_response.response_zh, en_text=brain_response.response_en,
    )
