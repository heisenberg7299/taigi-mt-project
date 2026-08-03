"""
TTS 合成層。

MockTTSBackend: 不需要任何模型權重, 直接產生一段對應長度的靜音 WAV,
用來驗證整條 pipeline 是否能跑通、檔案是否正確輸出。

NeurlangTTSBackend: 正式後端, 串接 `neurlang/coqui-vits-suisiann-minnan-hokkien`
(這個repo `live_test/tts_backend.py` 已經驗證過能實際出聲的同一個模型)。
輸入格式是**台語漢字**, 不是台羅——這個模型內建 pygoruut phonemizer 會自己
把漢字轉成 IPA 音素, 直接餵台羅字串不是它訓練時看過的格式。詳見下方類別
docstring。

SpeechT5TailoBackend: 串接 huggingface 上的 speecht5_tailo-hokkien 系列
模型 (例如 Curiousfox/speecht5_tailo-hokkien_ver1.0.b), 需要額外安裝
transformers / torch / soundfile, 且模型輸入格式 (是否吃台羅字串、是否
需要額外的 speaker embedding) 應以該模型卡片 (model card) 上的說明為準,
使用前務必先在小範圍測試集上驗證發音正確性。**這個backend目前還是骨架,
沒有實際驗證過。**
"""

from __future__ import annotations

import math
import struct
import time
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .audio_metrics import read_wav_metrics


@dataclass
class TTSInput:
    """TTS backend 要吃哪一種格式由 backend 自己決定, pipeline 層兩種都準備好,
    不假設「pipeline最後產生的台羅」一定是每個TTS模型能接受的格式。"""

    hanji_text: str  # 翻譯後台語漢字, Protected Token 已還原成原文寫法
    tailo_text: str  # 正規化後台羅字串, Protected Token 已還原成台羅讀音


@dataclass
class TTSResult:
    text: str  # 實際送進模型的文字
    text_format: str  # "hanji" 或 "tailo"：這次實際用的是哪一種格式
    wav_path: Path
    backend_name: str
    sample_rate: int
    model_id: str | None = None
    inference_sec: float | None = None
    duration_sec: float | None = None
    non_silence_ratio: float | None = None


class TTSBackend(ABC):
    name: str = "base"

    @abstractmethod
    def synthesize(self, tts_input: TTSInput, out_path: Path) -> TTSResult:
        raise NotImplementedError


class MockTTSBackend(TTSBackend):
    """產生提示音 (非完全靜音) WAV, 僅用於驗證 pipeline 串接與檔案輸出,
    **不是真的語音**。固定使用 tailo_text 只是為了估計音節數決定長度,
    跟真實TTS選哪種輸入格式無關。"""

    name = "mock"

    def __init__(self, sample_rate: int = 16000, seconds_per_syllable: float = 0.35):
        self.sample_rate = sample_rate
        self.seconds_per_syllable = seconds_per_syllable

    def synthesize(self, tts_input: TTSInput, out_path: Path) -> TTSResult:
        text = tts_input.tailo_text
        n_syllables = max(1, len([s for s in text.split("-") if s]))
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
            text=text,
            text_format="tailo",
            wav_path=out_path,
            backend_name=self.name,
            sample_rate=self.sample_rate,
            model_id="mock-beep-generator",
            inference_sec=0.0,
        )


class NeurlangTTSBackend(TTSBackend):
    """正式後端：`neurlang/coqui-vits-suisiann-minnan-hokkien`，跟這個repo
    `live_test/tts_backend.py` 用的是同一套已驗證程式碼路徑
    (`TTS.utils.synthesizer.Synthesizer` + 模型內建 pygoruut phonemizer)，
    模型路徑常數也沿用同一個慣例，不重新猜測模型用法。

    **輸入格式是台語漢字, 不是台羅**：這個模型訓練/推論時吃的是漢字,
    內建 phonemizer 自己轉成 IPA 音素合成——這點在 `reports/tts_oov_audit.md`
    反覆驗證過(pygoruut轉不出來的送氣/鼻化符號會被丟棄, 但輸入格式本身是
    漢字)。所以這個backend固定使用 `tts_input.hanji_text`, 忽略 tailo_text。

    需要 `transformers<5`(coqui-tts的要求), 跟MERaLiON要的`transformers>=5.3.0`
    互斥。若目前環境版本不對或模型權重不存在, 會丟出清楚的例外, **不會偷偷
    fallback 成 mock 提示音**——避免使用者誤以為真的合成成功了。
    """

    name = "neurlang"
    model_id = "neurlang/coqui-vits-suisiann-minnan-hokkien"

    # 跟 live_test/tts_backend.py 同一個慣例：這個檔案在
    # tw_hokkien_tts_pipeline/tts.py，repo 根目錄是往上一層
    _DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "neurlang-vits-suisiann"

    def __init__(self, model_dir: str | Path | None = None):
        self.model_dir = Path(model_dir) if model_dir else self._DEFAULT_MODEL_DIR
        self._synth = None

    def _ensure_loaded(self) -> None:
        if self._synth is not None:
            return

        checkpoint = self.model_dir / "best_model.pth"
        config_path = self.model_dir / "config.json"
        if not checkpoint.exists() or not config_path.exists():
            raise FileNotFoundError(
                f"找不到neurlang模型權重: {self.model_dir}\n"
                "需要先準備 models/neurlang-vits-suisiann/ (best_model.pth + config.json)，"
                "見 README.md「環境設置」章節。不會自動fallback成mock。"
            )
        try:
            from TTS.utils.synthesizer import Synthesizer
        except ImportError as exc:
            raise ImportError(
                "缺少 coqui-tts 或目前venv的transformers版本不對"
                "(neurlang需要 transformers<5，跟MERaLiON的>=5.3.0互斥)。\n"
                "請先: pip install coqui-tts[codec] \"transformers<5\"\n"
                "(見 tw_hokkien_tts_pipeline/requirements.txt)"
            ) from exc

        self._synth = Synthesizer(
            tts_checkpoint=str(checkpoint), tts_config_path=str(config_path)
        )

    def synthesize(self, tts_input: TTSInput, out_path: Path) -> TTSResult:
        self._ensure_loaded()

        text = tts_input.hanji_text
        if not text or not text.strip():
            raise ValueError("neurlang輸入(台語漢字)為空字串，無法合成——檢查翻譯/斷詞層輸出")

        start = time.perf_counter()
        wav = self._synth.tts(text)
        inference_sec = time.perf_counter() - start

        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._synth.save_wav(wav, str(out_path))

        metrics = read_wav_metrics(out_path)
        if metrics.is_all_zero or metrics.has_nan:
            raise RuntimeError(
                f"neurlang推論產生異常音檔 (全零={metrics.is_all_zero}, "
                f"含NaN={metrics.has_nan})，判定為推論失敗，不回傳當作成功結果"
            )

        return TTSResult(
            text=text,
            text_format="hanji",
            wav_path=out_path,
            backend_name=self.name,
            sample_rate=metrics.sample_rate,
            model_id=self.model_id,
            inference_sec=round(inference_sec, 3),
            duration_sec=metrics.duration_sec,
            non_silence_ratio=metrics.non_silence_ratio,
        )


class SpeechT5TailoBackend(TTSBackend):
    """真實 SpeechT5 台羅/Hokkien TTS 串接骨架, **目前還沒有實際驗證過**。

    使用前需要:
        pip install transformers torch soundfile sentencepiece

    並確認目標模型 (例如 speecht5_tailo-hokkien 系列) 的輸入是否直接吃
    台羅字串, 或需要先轉成該模型訓練時使用的音素表示法; 這需要參考模型
    卡片或直接詢問模型作者。這個backend使用 tailo_text(台羅), 不是漢字。
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

    def synthesize(self, tts_input: TTSInput, out_path: Path) -> TTSResult:
        import numpy as np
        import soundfile as sf
        import torch

        self._ensure_loaded()
        tailo_text = tts_input.tailo_text

        start = time.perf_counter()
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
        inference_sec = time.perf_counter() - start

        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), speech.numpy().astype(np.float32), samplerate=16000)

        return TTSResult(
            text=tailo_text,
            text_format="tailo",
            wav_path=out_path,
            backend_name=self.name,
            sample_rate=16000,
            model_id=self.model_id,
            inference_sec=round(inference_sec, 3),
        )


def build_tts_backend(config) -> TTSBackend:
    if config.tts_backend == "mock":
        return MockTTSBackend()
    if config.tts_backend == "neurlang":
        return NeurlangTTSBackend(model_dir=config.neurlang_model_dir)
    if config.tts_backend == "real":
        return SpeechT5TailoBackend(
            model_id=config.tts_model_id, vocoder_id=config.tts_vocoder_id
        )
    raise ValueError(f"未知的 tts_backend: {config.tts_backend}")
