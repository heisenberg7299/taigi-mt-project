"""
把 Baseline 2（Taigi-Llama）產生的200句候選台語漢字翻譯，
用 neurlang/coqui-vits-suisiann-minnan-hokkien 合成音檔，
給驗證平台播放，讓母語者不只看字、還能聽發音。

執行：
  source venv/bin/activate
  python scripts/synthesize_audio.py
"""
import json
import os
import time

from TTS.utils.synthesizer import Synthesizer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "tests", "baseline_taigi_llama.jsonl")
AUDIO_DIR = os.path.join(ROOT, "tests", "audio")
MODEL_DIR = os.path.join(ROOT, "models", "neurlang-vits-suisiann")


def main():
    os.makedirs(AUDIO_DIR, exist_ok=True)
    rows = [json.loads(l) for l in open(BASELINE)]

    print("載入 VITS 模型...")
    t0 = time.time()
    syn = Synthesizer(
        tts_checkpoint=os.path.join(MODEL_DIR, "best_model.pth"),
        tts_config_path=os.path.join(MODEL_DIR, "config.json"),
    )
    print(f"  模型載入完成，耗時 {time.time()-t0:.1f}s")

    ok, fail = 0, 0
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        text = r.get("baseline_taigi_llama_han")
        out_path = os.path.join(AUDIO_DIR, f"{r['id']}.wav")
        if not text:
            fail += 1
            continue
        if os.path.exists(out_path):
            ok += 1
            continue
        try:
            wav = syn.tts(text)
            syn.save_wav(wav, out_path)
            ok += 1
        except Exception as e:
            print(f"  [{i}/{len(rows)}] {r['id']} 合成失敗: {e}")
            fail += 1
        if i % 20 == 0 or i == len(rows):
            print(f"  [{i}/{len(rows)}] 完成，耗時 {time.time()-t0:.0f}s")

    print(f"完成。成功 {ok}，失敗 {fail}。音檔存在 {AUDIO_DIR}")


if __name__ == "__main__":
    main()
