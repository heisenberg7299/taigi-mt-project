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
    #           "taigi_llama" 翻譯專用選項: 已驗證能實際翻譯的正式後端
    #             (Taigi-Llama-2-Translator-7B, 透過本機Ollama)——只當baseline,
    #             不代表結果安全可信, 見 translate.py docstring
    translation_backend: Literal["mock", "taigi_llama", "real"] = "mock"
    segmentation_backend: Literal["mock", "real"] = "mock"
    tts_backend: Literal["mock", "neurlang", "real"] = "mock"

    # 真實翻譯 API 設定 (使用 real 後端時才需要)
    translation_api_base_url: str | None = None
    translation_api_key: str | None = None

    # Taigi-Llama 設定 (translation_backend="taigi_llama" 時使用)
    ollama_url: str = "http://localhost:11434/api/generate"

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

    # 翻譯策略: "single" 固定遮罩後才翻譯(原本的做法)
    #           "adaptive" 雙路翻譯(原文/遮罩)+安全檢查選擇, 不是所有專名一律遮罩。
    #             背景：實測發現「一律遮罩」對「模型本來就認得的常見詞」(例如
    #             普拿疼)反而有害——遮罩成DRUGA後模型當成陌生詞去泛化翻譯，
    #             比不遮罩還差。詳見 adaptive_translation.py。兩個候選都沒通過
    #             安全檢查時會丟出 UnsafeTranslationError(fail closed)，不是
    #             警告了事，因為這代表兩種策略都救不回這句話。
    translation_strategy: Literal["single", "adaptive"] = "single"

    # 醫療安全: 是否強制要求 protected token 詞庫 (人工校正過的發音) 命中率達 100% 才放行
    require_full_protected_coverage: bool = False

    # 醫療安全: 翻譯完成後是否檢查每個protected token佔位符有沒有在翻譯過程中
    # 被LLM弄丟/複製/改序(不是mock替換那種決定性操作，真實LLM有可能這樣做，
    # 見 reports/safety_critical_translation_failures.md)。True時發現問題直接
    # raise擋下合成，不放行；False(預設)只記錄進debug trace的warnings。
    require_protected_token_integrity: bool = False

    # 醫療安全: 翻譯完成後是否套用 scripts/safety_checks.py 的四層檢查
    # (否定詞/數字一致性/醫療術語白名單/長度異常/陷阱字語意反轉)，比對原文
    # zh_text跟還原後的hanji_text。True時任何一項檢查沒過就直接raise擋下合成；
    # False(預設)只記錄進debug trace，不阻擋——這些檢查目前誤報率不算低
    # (見reports/stage3_safety_checks.md，medical_terms白名單誤報率偏高)，
    # 預設關閉避免過度阻擋。
    require_safety_checks_pass: bool = False

    # 連讀變調: 目前只是簡化版循環表(見romanize.py)，且只對數字調格式的音節有效，
    # 對詞庫現有的diacritic讀音是no-op。預設關閉，避免輸入格式偏離neurlang等
    # 已驗證backend訓練資料的樣子；要開啟前應先由台語語言學背景的人確認規則。
    apply_tone_sandhi: bool = False

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
