"""Pipeline 設定與後端選擇。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class PipelineConfig:
    """控制 pipeline 要使用哪一種後端實作,以及輸出路徑等設定。"""

    # 後端選擇: "mock" 為內建可離線執行的假後端, 用於開發/測試/串接驗證
    #           "real" 需自行完成對應 Backend 的 API 串接後才能使用
    translation_backend: Literal["mock", "real"] = "mock"
    segmentation_backend: Literal["mock", "real"] = "mock"
    tts_backend: Literal["mock", "real"] = "mock"

    # 真實翻譯 API 設定 (使用 real 後端時才需要)
    translation_api_base_url: str | None = None
    translation_api_key: str | None = None

    # 真實 TTS 設定 (使用 real 後端時才需要)
    # 例如 huggingface 上的 speecht5_tailo-hokkien 系列模型 repo id
    tts_model_id: str = "Curiousfox/speecht5_tailo-hokkien_ver1.0.b"
    tts_vocoder_id: str = "microsoft/speecht5_hifigan"

    # 輸出設定
    output_dir: Path = field(default_factory=lambda: Path("./pipeline_output"))
    save_debug_trace: bool = True

    # 醫療安全: 是否強制要求 protected token 詞庫 (人工校正過的發音) 命中率達 100% 才放行
    require_full_protected_coverage: bool = False

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
