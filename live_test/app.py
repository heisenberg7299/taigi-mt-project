"""
開發者自用的即時測試平台：瀏覽器輸入任意中文句子，馬上看到完整pipeline的
翻譯結果+可播放的台語語音，不用每次都下指令跑 scripts/zh_to_taigi_speech.py。

跟 docs/（給母語者測試者用的驗證平台，GitHub Pages上，只能對事先產生好的
200句打分）不一樣：這裡是給開發者自己測、句子當場輸入當場生成、只在本機跑。

中文 -> Taigi-Llama-2-Translator-7B(Ollama) -> 台語漢字 -> neurlang VITS -> 語音

前置需求：
- Ollama要在跑，且已經pull過 hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M
- venv要是 transformers<5（neurlang用coqui-tts的要求，如果剛用過MERaLiON
  記得先 pip install "transformers<5" 切回來）

執行：
  source venv/bin/activate
  python3 live_test/app.py
  瀏覽器開 http://127.0.0.1:5002
"""
import json
import os
import re
import uuid

import requests
from flask import Flask, render_template, request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = "hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_DIR = os.path.join(ROOT, "models", "neurlang-vits-suisiann")
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "audio")

os.makedirs(AUDIO_DIR, exist_ok=True)

app = Flask(__name__)
synthesizer = None


def translate(zh):
    prompt = f"[TRANS]\n{zh}\n[/TRANS]\n[HAN]\n"
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "raw": True, "stream": False,
        "options": {"temperature": 0, "stop": ["[TRANS]", "</s>"]},
    }).encode("utf-8")
    resp = requests.post(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}, timeout=60)
    text = resp.json().get("response", "").strip()
    return re.sub(r"\[/?(HAN|POJ|HL|ZH|EN)\]\s*$", "", text).strip()


def get_synthesizer():
    global synthesizer
    if synthesizer is None:
        from TTS.utils.synthesizer import Synthesizer
        synthesizer = Synthesizer(
            tts_checkpoint=os.path.join(MODEL_DIR, "best_model.pth"),
            tts_config_path=os.path.join(MODEL_DIR, "config.json"),
        )
    return synthesizer


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    zh = ""
    if request.method == "POST":
        zh = request.form.get("zh", "").strip()
        if not zh:
            error = "請輸入中文句子"
        else:
            try:
                han = translate(zh)
                syn = get_synthesizer()
                wav = syn.tts(han)
                filename = f"{uuid.uuid4().hex}.wav"
                syn.save_wav(wav, os.path.join(AUDIO_DIR, filename))
                result = {"zh": zh, "han": han, "audio_url": f"/static/audio/{filename}"}
            except requests.exceptions.ConnectionError:
                error = "連不到 Ollama，請確認 Ollama 有在跑（ollama serve）"
            except Exception as exc:
                error = f"發生錯誤：{exc}"
    return render_template("index.html", result=result, error=error, zh=zh)


if __name__ == "__main__":
    print("載入 neurlang VITS...")
    get_synthesizer()
    print("準備好了，開瀏覽器：http://127.0.0.1:5002")
    app.run(host="127.0.0.1", port=5002, debug=False)
