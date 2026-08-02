"""
端對端測試工具：輸入任意中文句子，跑完整pipeline輸出台語語音。

中文 -> Taigi-Llama-2-Translator-7B(Ollama) -> 台語漢字 -> neurlang VITS -> 語音

用途：手動測試新句子，不用每次都寫一次性腳本。輸出的wav檔會自動用Finder
打開所在資料夾，方便直接聽。

前置需求：
- Ollama要在跑，且已經pull過 hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M
- venv要是 transformers<5（neurlang用coqui-tts的要求，如果剛用過MERaLiON
  記得先 pip install "transformers<5" 切回來）

執行：
  python scripts/zh_to_taigi_speech.py "你的中文句子"
  python scripts/zh_to_taigi_speech.py "句子1" "句子2" "句子3"   # 一次測多句
"""
import json
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = "hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_DIR = os.path.join(ROOT, "models", "neurlang-vits-suisiann")
OUT_DIR = "/tmp/zh_to_taigi_output"


def translate(zh):
    prompt = f"[TRANS]\n{zh}\n[/TRANS]\n[HAN]\n"
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "raw": True, "stream": False,
        "options": {"temperature": 0, "stop": ["[TRANS]", "</s>"]},
    }).encode("utf-8")
    resp = requests.post(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}, timeout=60)
    text = resp.json().get("response", "").strip()
    return re.sub(r"\[/?(HAN|POJ|HL|ZH|EN)\]\s*$", "", text).strip()


def main():
    sentences = sys.argv[1:]
    if not sentences:
        print('用法：python scripts/zh_to_taigi_speech.py "你的中文句子"')
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    print("載入 neurlang VITS...")
    from TTS.utils.synthesizer import Synthesizer
    syn = Synthesizer(
        tts_checkpoint=os.path.join(MODEL_DIR, "best_model.pth"),
        tts_config_path=os.path.join(MODEL_DIR, "config.json"),
    )

    results = []
    for i, zh in enumerate(sentences):
        print(f"\n翻譯中：{zh}")
        han = translate(zh)
        print(f"  台語漢字：{han}")
        wav = syn.tts(han)
        out_path = os.path.join(OUT_DIR, f"{i:02d}.wav")
        syn.save_wav(wav, out_path)
        print(f"  音檔：{out_path}")
        results.append({"zh": zh, "nan_han": han, "audio": out_path})

    print(f"\n完成，共 {len(results)} 句，全部在 {OUT_DIR}")
    os.system(f"open {OUT_DIR}")


if __name__ == "__main__":
    main()
