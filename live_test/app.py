"""
開發者自用的即時測試平台：瀏覽器輸入任意中文句子，選擇neurlang或MERaLiON，
馬上看到完整pipeline的翻譯結果+可播放的台語語音。也可以選擇要不要套用
Adaptive Protected Token(雙路翻譯+安全檢查選擇+候選C)安全機制。

跟 docs/（給母語者測試者用的驗證平台，GitHub Pages上，只能對事先產生好的
200句打分）不一樣：這裡是給開發者自己測、句子當場輸入當場生成。

中文 -> [簡單版: 直接Ollama翻譯 / Adaptive: Protected Token+雙路+安全檢查]
     -> 台語漢字 -> neurlang/MERaLiON語音

架構：這個app本身只做翻譯，不直接載入任何TTS模型，而是把台語漢字轉發給
tts_backend.py 開的內部API(127.0.0.1:5010=neurlang, :5011=meralion)。
這樣拆是因為兩個TTS引擎要的transformers版本互斥，沒辦法同一個process同時
載入，拆成獨立venv/process後才能在同一個網站上讓使用者自由切換兩種模式。

Adaptive模式重用 tw_hokkien_tts_pipeline/adaptive_translation.py 的
translate_with_structured_fallback()(A->B->C->fail closed)，跟
scripts/eval_translation_safety.py 用同一份Protected Token詞庫(藥名/人名)，
所以句子裡如果剛好含有「盤尼西林」「王小明」這類已收錄的詞才會觸發保護，
其餘句子等同直接翻譯。**這裡沒有structured_intent輸入(那需要結構化表單，
不是自由輸入文字能自動判斷的)，所以候選C實際上不會被觸發，只會用到候選
A/B**，這點在畫面上會註明。

前置需求（三個都要先啟動，各自在自己的終端機視窗）：
  1. ollama serve（且已pull過 hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M）
  2. source venv/bin/activate && TTS_BACKEND=neurlang python3 live_test/tts_backend.py
  3. source venv_meralion/bin/activate && TTS_BACKEND=meralion python3 live_test/tts_backend.py

再啟動這個gateway（用主venv即可，只需要flask+requests）：
  source venv/bin/activate
  python3 live_test/app.py

本機瀏覽器開 http://127.0.0.1:5002
同一個Wi-Fi的其他裝置開 http://<這台Mac的區網IP>:5002（因為綁0.0.0.0）
要給外部網路連：另外跑 cloudflared tunnel --url http://localhost:5002
"""
import json
import os
import re
import sys
import uuid

import requests
from flask import Flask, render_template, request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.eval_translation_safety import DRUG_LEXICON, PERSON_NAMES  # noqa: E402
from tw_hokkien_tts_pipeline.adaptive_translation import (  # noqa: E402
    UnsafeTranslationError,
    translate_with_structured_fallback,
)
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard  # noqa: E402
from tw_hokkien_tts_pipeline.structured_renderer import StructuredMedicalRenderer  # noqa: E402
from tw_hokkien_tts_pipeline.translate import TaigiLlamaTranslationBackend  # noqa: E402

MODEL = "hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/generate"
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "audio")
BACKEND_PORTS = {"neurlang": 5010, "meralion": 5011}
BACKEND_LABELS = {
    "neurlang": "neurlang",
    "meralion": "MERaLiON",
}
STRATEGY_LABELS = {
    "simple": "簡單版（直接翻譯，無保護）",
    "adaptive": "Adaptive Protected Token（藥名/人名保護+安全檢查）",
}

os.makedirs(AUDIO_DIR, exist_ok=True)
app = Flask(__name__)

_guard = ProtectedTokenGuard(drug_lexicon=DRUG_LEXICON, person_names=PERSON_NAMES)
_adaptive_backend = TaigiLlamaTranslationBackend()
_renderer = StructuredMedicalRenderer()


def translate(zh):
    prompt = f"[TRANS]\n{zh}\n[/TRANS]\n[HAN]\n"
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "raw": True, "stream": False,
        "options": {"temperature": 0, "stop": ["[TRANS]", "</s>"]},
    }).encode("utf-8")
    resp = requests.post(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}, timeout=60)
    text = resp.json().get("response", "").strip()
    return re.sub(r"\[/?(HAN|POJ|HL|ZH|EN)\]\s*$", "", text).strip()


def translate_adaptive_for_ui(zh):
    """回傳 (han, info)，info是要顯示在畫面上的Protected Token除錯資訊，
    或是丟出 UnsafeTranslationError(呼叫方負責接住並顯示成"已被安全機制擋下")。"""
    result = translate_with_structured_fallback(
        zh, _guard, _adaptive_backend, structured_intent=None, structured_renderer=_renderer,
    )
    info = {
        "chosen": result.chosen,
        "masked_text": result.mask_result.masked_text,
        "protected_spans": [
            {"kind": s.kind, "original": s.original, "placeholder": s.placeholder}
            for s in result.mask_result.spans
        ],
    }
    return result.hanji_text, info


def synthesize(han, backend):
    port = BACKEND_PORTS[backend]
    resp = requests.post(f"http://127.0.0.1:{port}/synthesize", json={"han": han}, timeout=120)
    resp.raise_for_status()
    filename = f"{uuid.uuid4().hex}.wav"
    with open(os.path.join(AUDIO_DIR, filename), "wb") as f:
        f.write(resp.content)
    return filename


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    blocked = None
    zh = ""
    backend = request.values.get("backend", "neurlang")
    if backend not in BACKEND_PORTS:
        backend = "neurlang"
    strategy = request.values.get("strategy", "simple")
    if strategy not in STRATEGY_LABELS:
        strategy = "simple"

    if request.method == "POST":
        zh = request.form.get("zh", "").strip()
        if not zh:
            error = "請輸入中文句子"
        else:
            try:
                adaptive_info = None
                if strategy == "adaptive":
                    try:
                        han, adaptive_info = translate_adaptive_for_ui(zh)
                    except UnsafeTranslationError as exc:
                        blocked = {
                            "message": "Adaptive Protected Token兩個候選都沒通過安全檢查，已阻擋合成(fail closed)",
                            "raw_candidate": exc.raw_candidate.hanji_text,
                            "raw_missing": exc.raw_candidate.missing_entities,
                            "masked_candidate": exc.masked_candidate.hanji_text,
                            "masked_missing": exc.masked_candidate.missing_entities,
                        }
                        han = None
                else:
                    han = translate(zh)

                if han is not None:
                    filename = synthesize(han, backend)
                    result = {
                        "zh": zh, "han": han, "audio_url": f"/static/audio/{filename}",
                        "backend": backend, "strategy": strategy, "adaptive_info": adaptive_info,
                    }
            except requests.exceptions.ConnectionError as exc:
                if "11434" in str(exc):
                    error = "連不到 Ollama，請確認 Ollama 有在跑（ollama serve）"
                else:
                    error = f"連不到「{backend}」後端，請確認對應的 tts_backend.py 有啟動（見 app.py 檔頭說明）"
            except Exception as exc:
                error = f"發生錯誤：{exc}"
    return render_template(
        "index.html", result=result, error=error, blocked=blocked, zh=zh,
        backend=backend, backend_labels=BACKEND_LABELS,
        strategy=strategy, strategy_labels=STRATEGY_LABELS,
    )


if __name__ == "__main__":
    print("準備好了。")
    print("本機瀏覽器：http://127.0.0.1:5002")
    print("同網路其他裝置：http://<這台Mac的區網IP>:5002")
    app.run(host="0.0.0.0", port=5002, debug=False)
