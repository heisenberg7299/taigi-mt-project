"""Pipeline 主流程: 中文 -> Protected Token 遮罩 -> 翻譯 -> Protected Token
完整性檢查 -> 台語語意安全檢查 -> 斷詞/台羅 -> 正規化/變調 -> TTS -> WAV。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .adaptive_translation import translate_adaptive
from .config import PipelineConfig
from .protected_tokens import _PLACEHOLDER_RE, ProtectedTokenGuard
from .romanize import RomanizationResult, romanize
from .segment import SegmentationResult, build_segmentation_backend
from .translate import TranslationResult, build_translation_backend
from .tts import TTSInput, TTSResult, build_tts_backend


def _check_protected_token_integrity(translated_text: str, spans) -> dict:
    """翻譯完成後檢查每個protected token佔位符還在不在、有沒有被複製。

    mock翻譯backend是決定性的字典替換, 不會弄丟/複製佔位符; 但真實LLM
    (例如Taigi-Llama)是生成式的, 有可能把佔位符當一般文字改寫、重複輸出、
    或整個漏掉——這正是 reports/safety_critical_translation_failures.md
    記錄過的問題模式(藥名被吃掉)的另一種可能形式, 所以獨立成一個檢查,
    不能只靠最後的unmask_text/unmask_to_tailo round-trip(那個只檢查
    "有出現的佔位符換得回來", 換不回「翻譯時就已經不見了」這種狀況)。
    """
    counts = Counter(_PLACEHOLDER_RE.findall(translated_text))
    missing = [span.placeholder for span in spans if counts.get(span.placeholder, 0) == 0]
    duplicated = [span.placeholder for span in spans if counts.get(span.placeholder, 0) > 1]
    return {"ok": not missing and not duplicated, "missing": missing, "duplicated": duplicated}


def _run_safety_checks(zh_text: str, hanji_text: str) -> dict:
    """套用 scripts/safety_checks.py 既有的四層+陷阱字檢查, 不重新發明一套。

    這些檢查本身有已知的誤報率(見 reports/stage3_safety_checks.md,
    medical_terms白名單誤報率偏高), 所以預設不會拿來擋下合成, 只記錄結果,
    要不要fail-closed由 PipelineConfig.require_safety_checks_pass 決定。
    """
    from scripts.safety_checks import run_all_checks

    return run_all_checks(zh_text, hanji_text)


@dataclass
class PipelineResult:
    source_text: str
    masked_text: str
    translation: TranslationResult
    segmentation: SegmentationResult
    romanization: RomanizationResult
    hanji_text: str  # 翻譯後台語漢字, Protected Token 已還原成原文寫法 (供 neurlang 等吃漢字的 backend 使用)
    tts: TTSResult
    protected_text_preserved: bool  # 每個protected span的原文是否都完整出現在最終送進TTS的文字裡 (沒有遺失/改序/類型互換)
    protected_pronunciation_enforced: bool  # 是否保證TTS真的用了人工校正過的台羅讀音 (不是backend自己重新推導的發音)
    protected_token_integrity: dict  # 翻譯完成後佔位符有沒有被LLM弄丟/複製
    safety_checks: dict  # scripts/safety_checks.py 四層+陷阱字檢查結果 (比對原文zh跟hanji_text)
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
            "protected_text_preserved": self.protected_text_preserved,
            "protected_pronunciation_enforced": self.protected_pronunciation_enforced,
            "protected_token_integrity": self.protected_token_integrity,
            "safety_checks": self.safety_checks,
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

        if self.config.translation_strategy == "adaptive":
            # 2'. Adaptive Protected Token：雙路翻譯(原文/遮罩)+安全檢查選擇，
            #     不是所有專名一律遮罩——實測發現「一律遮罩」對模型本來就
            #     認得的常見詞反而有害。兩個候選都沒通過會直接raise
            #     UnsafeTranslationError(fail closed)，不是警告了事，見
            #     adaptive_translation.py。
            adaptive_result = translate_adaptive(zh_text, self.guard, self.translation_backend)
            chosen_candidate = (
                adaptive_result.raw_candidate if adaptive_result.chosen == "raw"
                else adaptive_result.masked_candidate
            )
            translation = TranslationResult(
                source_text=zh_text,
                translated_text=chosen_candidate.llm_output,
                backend_name=f"{adaptive_result.translation_backend_name}(adaptive:{adaptive_result.chosen})",
                raw_response=adaptive_result.to_debug_dict(),
            )
            hanji_text = adaptive_result.hanji_text
            protected_token_integrity = {
                "ok": chosen_candidate.entities_ok,
                "missing": chosen_candidate.missing_entities,
                "duplicated": chosen_candidate.duplicated_entities,
            }
            safety_checks = chosen_candidate.safety_checks
            warnings.append(f"Adaptive Protected Token選擇了候選「{adaptive_result.chosen}」")
        else:
            # 2. 翻譯 (帶著佔位符送出, 避免翻譯模型動到關鍵資訊)
            translation = self.translation_backend.translate(mask_result.masked_text)

            # 2a. Protected Token 完整性檢查: 翻譯過程(尤其是真實LLM, 生成式、
            #     非決定性)有沒有把佔位符弄丟或複製
            protected_token_integrity = _check_protected_token_integrity(
                translation.translated_text, mask_result.spans
            )
            if not protected_token_integrity["ok"]:
                msg = (
                    f"Protected token在翻譯過程中被弄壞: "
                    f"missing={protected_token_integrity['missing']}, "
                    f"duplicated={protected_token_integrity['duplicated']}"
                )
                if self.config.require_protected_token_integrity:
                    raise ValueError(f"{msg}（已阻擋合成, require_protected_token_integrity=True）")
                warnings.append(msg)

            # 2b. 還原成「原文漢字」版本, 供下面的安全檢查跟neurlang等吃漢字的backend使用。
            #     刻意在斷詞/正規化之前就算出來, 因為它只依賴translation.translated_text
            #     + mask_result.spans, 不需要等後面的步驟
            hanji_text = self.guard.unmask_text(translation.translated_text, mask_result.spans)

            # 2c. 台語語意安全檢查 (否定詞/數字一致性/醫療術語/長度異常/陷阱字),
            #     比對原文zh_text跟還原後的hanji_text——不是翻譯本身，是翻譯完之後
            #     的把關層，只會告訴你「這次翻譯可能有問題」，不會自己修正
            safety_checks = _run_safety_checks(zh_text, hanji_text)
            failed_checks = [name for name, r in safety_checks.items() if not r["ok"]]
            if failed_checks:
                msg = f"台語語意安全檢查未通過: {failed_checks}"
                if self.config.require_safety_checks_pass:
                    raise ValueError(f"{msg}（已阻擋合成, require_safety_checks_pass=True）")
                warnings.append(msg)

        # 3. 斷詞 + 轉台羅
        segmentation = self.segmentation_backend.segment(translation.translated_text)
        if segmentation.unresolved_words:
            surfaces = [
                w.surface for w in segmentation.unresolved_words
                if not _PLACEHOLDER_RE.fullmatch(w.surface)
            ]
            if surfaces:
                warnings.append(f"斷詞後查無台羅讀音, 已用原字 fallback: {surfaces}")

        # 4. 台羅正規化
        romanization = romanize(segmentation, apply_tone_sandhi=self.config.apply_tone_sandhi)

        # 5. 把 Protected Token 佔位符換回人工校正的台羅讀音 (給吃台羅的backend用)
        #    hanji_text (漢字版本) 已經在步驟2b算過了, 這裡不用重算
        tailo_text = self.guard.unmask_to_tailo(romanization.text, mask_result.spans)
        romanization.text = tailo_text

        # 6. TTS 合成
        out_path = self.config.output_dir / out_filename
        tts_input = TTSInput(hanji_text=hanji_text, tailo_text=tailo_text)
        tts_result = self.tts_backend.synthesize(tts_input, out_path)

        # 每個protected span的內容是否真的完整出現在最終送進TTS的文字裡，而不是
        # 憑空假設「呼叫過unmask就等於保留成功」——翻譯/斷詞層若把佔位符弄壞，
        # 這裡才抓得到。注意：漢字版本應該找「原文漢字」(span.original)，台羅
        # 版本應該找「台羅讀音」(span.tailo，沒有的話unmask_to_tailo會fallback
        # 回原文漢字，見protected_tokens.py)——不能不分格式都拿中文字去台羅
        # 字串裡找，那樣永遠找不到(台羅字串裡不會出現中文字)。
        if tts_result.text_format == "hanji":
            protected_text_preserved = all(
                span.original in hanji_text for span in mask_result.spans
            )
        else:
            expected_values = [span.tailo if span.tailo else span.original for span in mask_result.spans]
            protected_text_preserved = all(val in tailo_text for val in expected_values)

        # 發音是否真的受保護: 只有當backend直接消費「人工校正過的台羅讀音」
        # (consumes_verified_pronunciation=True) 且每個藥名都有查到讀音(coverage=100%)
        # 時才能算數。neurlang這類吃漢字+自己內建phonemizer的backend, 固定是False——
        # 漢字文字保留下來不代表模型會照著人工校正過的讀音念。
        protected_pronunciation_enforced = (
            getattr(self.tts_backend, "consumes_verified_pronunciation", False)
            and coverage >= 1.0
        )

        result = PipelineResult(
            source_text=zh_text,
            masked_text=mask_result.masked_text,
            translation=translation,
            segmentation=segmentation,
            romanization=romanization,
            hanji_text=hanji_text,
            tts=tts_result,
            protected_text_preserved=protected_text_preserved,
            protected_pronunciation_enforced=protected_pronunciation_enforced,
            protected_token_integrity=protected_token_integrity,
            safety_checks=safety_checks,
            warnings=warnings,
        )

        if self.config.save_debug_trace:
            debug_path = self.config.output_dir / (Path(out_filename).stem + ".debug.json")
            debug_path.write_text(
                json.dumps(result.to_debug_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return result
