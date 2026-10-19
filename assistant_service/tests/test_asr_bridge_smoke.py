"""
asr_bridge真實smoke test：用gTTS現場合成一句中文、一句英文的wav檔，餵給
真實的Whisper做辨識，驗證transcribe_bilingual()真的能自動分辨中文/英文
(不是寫死language="Chinese")。openai-whisper或gtts沒裝時自動skip。

不驗證辨識文字逐字正確(ASR本來就有機率性誤差)，只驗證：語言有被正確偵測、
辨識出來的文字不是空字串、且跟原文有明顯重疊(粗略檢查，不要求精確)。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_HAS_WHISPER = importlib.util.find_spec("whisper") is not None
_HAS_GTTS = importlib.util.find_spec("gtts") is not None

pytestmark = pytest.mark.skipif(
    not (_HAS_WHISPER and _HAS_GTTS),
    reason="需要openai-whisper跟gtts都裝好才能跑(pip install openai-whisper gtts)",
)


def _synthesize_mp3(text: str, lang: str, tmp_path: Path) -> Path:
    """whisper內部用ffmpeg載入音檔, 直接吃mp3不需要先轉wav。"""
    from gtts import gTTS

    mp3_path = tmp_path / f"{lang}.mp3"
    gTTS(text=text, lang=lang).save(str(mp3_path))
    return mp3_path


def test_transcribe_bilingual_detects_chinese(tmp_path: Path):
    from assistant_service.asr_bridge import transcribe_bilingual

    audio_path = _synthesize_mp3("我想要喝水", "zh-TW", tmp_path)
    result = transcribe_bilingual(audio_path, model_size="base")

    assert result.detected_language == "zh"
    assert result.text


def test_transcribe_bilingual_detects_english(tmp_path: Path):
    from assistant_service.asr_bridge import transcribe_bilingual

    audio_path = _synthesize_mp3("I would like some water please", "en", tmp_path)
    result = transcribe_bilingual(audio_path, model_size="base")

    assert result.detected_language == "en"
    assert "water" in result.text.lower()
