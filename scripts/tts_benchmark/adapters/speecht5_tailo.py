import io
import zipfile
from .base import TTSAdapter

MODEL_ID = "wenxinkoh06/speecht5_tailo_Hokkien_ver1.0.d"
XVECTOR_MEMBER = "spkrec-xvect/cmu_us_slt_arctic-wav-arctic_b0258.npy"


class SpeechT5TailoAdapter(TTSAdapter):
    name = "speecht5_tailo_Hokkien_ver1.0.d"
    input_format = "tailo"
    required_frontend = "hanji_to_tailo_g2p"
    license = "mit"

    def load(self):
        import torch
        import numpy as np
        from transformers import SpeechT5Processor, SpeechT5ForTextToSpeech, SpeechT5HifiGan
        from huggingface_hub import hf_hub_download

        self.torch = torch
        self.processor = SpeechT5Processor.from_pretrained("microsoft/speecht5_tts")
        self.model = SpeechT5ForTextToSpeech.from_pretrained(MODEL_ID)
        self.vocoder = SpeechT5HifiGan.from_pretrained("microsoft/speecht5_hifigan")

        # 這個repo沒有附自己訓練用的speaker embedding，用cmu-arctic-xvectors
        # 隨便挑一個當佔位（見 reports/stage4_tts_candidates.md 的說明：
        # 音色大概率不對，但足夠測試「有沒有正常發出語音」）。
        zip_path = hf_hub_download(
            repo_id="Matthijs/cmu-arctic-xvectors",
            repo_type="dataset",
            filename="spkrec-xvect.zip",
        )
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(XVECTOR_MEMBER) as f:
                xvec = np.load(io.BytesIO(f.read()))
        self.speaker_embeddings = torch.tensor(xvec).unsqueeze(0)

    def synthesize(self, text: str):
        inputs = self.processor(text=text, return_tensors="pt")
        speech = self.model.generate_speech(
            inputs["input_ids"], self.speaker_embeddings, vocoder=self.vocoder
        )
        return speech.numpy(), 16000
