"""Pipeline 設定與後端選擇。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class PipelineConfig:
    """控制 pipeline 要使用哪一種後端實作,以及輸出路徑等設定。"""

    # 後端選擇: "mock" 為內建可離線執行的假後端, 用於開發/測試/串接驗證
    #           "real" 需自行完成對應 Backend 的 API 串接後才能使用 (speecht5_tailo骨架, 尚未驗證)
    #           "neurlang" TTS專用選項: 已驗證能實際出聲的正式後端
    #             (neurlang/coqui-vits-suisiann-minnan-hokkien)
    translation_backend: Literal["mock", "real"] = "mock"
    segmentation_backend: Literal["mock", "real"] = "mock"
    tts_backend: Literal["mock", "neurlang", "real"] = "mock"

    # 真實翻譯 API 設定 (使用 real 後端時才需要)
    translation_api_base_url: str | None = None
    translation_api_key: str | None = None

    # neurlang TTS 設定 (tts_backend="neurlang" 時使用); 預設None時backend會自己
    # 用跟 live_test/tts_backend.py 一樣的路徑慣例找 models/neurlang-vits-suisiann/
    neurlang_model_dir: str | None = None

    # 真實 TTS 設定 (使用 real 後端時才需要, speecht5_tailo系列骨架)
    # 例如 huggingface 上的 speecht5_tailo-hokkien 系列模型 repo id
    tts_model_id: str = "Curiousfox/speecht5_tailo-hokkien_ver1.0.b"
    tts_vocoder_id: str = "microsoft/speecht5_hifigan"

    # 輸出設定
    output_dir: Path = field(default_factory=lambda: Path("./pipeline_output"))
    save_debug_trace: bool = True

    # 醫療安全: 是否強制要求 protected token 詞庫 (人工校正過的發音) 命中率達 100% 才放行
    require_full_protected_coverage: bool = False

    # 連讀變調: 目前只是簡化版循環表(見romanize.py)，且只對數字調格式的音節有效，
    # 對詞庫現有的diacritic讀音是no-op。預設關閉，避免輸入格式偏離neurlang等
    # 已驗證backend訓練資料的樣子；要開啟前應先由台語語言學背景的人確認規則。
    apply_tone_sandhi: bool = False

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
