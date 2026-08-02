"""
開發者自用的即時測試平台：瀏覽器輸入任意中文句子，選擇neurlang或MERaLiON，
馬上看到完整pipeline的翻譯結果+可播放的台語語音。

跟 docs/（給母語者測試者用的驗證平台，GitHub Pages上，只能對事先產生好的
200句打分）不一樣：這裡是給開發者自己測、句子當場輸入當場生成。

中文 -> Taigi-Llama-2-Translator-7B(Ollama) -> 台語漢字 -> neurlang/MERaLiON語音

架構：這個app本身只做翻譯(呼叫Ollama)，不直接載入任何TTS模型，而是把台語
漢字轉發給 tts_backend.py 開的內部API(127.0.0.1:5010=neurlang, :5011=meralion)。
這樣拆是因為兩個TTS引擎要的transformers版本互斥，沒辦法同一個process同時
載入，拆成獨立venv/process後才能在同一個網站上讓使用者自由切換兩種模式。

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
import uuid

import requests
from flask import Flask, render_template, request

MODEL = "hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/generate"
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "audio")
BACKEND_PORTS = {"neurlang": 5010, "meralion": 5011}
BACKEND_LABELS = {
    "neurlang": "neurlang（快，目前正式在跑的方法）",
    "meralion": "MERaLiON（品質較好，但比即時慢約35倍，生成需數十秒）",
}

os.makedirs(AUDIO_DIR, exist_ok=True)
app = Flask(__name__)


def translate(zh):
    prompt = f"[TRANS]\n{zh}\n[/TRANS]\n[HAN]\n"
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "raw": True, "stream": False,
        "options": {"temperature": 0, "stop": ["[TRANS]", "</s>"]},
    }).encode("utf-8")
    resp = requests.post(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}, timeout=60)
    text = resp.json().get("response", "").strip()
    return re.sub(r"\[/?(HAN|POJ|HL|ZH|EN)\]\s*$", "", text).strip()


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
    zh = ""
    backend = request.values.get("backend", "neurlang")
    if backend not in BACKEND_PORTS:
        backend = "neurlang"
    if request.method == "POST":
        zh = request.form.get("zh", "").strip()
        if not zh:
            error = "請輸入中文句子"
        else:
            try:
                han = translate(zh)
                filename = synthesize(han, backend)
                result = {"zh": zh, "han": han, "audio_url": f"/static/audio/{filename}", "backend": backend}
            except requests.exceptions.ConnectionError as exc:
                if "11434" in str(exc):
                    error = "連不到 Ollama，請確認 Ollama 有在跑（ollama serve）"
                else:
                    error = f"連不到「{backend}」後端，請確認對應的 tts_backend.py 有啟動（見 app.py 檔頭說明）"
            except Exception as exc:
                error = f"發生錯誤：{exc}"
    return render_template(
        "index.html", result=result, error=error, zh=zh,
        backend=backend, backend_labels=BACKEND_LABELS,
    )


if __name__ == "__main__":
    print("準備好了。")
    print("本機瀏覽器：http://127.0.0.1:5002")
    print("同網路其他裝置：http://<這台Mac的區網IP>:5002")
    app.run(host="0.0.0.0", port=5002, debug=False)
