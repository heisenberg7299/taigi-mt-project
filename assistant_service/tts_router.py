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

## 強制全部用MERaLiON的選項(2026-10-19新增)

使用者實際確認過代價後(硬碟~2.7GB、RAM常駐~2.1GB、RTF比即時慢35倍)，
明確要求把assistant_service(port 5020)的台語語音輸出全部改用MERaLiON，
不要只靠approved_sentences這套智慧路由。用環境變數`ASSISTANT_SERVICE_
FORCE_MERALION=1`開啟，**預設不開**——不想承擔這個效能代價的人完全不受
影響，原本的智慧路由邏輯(規則1/2/3)一行都沒改，只是在前面多加一個
使用者自己選擇性開啟的覆蓋開關。開啟後每句話都要等好幾秒到十幾秒才會
出聲，這是已經讓使用者知情後的取捨，不是自動判斷「這樣比較好」。

## 快取key修正：同一句話要分backend各自快取(2026-10-19修正)

使用者實際回報「網頁版的聲音聽起來跟另一個比較工具不一樣」，追查發現
一個真實bug：原本`_cache_key()`只對文字內容算hash，**不管這句話是
neurlang還是MERaLiON生成的，快取檔名都一樣**。代表如果某句話在開啟
`ASSISTANT_SERVICE_FORCE_MERALION`**之前**就已經被neurlang生成過、
存進快取，開啟這個環境變數之後再問同一句話，會直接命中那個舊的
neurlang快取、完全不會重新呼叫MERaLiON——使用者以為自己在聽MERaLiON，
實際上聽到的是舊快取裡的neurlang聲音。

修正：快取key改成`hash(backend + ":" + text)`，同一句話在neurlang跟
MERaLiON底下會各自存成不同的快取檔案，不會互相蓋過或誤用對方的結果。
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


def _cache_key(backend: str, text: str) -> str:
    # backend一定要納入hash，不然同一句話在neurlang/MERaLiON底下會共用
    # 同一個快取檔案、互相蓋過對方的結果——見模組docstring「快取key修正」
    return hashlib.sha256(f"{backend}:{text}".encode("utf-8")).hexdigest()


def cached_audio_path(backend: str, text: str) -> Path | None:
    path = CACHE_DIR / f"{_cache_key(backend, text)}.wav"
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


def _force_meralion_enabled() -> bool:
    """見模組docstring「強制全部用MERaLiON的選項」。每次呼叫都重新讀環境
    變數(不快取成模組層級常數)，讓測試/重新設定時不需要reload模組。"""
    return os.environ.get("ASSISTANT_SERVICE_FORCE_MERALION") == "1"


def _call_backend(text: str, backend: str) -> bytes:
    port = BACKEND_PORTS[backend]
    resp = requests.post(f"http://127.0.0.1:{port}/synthesize", json={"han": text}, timeout=120)
    resp.raise_for_status()
    return resp.content


def route_and_synthesize(text: str) -> TTSRouteResult:
    # 先決定這句話「這次」該用哪個backend，再用backend-aware的key查/寫快取
    # ——不能反過來先查快取再決定backend，不然backend切換(approved清單
    # 變動、FORCE_MERALION開關)時會誤用另一個backend留下的舊快取檔案，
    # 見模組docstring「快取key修正」的真實案例。
    backend = "meralion" if (is_approved_common_sentence(text) or _force_meralion_enabled()) else "neurlang"

    cached = cached_audio_path(backend, text)
    if cached is not None:
        cached_label = "meralion_cached" if backend == "meralion" else "neurlang_cached"
        return TTSRouteResult(backend=cached_label, audio_path=cached, from_cache=True)

    out_path = CACHE_DIR / f"{_cache_key(backend, text)}.wav"
    audio_bytes = _call_backend(text, backend)
    out_path.write_bytes(audio_bytes)
    fresh_label = "meralion_fresh_cached" if backend == "meralion" else "neurlang_realtime"
    return TTSRouteResult(backend=fresh_label, audio_path=out_path, from_cache=False)
