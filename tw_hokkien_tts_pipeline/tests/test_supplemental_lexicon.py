"""測試supplemental_lexicon.py: CSV載入正確、verified欄位正確轉成
low_confidence_surfaces集合。用暫存CSV測試, 不依賴真正的
data/lexicons/supplemental_particles.csv內容(那份內容之後可能會增修)。"""

from __future__ import annotations

from pathlib import Path

from tw_hokkien_tts_pipeline.supplemental_lexicon import (
    load_supplemental_entries,
    load_supplemental_lexicon,
)

_SAMPLE_CSV = """surface,reading,source,reason,verified
的,e5,pronunciation_overrides.py,語料庫驗證過,true
欲,beh4,公開標準辭典,推測值未驗證,false
"""


def _write_sample(tmp_path: Path) -> Path:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(_SAMPLE_CSV, encoding="utf-8")
    return csv_path


def test_load_supplemental_entries_parses_all_fields(tmp_path: Path):
    entries = load_supplemental_entries(_write_sample(tmp_path))
    assert len(entries) == 2
    the = next(e for e in entries if e.surface == "的")
    assert the.reading == "e5"
    assert the.source == "pronunciation_overrides.py"
    assert the.verified is True

    beh = next(e for e in entries if e.surface == "欲")
    assert beh.verified is False


def test_load_supplemental_lexicon_returns_dict_and_low_confidence_set(tmp_path: Path):
    lexicon, low_confidence = load_supplemental_lexicon(_write_sample(tmp_path))
    assert lexicon == {"的": "e5", "欲": "beh4"}
    assert low_confidence == {"欲"}
    assert "的" not in low_confidence
