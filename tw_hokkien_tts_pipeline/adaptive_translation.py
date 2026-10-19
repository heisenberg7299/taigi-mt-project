"""
Adaptive Protected Token：雙路翻譯 + 安全檢查選擇, 不是「所有專名一律遮罩」。

背景：實測10句泛化測試發現「一律遮罩」策略不是穩賺不賠——「普拿疼」這種
模型本來就認得的常見詞, 遮罩成`DRUGA`反而讓模型當成陌生詞去泛化翻譯
(退步成「藥仔」), 比不遮罩還糟; 但「盤尼西林」這種生僻詞遮罩後才成功保留。
人名(小明/陳太太)兩種策略都失敗過。詳見對話記錄跟
reports/safety_critical_translation_failures.md。

策略：同一句話產生兩個候選, 依序選擇:
  1. 候選A(原文不遮罩)：如果每個protected entity的原文字面都完整保留在
     輸出裡, 且台語語意安全檢查通過 -> 直接用這個(省一次LLM呼叫的機會,
     只有A失敗才會真的呼叫B)。
  2. 候選A失敗, 但候選B(遮罩後翻譯)的佔位符完整性通過、且安全檢查通過
     -> 還原後使用。
  3. 兩個都失敗 -> UnsafeTranslationError, fail closed, 不合成語音。

運算量最壞情況是單路的兩倍(A失敗時才會呼叫B), 但temperature=0代表結果
是決定性的, 之後可以加快取層省掉重複呼叫。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .protected_tokens import MaskResult, ProtectedSpan, ProtectedTokenGuard, _PLACEHOLDER_RE
from .translate import TranslationBackend


def _run_safety_checks(zh_text: str, hanji_text: str) -> dict:
    from scripts.safety_checks import run_all_checks

    return run_all_checks(zh_text, hanji_text)


@dataclass
class AdaptiveCandidate:
    label: str  # "raw" 或 "masked"
    llm_output: str  # 模型直接輸出的原始文字 (masked候選還含著佔位符)
    hanji_text: str  # 還原/等同的漢字全文, 用來跑安全檢查跟後續pipeline
    missing_entities: list[str] = field(default_factory=list)
    duplicated_entities: list[str] = field(default_factory=list)
    safety_checks: dict = field(default_factory=dict)

    @property
    def entities_ok(self) -> bool:
        return not self.missing_entities and not self.duplicated_entities

    @property
    def safety_ok(self) -> bool:
        return all(v["ok"] for v in self.safety_checks.values())

    @property
    def overall_ok(self) -> bool:
        return self.entities_ok and self.safety_ok

    def to_debug_dict(self) -> dict:
        return {
            "label": self.label,
            "llm_output": self.llm_output,
            "hanji_text": self.hanji_text,
            "missing_entities": self.missing_entities,
            "duplicated_entities": self.duplicated_entities,
            "entities_ok": self.entities_ok,
            "safety_ok": self.safety_ok,
            "safety_checks": self.safety_checks,
        }


@dataclass
class AdaptiveTranslationResult:
    zh_text: str
    mask_result: MaskResult
    raw_candidate: AdaptiveCandidate
    masked_candidate: AdaptiveCandidate | None  # None代表raw已經通過, 沒有呼叫masked候選
    chosen: str  # "raw" 或 "masked"
    hanji_text: str
    translation_backend_name: str

    def to_debug_dict(self) -> dict:
        return {
            "zh_text": self.zh_text,
            "chosen": self.chosen,
            "hanji_text": self.hanji_text,
            "raw_candidate": self.raw_candidate.to_debug_dict(),
            "masked_candidate": self.masked_candidate.to_debug_dict() if self.masked_candidate else None,
        }


class UnsafeTranslationError(Exception):
    """雙路候選都沒通過檢查, 已阻擋合成。"""

    def __init__(
        self, zh_text: str, raw_candidate: AdaptiveCandidate, masked_candidate: AdaptiveCandidate,
        mask_result: MaskResult | None = None,
    ):
        self.zh_text = zh_text
        self.raw_candidate = raw_candidate
        self.masked_candidate = masked_candidate
        self.mask_result = mask_result
        super().__init__(
            f"雙路翻譯都未通過檢查, 已阻擋合成: {zh_text!r}\n"
            f"  候選A(原文): entities_ok={raw_candidate.entities_ok}"
            f"(缺失={raw_candidate.missing_entities}), safety_ok={raw_candidate.safety_ok}\n"
            f"  候選B(遮罩): entities_ok={masked_candidate.entities_ok}"
            f"(缺失={masked_candidate.missing_entities}, 重複={masked_candidate.duplicated_entities}), "
            f"safety_ok={masked_candidate.safety_ok}"
        )


def _evaluate_raw_candidate(zh_text: str, spans: list[ProtectedSpan], llm_output: str) -> AdaptiveCandidate:
    missing = [span.original for span in spans if span.original not in llm_output]
    safety = _run_safety_checks(zh_text, llm_output)
    return AdaptiveCandidate(
        label="raw", llm_output=llm_output, hanji_text=llm_output,
        missing_entities=missing, duplicated_entities=[], safety_checks=safety,
    )


def _evaluate_masked_candidate(
    zh_text: str, guard: ProtectedTokenGuard, spans: list[ProtectedSpan], llm_output: str
) -> AdaptiveCandidate:
    from collections import Counter

    counts = Counter(_PLACEHOLDER_RE.findall(llm_output))
    missing = [span.placeholder for span in spans if counts.get(span.placeholder, 0) == 0]
    duplicated = [span.placeholder for span in spans if counts.get(span.placeholder, 0) > 1]
    hanji_text = guard.unmask_text(llm_output, spans)
    safety = _run_safety_checks(zh_text, hanji_text)
    return AdaptiveCandidate(
        label="masked", llm_output=llm_output, hanji_text=hanji_text,
        missing_entities=missing, duplicated_entities=duplicated, safety_checks=safety,
    )


def translate_adaptive(
    zh_text: str, guard: ProtectedTokenGuard, translation_backend: TranslationBackend
) -> AdaptiveTranslationResult:
    """雙路翻譯 + 安全檢查選擇。候選A(原文)先跑一次, 通過就直接回傳,
    不通過才會真的呼叫候選B(遮罩後翻譯)——最好狀況只花一次LLM呼叫。"""
    mask_result = guard.mask(zh_text)

    raw_output = translation_backend.translate(zh_text).translated_text
    raw_candidate = _evaluate_raw_candidate(zh_text, mask_result.spans, raw_output)

    if raw_candidate.overall_ok:
        return AdaptiveTranslationResult(
            zh_text=zh_text, mask_result=mask_result,
            raw_candidate=raw_candidate, masked_candidate=None,
            chosen="raw", hanji_text=raw_candidate.hanji_text,
            translation_backend_name=translation_backend.name,
        )

    masked_output = translation_backend.translate(mask_result.masked_text).translated_text
    masked_candidate = _evaluate_masked_candidate(zh_text, guard, mask_result.spans, masked_output)

    if masked_candidate.overall_ok:
        return AdaptiveTranslationResult(
            zh_text=zh_text, mask_result=mask_result,
            raw_candidate=raw_candidate, masked_candidate=masked_candidate,
            chosen="masked", hanji_text=masked_candidate.hanji_text,
            translation_backend_name=translation_backend.name,
        )

    raise UnsafeTranslationError(zh_text, raw_candidate, masked_candidate, mask_result=mask_result)


def translate_with_structured_fallback(
    zh_text: str,
    guard: ProtectedTokenGuard,
    translation_backend: TranslationBackend,
    structured_intent=None,
    structured_renderer=None,
) -> AdaptiveTranslationResult:
    """A -> B -> C -> fail closed。

    候選A(原文)、候選B(遮罩)沿用 translate_adaptive()；兩者都失敗時，
    只有這句話的 structured_intent 屬於 structured_renderer 支援的範圍
    (見 structured_renderer.py 的 SUPPORTED_INTENTS)才會用候選C(人工審核
    模板)。三者都無法安全處理時, 原本的 UnsafeTranslationError 會照樣往外
    丟, 不會被吞掉——候選C只是多一條路, 不是把fail closed的門檻降低。
    """
    try:
        return translate_adaptive(zh_text, guard, translation_backend)
    except UnsafeTranslationError as e:
        if structured_renderer is not None and structured_renderer.can_handle(structured_intent):
            hanji_text = structured_renderer.render(structured_intent, translation_backend)
            return AdaptiveTranslationResult(
                zh_text=zh_text,
                mask_result=e.mask_result,
                raw_candidate=e.raw_candidate,
                masked_candidate=e.masked_candidate,
                chosen="structured_c",
                hanji_text=hanji_text,
                translation_backend_name=translation_backend.name,
            )
        raise
