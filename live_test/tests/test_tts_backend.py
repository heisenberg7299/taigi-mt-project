"""
live_test/tts_backend.py測試：2026-10-19修正記錄。

真實情境：這個Flask server process可能長時間存活(實測到同一個process從
9月跑到10月)，`TMP_DIR`(`/tmp/taigi_tts_backend`)原本只在模組載入(伺服器
啟動)那一刻`os.makedirs()`一次——如果中途這個目錄被系統清掉(macOS對
`/tmp`底下久未使用的目錄會做清理)，之後每次`/synthesize`都會在
`sf.write()`/`_synth.save_wav()`寫檔時失敗(`soundfile.LibsndfileError:
System error`)，且process不會自己恢復，需要手動重啟才能修好——這是
2026-10-19用MERaLiON backend實測到的真實500錯誤，不是假設性的。

這裡不import整個tts_backend模組(避免真的觸發`_load()`載入TTS模型)，
只驗證`synthesize()`路由裡「寫檔前確保目錄存在」這段邏輯本身。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
TTS_BACKEND_PATH = ROOT / "live_test" / "tts_backend.py"


@pytest.fixture
def tts_backend_module(monkeypatch, tmp_path):
    """用importlib單獨載入tts_backend.py，避免真的import整個flask app
    registry造成重複註冊問題；TMP_DIR導到pytest的tmp_path，不動到真正的
    /tmp/taigi_tts_backend。"""
    monkeypatch.setenv("TTS_BACKEND", "neurlang")
    spec = importlib.util.spec_from_file_location("live_test_tts_backend_under_test", TTS_BACKEND_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(ROOT))
    module.TMP_DIR = str(tmp_path / "taigi_tts_backend")
    os.makedirs(module.TMP_DIR, exist_ok=True)
    return module


def test_synthesize_recreates_tmp_dir_if_it_was_deleted_after_server_startup(tts_backend_module):
    """2026-10-19迴歸測試：模擬伺服器啟動很久之後、TMP_DIR被外部清掉的
    情境(這次真人實測MERaLiON backend時遇到的確切錯誤)。驗證/synthesize
    在寫檔前會自己重建目錄，不會直接丟LibsndfileError/500。"""
    module = tts_backend_module
    shutil.rmtree(module.TMP_DIR)
    assert not os.path.exists(module.TMP_DIR)

    fake_wav_bytes = b"RIFF....fake-wav-content"
    module._synth = MagicMock()
    module._synth.tts.return_value = "fake-wav-array"

    def _fake_save_wav(wav, out_path):
        # 真正的save_wav()需要目錄存在才能寫檔，這裡模擬同樣的前提條件，
        # 藉此驗證呼叫到這裡之前目錄已經被重建
        assert os.path.isdir(os.path.dirname(out_path)), "目錄應該已經在寫檔前被重建"
        with open(out_path, "wb") as f:
            f.write(fake_wav_bytes)

    module._synth.save_wav.side_effect = _fake_save_wav

    with module.app.test_client() as client:
        resp = client.post("/synthesize", json={"han": "我欲啉水"})

    assert resp.status_code == 200
    assert resp.data == fake_wav_bytes
    assert os.path.isdir(module.TMP_DIR)  # 目錄確實被重建了


def test_synthesize_still_works_normally_when_tmp_dir_already_exists(tts_backend_module):
    """正常情況(目錄本來就在)不應該因為這個修正而壞掉——確保修正沒有
    意外改變既有行為。"""
    module = tts_backend_module
    assert os.path.exists(module.TMP_DIR)

    fake_wav_bytes = b"RIFF....another-fake-wav"
    module._synth = MagicMock()
    module._synth.tts.return_value = "fake-wav-array"

    def _fake_save_wav(wav, out_path):
        with open(out_path, "wb") as f:
            f.write(fake_wav_bytes)

    module._synth.save_wav.side_effect = _fake_save_wav

    with module.app.test_client() as client:
        resp = client.post("/synthesize", json={"han": "我欲去放尿"})

    assert resp.status_code == 200
    assert resp.data == fake_wav_bytes
