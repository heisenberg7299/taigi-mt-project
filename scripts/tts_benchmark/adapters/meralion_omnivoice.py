"""
MERaLiON-OmniVoice-Hokkien-TTS adapter。

注意：這個adapter需要 transformers>=5.3.0（omnivoice套件的要求），
跟其他adapter用的coqui-tts（要求transformers<5）在同一個venv session
會版本衝突，不能跟 neurlang_vits.py / speecht5_tailo*.py 在同一次
`run_tts_benchmark.py`執行裡一起跑。要測這個adapter，先
`pip install "transformers>=5.3.0"`，用單獨的進入點跑（見
scripts/run_tts_benchmark_meralion.py），跑完要測其他adapter記得
`pip install "transformers<5"` 切回來。

授權：MIT License + OpenAI Whisper-Large-V3 Community License Agreement，
沒有非商業限制，只需要在產品/服務裡放致謝聲明（見
reports/stage4_tts_candidates.md 的授權章節）。
"""
import os

from .base import TTSAdapter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
VOICE_REF_AUDIO = os.path.join(ROOT, "tests", "voice_refs", "neurlang_ref_16k.wav")
VOICE_REF_TEXT = "阿媽，你這罐降血糖的欲囥佇冰櫥内底冷藏。"


class MeralionOmnivoiceAdapter(TTSAdapter):
    name = "meralion-omnivoice-hokkien"
    input_format = "han"
    required_frontend = "none"
    license = "mit + openai-whisper-large-v3-community-license（無非商業限制，需放致謝聲明）"

    def load(self):
        import torch
        from omnivoice.models.omnivoice import OmniVoice

        self.model = OmniVoice.from_pretrained(
            "MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS", device_map="cpu", dtype=torch.float32,
        )
        # voice clone成neurlang現有的聲音，讓兩個模型的輸出音色可以直接比較
        # （開發者聽過確認「蠻像的」，見報告）
        self.voice_prompt = self.model.create_voice_clone_prompt(
            ref_audio=VOICE_REF_AUDIO, ref_text=VOICE_REF_TEXT,
        )

    def synthesize(self, text: str):
        audios = self.model.generate(text=text, language="nan", voice_clone_prompt=self.voice_prompt)
        return audios[0], self.model.sampling_rate
