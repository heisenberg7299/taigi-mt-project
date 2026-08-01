import os
from .base import TTSAdapter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MODEL_DIR = os.path.join(ROOT, "models", "neurlang-vits-suisiann")


class NeurlangVitsAdapter(TTSAdapter):
    name = "neurlang-vits-suisiann"
    input_format = "han"
    required_frontend = "none"
    license = "cc-by-sa-4.0"

    def load(self):
        from TTS.utils.synthesizer import Synthesizer
        self.synth = Synthesizer(
            tts_checkpoint=os.path.join(MODEL_DIR, "best_model.pth"),
            tts_config_path=os.path.join(MODEL_DIR, "config.json"),
        )

    def synthesize(self, text: str):
        wav = self.synth.tts(text)
        import numpy as np
        return np.array(wav), 22050
