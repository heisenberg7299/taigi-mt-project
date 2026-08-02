"""
測試 MERaLiON-OmniVoice-Hokkien-TTS 能不能用「同一個聲音」自然處理
中台混讀（例如「你對盤尼西林敢會過敏？」這種嵌入中文專有名詞的台語句）。

注意：這個套件(omnivoice)要求 transformers>=5.3.0，跟neurlang VITS用的
coqui-tts（要求transformers<5）版本衝突，不能在同一個venv session裡
兩個都import——所以這支腳本只测MERaLiON本身，用「已經先產生好的neurlang
音檔」當voice clone參考（不在這支腳本裡重新呼叫coqui-tts）。

執行：python scripts/test_meralion.py
"""
import time

import soundfile as sf
import torch
from omnivoice.models.omnivoice import OmniVoice

OUT_DIR = "/tmp/meralion_test"


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)

    print("載入模型...")
    t0 = time.time()
    model = OmniVoice.from_pretrained(
        "MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS",
        device_map="cpu",
        dtype=torch.float32,
    )
    print(f"  完成，{time.time()-t0:.1f}s")

    test_sentences = [
        "你對盤尼西林敢會過敏？",
        "阿媽，你這罐胰島素愛囥冰箱冷凍。",
        "王小明先生，你的抽血報告出來矣。",
    ]

    # 測試1：用模型自帶的參考語音
    print("\n=== 用內建參考語音 ===")
    builtin_ref_text = open(
        os.path.expanduser(
            "~/.cache/huggingface/hub/models--MERaLiON--MERaLiON-OmniVoice-Hokkien-TTS/"
            "snapshots/cd2fa70a18dd464dec4a429aedd5606c75985533/reference_audio/reference_text.txt"
        )
    ).read().strip()
    builtin_ref_audio = os.path.expanduser(
        "~/.cache/huggingface/hub/models--MERaLiON--MERaLiON-OmniVoice-Hokkien-TTS/"
        "snapshots/cd2fa70a18dd464dec4a429aedd5606c75985533/reference_audio/reference_audio.wav"
    )
    t0 = time.time()
    builtin_prompt = model.create_voice_clone_prompt(ref_audio=builtin_ref_audio, ref_text=builtin_ref_text)
    print(f"  建立voice prompt: {time.time()-t0:.1f}s")

    for i, text in enumerate(test_sentences):
        t0 = time.time()
        audios = model.generate(text=text, language="nan", voice_clone_prompt=builtin_prompt)
        out_path = f"{OUT_DIR}/builtin_ref_{i:02d}.wav"
        sf.write(out_path, audios[0], model.sampling_rate)
        print(f"  [{text}] -> {out_path} ({time.time()-t0:.1f}s)")

    # 測試2：用我們自己的neurlang音檔當voice clone參考
    print("\n=== 用neurlang自己的語音當參考 ===")
    neurlang_ref_audio = "/tmp/neurlang_ref_16k.wav"
    neurlang_ref_text = "阿媽，你這罐降血糖的欲囥佇冰櫥内底冷藏。"
    t0 = time.time()
    neurlang_prompt = model.create_voice_clone_prompt(ref_audio=neurlang_ref_audio, ref_text=neurlang_ref_text)
    print(f"  建立voice prompt: {time.time()-t0:.1f}s")

    for i, text in enumerate(test_sentences):
        t0 = time.time()
        audios = model.generate(text=text, language="nan", voice_clone_prompt=neurlang_prompt)
        out_path = f"{OUT_DIR}/neurlang_ref_{i:02d}.wav"
        sf.write(out_path, audios[0], model.sampling_rate)
        print(f"  [{text}] -> {out_path} ({time.time()-t0:.1f}s)")

    print(f"\n完成，全部在 {OUT_DIR}")


if __name__ == "__main__":
    main()
