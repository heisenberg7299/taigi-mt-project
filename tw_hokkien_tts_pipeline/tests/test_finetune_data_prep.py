"""finetune_data_prep.py測試：驗證TAT-MOE語料庫→neurlang微調訓練資料的
轉換邏輯(見finetune_data_prep.py docstring的完整背景說明)。

用合成的假語料庫目錄結構(不是真的22GB下載)測試discover/filter/manifest
邏輯，跟真實下載無關，CI/其他人的機器上都能跑。resample的部分用真的
soundfile/librosa處理小段合成音訊(不需要真的語料庫wav)。
"""

from __future__ import annotations

import json

import numpy as np
import soundfile as sf

from tw_hokkien_tts_pipeline.finetune_data_prep import (
    build_manifest,
    discover_speaker_utterances,
    is_pure_han_text,
)


def test_is_pure_han_text_accepts_han_and_punctuation():
    assert is_pure_han_text("就會愈來愈食力。")
    assert is_pure_han_text("按怎？緊來！")


def test_is_pure_han_text_rejects_mixed_latin_letters():
    """漢羅台文欄位裡夾雜羅馬字(台羅片段)的句子，例如原始語料庫抽樣時
    找到的「我siūnn無嘛加你二十歲」，要被判定為不是純漢字。"""
    assert not is_pure_han_text("我siūnn無嘛加你二十歲，")
    assert not is_pure_han_text("Kan仔轄王無五彩的絲仔襪佮短絲仔褲，")


def _write_fake_corpus(root, split: str, speaker_id: str, sentences: list[str], sample_rate: int = 16000):
    """在`root`底下建一個跟真實TAT-MOE解壓縮後同樣巢狀結構的假語料庫：
    `TAT-MOE-{split}-json/TAT-MOE-{split}-json/<hash>-master/json/<speaker>/*.json`
    `TAT-MOE-{split}-lavalier/TAT-MOE-{split}-lavalier/<hash>-master/lavalier/<speaker>/*.wav`
    """
    json_dir = root / f"TAT-MOE-{split}-json" / f"TAT-MOE-{split}-json" / "deadbeef-master" / "json" / speaker_id
    wav_dir = root / f"TAT-MOE-{split}-lavalier" / f"TAT-MOE-{split}-lavalier" / "deadbeef-master" / "lavalier" / speaker_id
    json_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)

    for i, text in enumerate(sentences):
        stem = f"A001-{i}"
        with open(json_dir / f"{stem}.json", "w", encoding="utf-8") as fh:
            json.dump({"漢羅台文": text, "發音人": speaker_id}, fh, ensure_ascii=False)

        # 半秒的假音訊(合成，不是真的語料庫錄音)，驗證resample邏輯即可
        samples = np.zeros(sample_rate // 2, dtype=np.float32)
        sf.write(str(wav_dir / f"{stem}.wav"), samples, sample_rate)

    # 模擬真實壓縮檔裡macOS產生的AppleDouble雜訊檔(._開頭)，驗證掃描邏輯
    # 有正確跳過，不是這個測試特別去製造出錯的情境
    (json_dir / f"._A001-0.json").write_bytes(b"\x00\x05\x16\x07")


def _write_fake_corpus_single_nested(root, split: str, speaker_id: str, sentences: list[str], sample_rate: int = 16000):
    """跟`_write_fake_corpus`一樣，但只有單層巢狀(`TAT-MOE-{split}-{kind}/
    <hash>-master/{kind}/...`，沒有重複一次`TAT-MOE-{split}-{kind}`)。

    實測發現真實語料庫解壓縮後，train是雙層巢狀，但eval/test是單層
    (2026-08-06)，例如`TA_TAF1024`/`TA_TAF1010`這兩位發音人只在eval出現，
    用只支援雙層結構的掃描邏輯會完全找不到、被誤判成「這位發音人沒有
    句子」——這個fixture專門用來重現+驗證這個結構不一致的情境有被正確
    處理。
    """
    json_dir = root / f"TAT-MOE-{split}-json" / "deadbeef-master" / "json" / speaker_id
    wav_dir = root / f"TAT-MOE-{split}-lavalier" / "deadbeef-master" / "lavalier" / speaker_id
    json_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)

    for i, text in enumerate(sentences):
        stem = f"A001-{i}"
        with open(json_dir / f"{stem}.json", "w", encoding="utf-8") as fh:
            json.dump({"漢羅台文": text, "發音人": speaker_id}, fh, ensure_ascii=False)
        samples = np.zeros(sample_rate // 2, dtype=np.float32)
        sf.write(str(wav_dir / f"{stem}.wav"), samples, sample_rate)


def test_discover_speaker_utterances_finds_pairs_across_splits(tmp_path):
    _write_fake_corpus(tmp_path, "train", "TH_THF1001", ["第一句。", "第二句。"])
    _write_fake_corpus(tmp_path, "eval", "TH_THF1001", ["第三句。"])

    utterances = discover_speaker_utterances(tmp_path, "TH_THF1001", splits=("train", "eval", "test"))

    assert len(utterances) == 3
    texts = {u.text for u in utterances}
    assert texts == {"第一句。", "第二句。", "第三句。"}
    assert all(u.wav_path.exists() for u in utterances)


def test_discover_speaker_utterances_finds_speaker_only_present_in_single_nested_split(tmp_path):
    """迴歸測試：真實語料庫裡train是雙層巢狀、eval/test是單層，只支援
    其中一種結構會漏掉只在eval/test出現的發音人(見
    `_write_fake_corpus_single_nested`docstring的背景說明)。"""
    _write_fake_corpus_single_nested(tmp_path, "eval", "TA_TAF1024", ["只在eval出現的句子。"])

    utterances = discover_speaker_utterances(tmp_path, "TA_TAF1024", splits=("train", "eval", "test"))

    assert len(utterances) == 1
    assert utterances[0].text == "只在eval出現的句子。"
    assert utterances[0].wav_path.exists()


def test_discover_speaker_utterances_ignores_other_speakers(tmp_path):
    _write_fake_corpus(tmp_path, "train", "TH_THF1001", ["屬於1001的句子。"])
    _write_fake_corpus(tmp_path, "train", "TA_TAF1002", ["屬於1002的句子，不該出現。"])

    utterances = discover_speaker_utterances(tmp_path, "TH_THF1001", splits=("train",))

    assert len(utterances) == 1
    assert utterances[0].text == "屬於1001的句子。"


def test_build_manifest_filters_mixed_script_and_resamples(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_fake_corpus(
        corpus_root,
        "train",
        "TH_THF1001",
        ["純漢字句子。", "混雜siūnn羅馬字的句子。", "另一句純漢字。"],
        sample_rate=16000,
    )

    output_dir = tmp_path / "pilot_output"
    stats = build_manifest(corpus_root, "TH_THF1001", output_dir, splits=("train",))

    assert stats.total_found == 3
    assert stats.filtered_mixed_script == 1
    assert stats.written == 2

    metadata_path = output_dir / "metadata.csv"
    assert metadata_path.exists()
    lines = metadata_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        utt_id, text, text_dup = line.split("|")
        assert text == text_dup
        assert "siūnn" not in text

    wav_files = list((output_dir / "wavs").glob("*.wav"))
    assert len(wav_files) == 2
    for wav_path in wav_files:
        audio, sr = sf.read(str(wav_path))
        assert sr == 22050  # resample目標取樣率，對齊neurlang模型config


def test_build_manifest_skips_missing_audio_without_crashing(tmp_path):
    corpus_root = tmp_path / "corpus"
    _write_fake_corpus(corpus_root, "train", "TH_THF1001", ["有音檔的句子。"])

    # 手動刪掉音檔，模擬json/wav配對缺漏的情況(語料庫本身理論上不該發生，
    # 但轉換腳本不該對這種情況直接crash，應該跳過並記錄)
    wav_dir = corpus_root / "TAT-MOE-train-lavalier" / "TAT-MOE-train-lavalier" / "deadbeef-master" / "lavalier" / "TH_THF1001"
    for wav_path in wav_dir.glob("*.wav"):
        wav_path.unlink()

    output_dir = tmp_path / "pilot_output"
    stats = build_manifest(corpus_root, "TH_THF1001", output_dir, splits=("train",))

    assert stats.filtered_missing_audio == 1
    assert stats.written == 0
    assert stats.skipped_examples
