"""
TTS 合成層。

MockTTSBackend: 不需要任何模型權重, 直接產生一段對應長度的靜音 WAV,
用來驗證整條 pipeline 是否能跑通、檔案是否正確輸出。

SpeechT5TailoBackend: 串接 huggingface 上的 speecht5_tailo-hokkien 系列
模型 (例如 Curiousfox/speecht5_tailo-hokkien_ver1.0.b), 需要額外安裝
transformers / torch / soundfile, 且模型輸入格式 (是否吃台羅字串、是否
需要額外的 speaker embedding) 應以該模型卡片 (model card) 上的說明為準,
使用前務必先在小範圍測試集上驗證發音正確性。
"""

from __future__ import annotations

import math
import struct
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TTSResult:
    text: str
    wav_path: Path
    backend_name: str
    sample_rate: int


class TTSBackend(ABC):
    name: str = "base"

    @abstractmethod
    def synthesize(self, tailo_text: str, out_path: Path) -> TTSResult:
        raise NotImplementedError


class MockTTSBackend(TTSBackend):
    """產生靜音 (或簡單音調) WAV, 僅用於驗證 pipeline 串接與檔案輸出。"""

    name = "mock"

    def __init__(self, sample_rate: int = 16000, seconds_per_syllable: float = 0.35):
        self.sample_rate = sample_rate
        self.seconds_per_syllable = seconds_per_syllable

    def synthesize(self, tailo_text: str, out_path: Path) -> TTSResult:
        n_syllables = max(1, len([s for s in tailo_text.split("-") if s]))
        duration = n_syllables * self.seconds_per_syllable
        n_frames = int(self.sample_rate * duration)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            # 產生極低音量的 440Hz 提示音, 而非完全靜音, 方便肉耳確認檔案有內容
            amplitude = 2000
            freq = 440.0
            frames = bytearray()
            for i in range(n_frames):
                value = int(amplitude * math.sin(2 * math.pi * freq * (i / self.sample_rate)))
                frames += struct.pack("<h", value)
            wav_file.writeframes(bytes(frames))

        return TTSResult(
            text=tailo_text,
            wav_path=out_path,
            backend_name=self.name,
            sample_rate=self.sample_rate,
        )


class SpeechT5TailoBackend(TTSBackend):
    """真實 SpeechT5 台羅/Hokkien TTS 串接骨架。

    使用前需要:
        pip install transformers torch soundfile sentencepiece

    並確認目標模型 (例如 speecht5_tailo-hokkien 系列) 的輸入是否直接吃
    台羅字串, 或需要先轉成該模型訓練時使用的音素表示法; 這需要參考模型
    卡片或直接詢問模型作者。
    """

    name = "speecht5"

    def __init__(self, model_id: str, vocoder_id: str, speaker_embedding_path: str | None = None):
        self.model_id = model_id
        self.vocoder_id = vocoder_id
        self.speaker_embedding_path = speaker_embedding_path
        self._pipeline = None  # 延遲載入

    def _ensure_loaded(self):
        if self._pipeline is not None:
            return
        from transformers import SpeechT5ForTextToSpeech, SpeechT5HifiGan, SpeechT5Processor

        self._processor = SpeechT5Processor.from_pretrained(self.model_id)
        self._model = SpeechT5ForTextToSpeech.from_pretrained(self.model_id)
        self._vocoder = SpeechT5HifiGan.from_pretrained(self.vocoder_id)
        self._pipeline = True

    def synthesize(self, tailo_text: str, out_path: Path) -> TTSResult:
        import numpy as np
        import soundfile as sf
        import torch

        self._ensure_loaded()

        inputs = self._processor(text=tailo_text, return_tensors="pt")

        if self.speaker_embedding_path:
            speaker_embeddings = torch.load(self.speaker_embedding_path)
        else:
            # TODO: 沒有指定 speaker embedding 時的預設值需依模型卡片建議調整,
            # 這裡先用隨機向量佔位, 正式使用前必須替換成合適的說話人向量
            speaker_embeddings = torch.randn(1, 512)

        speech = self._model.generate_speech(
            inputs["input_ids"], speaker_embeddings, vocoder=self._vocoder
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), speech.numpy().astype(np.float32), samplerate=16000)

        return TTSResult(
            text=tailo_text, wav_path=out_path, backend_name=self.name, sample_rate=16000
        )


def build_tts_backend(config) -> TTSBackend:
    if config.tts_backend == "mock":
        return MockTTSBackend()
    if config.tts_backend == "real":
        return SpeechT5TailoBackend(
            model_id=config.tts_model_id, vocoder_id=config.tts_vocoder_id
        )
    raise ValueError(f"未知的 tts_backend: {config.tts_backend}")
