"""
中文 -> 台語 -> 台羅 -> TTS 語音合成 Pipeline

架構:
    中文輸入
      -> Protected Token 遮罩 (保護藥名/人名/劑量)
      -> 台語整句翻譯 (TranslationBackend)
      -> 台語斷詞 + 漢字轉台羅 (SegmentationBackend)
      -> 台羅正規化 + 連讀變調 (romanize)
      -> TTS 合成 (TTSBackend)
      -> WAV 語音輸出

各階段皆以抽象介面定義, 目前提供可直接執行的 Mock 實作,
真實後端 (Lohankha / 教育部翻譯器 / 臺灣言語工具 / speecht5_tailo-hokkien 等)
需自行申請 API 權限並實作對應 Backend 類別後替換即可, 詳見 README.md。
"""

from .pipeline import Pipeline, PipelineResult
from .config import PipelineConfig

__all__ = ["Pipeline", "PipelineResult", "PipelineConfig"]
