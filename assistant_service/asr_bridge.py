"""
中英雙語語音輸入：包裝openai-whisper，自動偵測輸入語言(中文或英文)，不像
yuava22/Interactive-service-robots的asr.py那樣把language參數寫死成
"Chinese"(那個版本收到英文語音也會被逼著用中文解碼，準確度會掉)。

用Python API(`whisper.load_model()`+`model.transcribe()`)而不是像對方
repo那樣shell出去呼叫`python3 -m whisper` CLI：一來可以直接拿到whisper
自己偵測出的語言(`result["language"]`)，不用另外猜；二來模型只需要載入
一次(`load_model`有內建cache，但透過這裡的`_MODEL_CACHE`確保同一個
process內重複呼叫不會重複載入到記憶體)，重複呼叫subprocess每次都要重新
啟動Python直譯器+載入模型，對即時語音互動來說延遲太高。

這裡只負責「語音->文字+偵測到的語言」，不做意圖判斷——那是
voice_io_bridge.py(規則式快速路徑)或brain_llm.py(LLM大腦, 通用路徑)的
責任，兩者都只需要文字輸入，不需要知道語音本身怎麼來的。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL_SIZE = "base"

_MODEL_CACHE: dict[str, object] = {}


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    detected_language: str  # whisper的ISO語言代碼, 例如"zh"/"en"


def _get_model(model_size: str = DEFAULT_MODEL_SIZE):
    if model_size not in _MODEL_CACHE:
        import whisper

        _MODEL_CACHE[model_size] = whisper.load_model(model_size)
    return _MODEL_CACHE[model_size]


def transcribe_bilingual(wav_path: str | Path, model_size: str = DEFAULT_MODEL_SIZE) -> TranscriptionResult:
    """自動偵測中文或英文並轉成文字。不強制指定language參數，讓whisper自己
    判斷——這是跟yuava22原本asr.py(language寫死"Chinese")最主要的差異，
    也是使用者要求「中英文語音輸入」的核心：病人/家屬用中文或英文講話都
    要能正確辨識，不能只支援中文。"""
    model = _get_model(model_size)
    result = model.transcribe(str(wav_path))
    text = (result.get("text") or "").strip()
    detected_language = result.get("language", "")
    return TranscriptionResult(text=text, detected_language=detected_language)
