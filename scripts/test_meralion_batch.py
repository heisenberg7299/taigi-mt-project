"""
用MERaLiON + neurlang聲音複製，跑一批更多句子，測試泛化狀況
（第一輪只測3句看起來可行，這輪擴大到10句「不在200句測試集裡」的
新句子，來自 reports/safety_critical_translation_failures.md 那批）。

執行：python scripts/test_meralion_batch.py
"""
import json
import os
import time

import soundfile as sf
import torch
from omnivoice.models.omnivoice import OmniVoice

OUT_DIR = "/tmp/meralion_batch_test"
NEURLANG_REF_AUDIO = "/tmp/neurlang_ref_16k.wav"
NEURLANG_REF_TEXT = "阿媽，你這罐降血糖的欲囥佇冰櫥内底冷藏。"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sentences = [json.loads(l)["nan_han"] if False else r["nan_han"]
                 for r in json.load(open("/tmp/novel_translations.json"))]

    print("載入模型...")
    model = OmniVoice.from_pretrained(
        "MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS", device_map="cpu", dtype=torch.float32,
    )
    prompt = model.create_voice_clone_prompt(ref_audio=NEURLANG_REF_AUDIO, ref_text=NEURLANG_REF_TEXT)

    for i, text in enumerate(sentences):
        t0 = time.time()
        audios = model.generate(text=text, language="nan", voice_clone_prompt=prompt)
        out_path = f"{OUT_DIR}/{i:02d}.wav"
        sf.write(out_path, audios[0], model.sampling_rate)
        print(f"[{i:02d}] {text} -> {out_path} ({time.time()-t0:.1f}s)")

    print(f"\n完成，全部在 {OUT_DIR}")


if __name__ == "__main__":
    main()
