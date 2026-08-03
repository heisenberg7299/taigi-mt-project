"""Pipeline 主流程: 中文 -> Protected Token 遮罩 -> 翻譯 -> 斷詞/台羅 ->
正規化/變調 -> TTS -> WAV。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import PipelineConfig
from .protected_tokens import ProtectedTokenGuard
from .romanize import RomanizationResult, romanize
from .segment import SegmentationResult, build_segmentation_backend
from .translate import TranslationResult, build_translation_backend
from .tts import TTSInput, TTSResult, build_tts_backend


@dataclass
class PipelineResult:
    source_text: str
    masked_text: str
    translation: TranslationResult
    segmentation: SegmentationResult
    romanization: RomanizationResult
    hanji_text: str  # 翻譯後台語漢字, Protected Token 已還原成原文寫法 (供 neurlang 等吃漢字的 backend 使用)
    tts: TTSResult
    warnings: list[str] = field(default_factory=list)

    def to_debug_dict(self) -> dict:
        return {
            "source_text": self.source_text,
            "masked_text": self.masked_text,
            "translated_text": self.translation.translated_text,
            "translation_backend": self.translation.backend_name,
            "segmentation_words": [
                {"surface": w.surface, "tailo": w.tailo, "confidence": w.confidence}
                for w in self.segmentation.words
            ],
            "romanized_text": self.romanization.text,
            "unresolved_count": self.romanization.unresolved_count,
            "mean_confidence": self.romanization.mean_confidence,
            "hanji_text": self.hanji_text,
            "tts": {
                "backend": self.tts.backend_name,
                "model_id": self.tts.model_id,
                "text_sent_to_model": self.tts.text,
                "text_format": self.tts.text_format,
                "inference_sec": self.tts.inference_sec,
                "duration_sec": self.tts.duration_sec,
                "non_silence_ratio": self.tts.non_silence_ratio,
                "sample_rate": self.tts.sample_rate,
                "wav_path": str(self.tts.wav_path),
            },
            "warnings": self.warnings,
        }


class Pipeline:
    def __init__(
        self,
        config: PipelineConfig | None = None,
        drug_lexicon: dict[str, str] | None = None,
        person_names: set[str] | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.guard = ProtectedTokenGuard(drug_lexicon=drug_lexicon, person_names=person_names)
        self.translation_backend = build_translation_backend(self.config)
        self.segmentation_backend = build_segmentation_backend(self.config)
        self.tts_backend = build_tts_backend(self.config)

    def run(self, zh_text: str, out_filename: str = "output.wav") -> PipelineResult:
        warnings: list[str] = []

        # 1. 遮罩
        mask_result = self.guard.mask(zh_text)

        # 醫療安全門檻: 若要求完整涵蓋率但詞庫沒收錄, 直接擋下而非放行猜測發音
        coverage = self.guard.coverage(mask_result.spans)
        if self.config.require_full_protected_coverage and coverage < 1.0:
            raise ValueError(
                f"Protected token 台羅涵蓋率為 {coverage:.0%}, 未達 100%, "
                "已阻擋合成 (require_full_protected_coverage=True)。"
                "請先補齊發音詞庫。"
            )
        if coverage < 1.0:
            warnings.append(f"部分藥名/實體查無人工校正台羅讀音 (涵蓋率 {coverage:.0%})")

        # 2. 翻譯 (帶著佔位符送出, 避免翻譯模型動到關鍵資訊)
        translation = self.translation_backend.translate(mask_result.masked_text)

        # 3. 斷詞 + 轉台羅
        segmentation = self.segmentation_backend.segment(translation.translated_text)
        if segmentation.unresolved_words:
            surfaces = [w.surface for w in segmentation.unresolved_words if not w.surface.startswith("__")]
            if surfaces:
                warnings.append(f"斷詞後查無台羅讀音, 已用原字 fallback: {surfaces}")

        # 4. 台羅正規化
        romanization = romanize(segmentation, apply_tone_sandhi=self.config.apply_tone_sandhi)

        # 5. 把 Protected Token 佔位符換回人工校正的台羅讀音 (給吃台羅的backend用)
        tailo_text = self.guard.unmask_to_tailo(romanization.text, mask_result.spans)
        romanization.text = tailo_text

        # 5b. 同時準備「還原成原文漢字」版本 (給neurlang這類吃漢字+內建phonemizer的backend用)
        #     不能假設pipeline最後產生的台羅一定能直接餵給任何TTS模型
        hanji_text = self.guard.unmask_text(translation.translated_text, mask_result.spans)

        # 6. TTS 合成
        out_path = self.config.output_dir / out_filename
        tts_input = TTSInput(hanji_text=hanji_text, tailo_text=tailo_text)
        tts_result = self.tts_backend.synthesize(tts_input, out_path)

        result = PipelineResult(
            source_text=zh_text,
            masked_text=mask_result.masked_text,
            translation=translation,
            segmentation=segmentation,
            romanization=romanization,
            hanji_text=hanji_text,
            tts=tts_result,
            warnings=warnings,
        )

        if self.config.save_debug_trace:
            debug_path = self.config.output_dir / (Path(out_filename).stem + ".debug.json")
            debug_path.write_text(
                json.dumps(result.to_debug_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return result
