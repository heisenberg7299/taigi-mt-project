"""把教育部TAT-MOE語料庫(單一發音人)轉成neurlang VITS微調用的訓練資料。

## 背景

`NeurlangTTSBackend`(見`tts.py`)只吃純漢字輸入，模型本身是單一女聲、
22050Hz、不支援speaker embedding(`num_speakers=0`)。使用者申請下載的
教育部「臺灣台語語料庫應用檢索系統」(TAT-MOE)是16kHz、多發音人(328位)、
每句都有多種文字表示法(台羅/台羅數字調/漢羅台文/白話字)。這個模組把
兩邊的差距接起來：

1. **只選一位發音人**——避免把328個不同聲音的資料混進單一女聲模型，
   把音色帶偏。試點選定`TH_THF1001`(混合腔、女聲、錄音室錄音)。
2. **過濾掉漢羅台文裡混雜羅馬字的句子**——`tts.py`的docstring已經
   記錄過純台羅輸入會讓`syn.tts()`卡死、漢羅混合輸入會讓phonemizer
   輸出雜訊字元，這個已知限制對「輸入」跟「訓練資料的文字標籤」是
   同一個phonemizer、同一個風險，所以訓練資料也必須避開混合輸入。
   實測抽樣20位發音人5,495句，20.3%的漢羅台文欄位裡有夾雜羅馬字。
3. **音檔resample 16kHz→22050Hz**——對齊模型`config.json`的
   `audio.sample_rate`。

## 不處理的部分

這個模組只做「資料準備」，不含實際訓練迴圈(見`README.md`訓練章節)。
訓練是否真的能在MPS上跑、微調後音質是否變好，都要等試點資料準備好、
實際跑過訓練才知道——這個模組本身不對這兩件事做任何保證。
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import soundfile as sf
import librosa

TARGET_SAMPLE_RATE = 22050

_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


def is_pure_han_text(text: str) -> bool:
    """True代表這句「漢羅台文」欄位裡沒有夾雜羅馬字(純漢字/標點/數字)。

    夾雜羅馬字的句子(例如「我siūnn無嘛加你二十歲」)會讓neurlang的
    phonemizer踩到`tts.py`docstring記錄過的「已知不安全」路徑，訓練
    資料要避開。
    """
    return not _LATIN_LETTER_RE.search(text)


@dataclass
class SpeakerUtterance:
    utterance_id: str
    text: str
    wav_path: Path


@dataclass
class ManifestStats:
    total_found: int = 0
    filtered_mixed_script: int = 0
    filtered_missing_audio: int = 0
    filtered_empty_text: int = 0
    written: int = 0
    total_audio_seconds: float = 0.0
    skipped_examples: list[str] = field(default_factory=list)


def _find_split_dir(corpus_root: Path, split: str, kind: str) -> Path | None:
    """`corpus_root`底下找`TAT-MOE-{split}-{kind}`，內部有一層雜湊命名
    的`*-master`目錄，用glob找而不是寫死雜湊值(每個split的雜湊都不同)。
    """
    # train解壓縮後是雙層巢狀(多包了一層同名資料夾)，但eval/test只有單層——
    # 開發過程實測發現這個結構不一致(2026-08-06)，兩種pattern都要試，
    # 不能只假設train那種雙層結構，不然eval/test-only的發音人會被漏掉
    # (例如TA_TAF1024/TA_TAF1010只在eval，用雙層pattern掃描不到)
    for pattern in (
        f"TAT-MOE-{split}-{kind}/TAT-MOE-{split}-{kind}/*-master/{kind}",
        f"TAT-MOE-{split}-{kind}/*-master/{kind}",
    ):
        matches = sorted(corpus_root.glob(pattern))
        if matches:
            return matches[0]
    return None


def discover_speaker_utterances(
    corpus_root: Path, speaker_id: str, splits: tuple[str, ...] = ("train", "eval", "test")
) -> list[SpeakerUtterance]:
    """掃描`corpus_root`底下所有指定的split，找`speaker_id`的所有句子。

    回傳未過濾的原始清單(漢羅混合、缺音檔等問題留給`build_manifest`
    處理，這裡只負責「找出配對」)。
    """
    utterances: list[SpeakerUtterance] = []
    for split in splits:
        json_dir = _find_split_dir(corpus_root, split, "json")
        wav_dir = _find_split_dir(corpus_root, split, "lavalier")
        if json_dir is None or wav_dir is None:
            continue

        speaker_json_dir = json_dir / speaker_id
        speaker_wav_dir = wav_dir / speaker_id
        if not speaker_json_dir.is_dir():
            continue

        for json_path in sorted(speaker_json_dir.glob("*.json")):
            if json_path.name.startswith("."):
                continue
            with open(json_path, encoding="utf-8") as fh:
                obj = json.load(fh)
            text = obj.get("漢羅台文", "")
            wav_path = speaker_wav_dir / f"{json_path.stem}.wav"
            utterances.append(
                SpeakerUtterance(
                    utterance_id=f"{split}_{speaker_id}_{json_path.stem}",
                    text=text,
                    wav_path=wav_path,
                )
            )
    return utterances


def build_manifest(
    corpus_root: Path,
    speaker_id: str,
    output_dir: Path,
    splits: tuple[str, ...] = ("train", "eval", "test"),
) -> ManifestStats:
    """建立LJSpeech格式的訓練資料：`output_dir/wavs/*.wav` +
    `output_dir/metadata.csv`(格式`id|text|text`，coqui-TTS
    `formatters.ljspeech`看得懂的格式)。

    音檔會resample成`TARGET_SAMPLE_RATE`並轉單聲道(lavalier麥克風
    本來就是mono，這裡的channel轉換主要是防呆)。
    """
    utterances = discover_speaker_utterances(corpus_root, speaker_id, splits)

    wavs_dir = output_dir / "wavs"
    wavs_dir.mkdir(parents=True, exist_ok=True)

    stats = ManifestStats(total_found=len(utterances))
    metadata_lines: list[str] = []

    for utt in utterances:
        text = utt.text.strip()
        if not text:
            stats.filtered_empty_text += 1
            continue
        if not is_pure_han_text(text):
            stats.filtered_mixed_script += 1
            continue
        if not utt.wav_path.exists():
            stats.filtered_missing_audio += 1
            stats.skipped_examples.append(f"missing audio: {utt.wav_path}")
            continue

        audio, sr = librosa.load(str(utt.wav_path), sr=TARGET_SAMPLE_RATE, mono=True)
        out_wav_path = wavs_dir / f"{utt.utterance_id}.wav"
        sf.write(str(out_wav_path), audio, TARGET_SAMPLE_RATE, subtype="PCM_16")

        stats.total_audio_seconds += len(audio) / TARGET_SAMPLE_RATE
        metadata_lines.append(f"{utt.utterance_id}|{text}|{text}")
        stats.written += 1

    metadata_path = output_dir / "metadata.csv"
    metadata_path.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")

    return stats


def clear_output_dir(output_dir: Path) -> None:
    """重跑之前先清空舊的輸出，避免新舊資料混在一起(例如換發音人後
    忘記清，metadata.csv被append而不是覆蓋)。"""
    if output_dir.exists():
        shutil.rmtree(output_dir)
