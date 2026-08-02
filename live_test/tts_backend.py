"""
輕量TTS合成API：只做「台語漢字 -> wav音檔」，不做翻譯（那是 app.py 的事）。

neurlang跟MERaLiON要的transformers版本互斥（<5 vs >=5.3.0），沒辦法在同一個
venv/process裡同時載入，所以拆成獨立process各自用獨立venv跑，內部用port
讓 app.py 轉發過去，兩個都跑起來才能在同一個網站上切換兩種模式測試。

執行：
  # neurlang後端 -> 主venv (transformers<5)
  source venv/bin/activate
  TTS_BACKEND=neurlang python3 live_test/tts_backend.py

  # meralion後端 -> 獨立的venv_meralion (transformers>=5.3.0)
  source venv_meralion/bin/activate
  TTS_BACKEND=meralion python3 live_test/tts_backend.py
"""
import os
import uuid

from flask import Flask, jsonify, request, send_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "models", "neurlang-vits-suisiann")
VOICE_REF_AUDIO = os.path.join(ROOT, "tests", "voice_refs", "neurlang_ref_16k.wav")
VOICE_REF_TEXT = "阿媽，你這罐降血糖的欲囥佇冰櫥内底冷藏。"
TTS_BACKEND = os.environ.get("TTS_BACKEND", "neurlang")
DEFAULT_PORT = 5010 if TTS_BACKEND == "neurlang" else 5011
PORT = int(os.environ.get("PORT", DEFAULT_PORT))
TMP_DIR = "/tmp/taigi_tts_backend"

os.makedirs(TMP_DIR, exist_ok=True)

app = Flask(__name__)
_synth = None
_meralion_model = None
_meralion_voice_prompt = None


def _load():
    global _synth, _meralion_model, _meralion_voice_prompt
    if TTS_BACKEND == "meralion":
        import torch
        from omnivoice.models.omnivoice import OmniVoice
        _meralion_model = OmniVoice.from_pretrained(
            "MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS", device_map="cpu", dtype=torch.float32,
        )
        # voice clone成neurlang現有的聲音，兩個後端輸出音色才能直接比較
        _meralion_voice_prompt = _meralion_model.create_voice_clone_prompt(
            ref_audio=VOICE_REF_AUDIO, ref_text=VOICE_REF_TEXT,
        )
    else:
        from TTS.utils.synthesizer import Synthesizer
        _synth = Synthesizer(
            tts_checkpoint=os.path.join(MODEL_DIR, "best_model.pth"),
            tts_config_path=os.path.join(MODEL_DIR, "config.json"),
        )


@app.route("/synthesize", methods=["POST"])
def synthesize():
    han = (request.json or {}).get("han", "").strip()
    if not han:
        return jsonify({"error": "empty text"}), 400
    out_path = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}.wav")
    if TTS_BACKEND == "meralion":
        import soundfile as sf
        audios = _meralion_model.generate(text=han, language="nan", voice_clone_prompt=_meralion_voice_prompt)
        sf.write(out_path, audios[0], samplerate=_meralion_model.sampling_rate)
    else:
        wav = _synth.tts(han)
        _synth.save_wav(wav, out_path)
    return send_file(out_path, mimetype="audio/wav")


@app.route("/health")
def health():
    return jsonify({"backend": TTS_BACKEND, "status": "ok"})


if __name__ == "__main__":
    print(f"載入 {TTS_BACKEND} ...")
    _load()
    print(f"{TTS_BACKEND} 後端準備好了，內部port {PORT}（只給app.py內部轉發用，不用對外開放）")
    app.run(host="127.0.0.1", port=PORT, debug=False)
