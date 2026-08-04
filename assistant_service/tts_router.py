"""
TTS Router：決定要用neurlang即時生成還是MERaLiON快取/預生成。

路由規則：
  1. 這句話之前生成過、快取裡已經有 -> 直接回傳快取的音檔路徑
  2. 這句話在「已審核常用句清單」(approved_sentences.json)裡 -> 用MERaLiON
     生成(較慢但品質較好；因為是會重複用到的固定句，值得先花時間生成
     一次再存進快取，之後同一句話就變成規則1直接命中快取)
  3. 其餘(動態、當場生成的一般句子) -> 用neurlang即時生成(快，適合即時互動)

重用 live_test/tts_backend.py 已經驗證過的內部API(127.0.0.1:5010=neurlang,
:5011=meralion)，不重新發明TTS呼叫邏輯——這兩個process要先手動啟動好
(見live_test/README或scripts/start_live_test.sh)。

MERaLiON即時生成(RTF=3.63，比即時慢35倍，見reports/stage4_tts_candidates.md)
只適合用在「预先生成、之後重複命中快取」的固定句，不適合每次都即時呼叫，
所以這裡故意只有approved_sentences才會觸發MERaLiON合成，其餘一律neurlang。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import requests

BACKEND_PORTS = {"neurlang": 5010, "meralion": 5011}

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = Path(os.path.join(_HERE, "cache", "audio"))
APPROVED_SENTENCES_PATH = Path(os.path.join(_HERE, "cache", "approved_sentences.json"))

CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TTSRouteResult:
    backend: str  # "meralion_cached" / "meralion_fresh_cached" / "neurlang_realtime"
    audio_path: Path
    from_cache: bool


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cached_audio_path(text: str) -> Path | None:
    path = CACHE_DIR / f"{_cache_key(text)}.wav"
    return path if path.exists() else None


def load_approved_sentences() -> set[str]:
    """已審核過、值得用MERaLiON預生成+快取的常用句清單。這份清單目前是
    空的demo檔案，實際要放哪些句子需要由台語專業人士審核過的固定回覆
    決定(例如固定的安全警語、常見問候語)，不是隨便什麼句子都適合預先
    花35倍時間生成快取。"""
    if not APPROVED_SENTENCES_PATH.exists():
        return set()
    with open(APPROVED_SENTENCES_PATH, encoding="utf-8") as f:
        return set(json.load(f))


def is_approved_common_sentence(text: str) -> bool:
    return text in load_approved_sentences()


def _call_backend(text: str, backend: str) -> bytes:
    port = BACKEND_PORTS[backend]
    resp = requests.post(f"http://127.0.0.1:{port}/synthesize", json={"han": text}, timeout=120)
    resp.raise_for_status()
    return resp.content


def route_and_synthesize(text: str) -> TTSRouteResult:
    cached = cached_audio_path(text)
    if cached is not None:
        return TTSRouteResult(backend="meralion_cached", audio_path=cached, from_cache=True)

    out_path = CACHE_DIR / f"{_cache_key(text)}.wav"

    if is_approved_common_sentence(text):
        audio_bytes = _call_backend(text, "meralion")
        out_path.write_bytes(audio_bytes)
        return TTSRouteResult(backend="meralion_fresh_cached", audio_path=out_path, from_cache=False)

    audio_bytes = _call_backend(text, "neurlang")
    # 動態句子也寫進同一個快取資料夾(用內容雜湊當檔名)，這樣如果剛好被
    # 使用者問到同一句兩次，第二次一樣直接命中快取，不用重新呼叫neurlang；
    # 這跟「approved_sentences」是兩件事——這裡只是省重複運算，不代表這句
    # 話被人工審核過。
    out_path.write_bytes(audio_bytes)
    return TTSRouteResult(backend="neurlang_realtime", audio_path=out_path, from_cache=False)
