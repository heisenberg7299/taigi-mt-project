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
    """值得用MERaLiON預生成+快取的常用句清單。

    2026-09-10前這份清單一直是空的demo檔案，代表雖然「常用句用高品質引擎
    快取」這個路由機制存在，實際上從來沒有任何句子真的觸發過MERaLiON，
    正式輸出永遠都是neurlang——等於這個機制寫好了卻完全沒生效。

    這次補上4句：規則式快速路徑(`voice_io_bridge.py`/yuava22
    `intent_rules.py`)3種固定意圖(喝水/如廁/求助)的中文回覆，實際跑過
    `TaigiLlamaTranslationBackend`(temperature=0，兩次呼叫結果一致確認
    過)得到的台語翻譯結果，加上`response_controller.py`的固定棄權回覆
    (`FALLBACK_SENTENCE_HAN`)。

    **實測後發現的重要修正**：`FALLBACK_SENTENCE_HAN`那句實際上**完全
    不會走這個router**——`response_controller._fail_safe()`直接指到
    `fallback_audio/notify_nurse.wav`這個預先生成好的靜態檔案(見
    `response_controller.py`的`FALLBACK_AUDIO_PATH`)，`is_approved_
    common_sentence()`根本不會被呼叫到。放進這份清單目前**沒有實際效果
    **，純粹是為了將來如果`_fail_safe()`改走router時已經預先準備好；
    真正有效的是另外3句(喝水/如廁/求助)，已經實測確認會真的觸發MERaLiON
    (見`assistant_service/tests/test_tts_router.py`跟2026-09-10手動
    curl測試：`/api/interact`問「我要喝水」後，MERaLiON backend的log
    真的收到一次`POST /synthesize`——這是這個路由機制寫出來以後第一次
    真的被觸發)。

    **誠實揭露，不是「已審核」**：這4句台語文字本身的用字/發音**都還沒有
    經過台語母語者審核**，跟`response_controller.py`裡棄權句自己承認的
    限制一樣——只是「值得預先花時間生成快取的高頻固定句」，不代表內容
    已經確認正確。另外「如廁」那句的翻譯結果是「鬥相共」(互相幫忙)，
    語意上比較接近「求助」而不是「協助如廁」，是翻譯模型本身品質問題
    (跟`reports/safety_critical_translation_failures.md`記錄的翻譯失真
    是同一類問題)，這裡先如實記錄下來，沒有為了湊清單而调整或美化，
    之後要修這個字典層級的翻譯品質問題不是這裡的範圍。"""
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
