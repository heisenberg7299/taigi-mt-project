"""
StructuredMedicalRenderer (候選C)：對已支援的高風險意圖用人工審核過的固定
模板生成，不靠LLM生成——保證結構化欄位(人名/位置/職稱/藥名/劑量)在輸出裡
100%正確，代價是只能覆蓋事先定義好的意圖，句子多樣性有限。

只在候選A(原文)、候選B(遮罩)都失敗，且這句話的intent屬於這裡支援的範圍時
才會用到，見 pipeline.py / adaptive_translation.py 的候選選擇順序。

**這裡的模板文字是demo等級，尚未經過台語母語者審核**，實際部署前必須由
台語專業人士逐一確認自然度與正確性，跟 protected_tokens.py 的drug_lexicon
要求一致——這個renderer解決的是「結構化資訊不會弄丟」，不是「台語念起來
道地」。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StructuredIntent:
    intent: str  # "addressing_patient" / "request_staff" / "medication_reminder"
    patient: str | None = None
    patient_title: str | None = None
    location: str | None = None  # 給人看的位置描述, 例如"隔壁床"
    staff_role: str | None = None
    need: str | None = None  # 需要什麼協助, 例如"協助"/"拍痰"
    remainder_zh: str | None = None  # addressing_patient 用: 稱呼之後剩下要翻譯的中文
    drug: str | None = None
    dose: str | None = None
    time: str | None = None
    constraint: str | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> "StructuredIntent | None":
        if d is None:
            return None
        return cls(**d)


class StructuredMedicalRenderer:
    SUPPORTED_INTENTS = {"addressing_patient", "request_staff", "medication_reminder"}

    def can_handle(self, intent: StructuredIntent | None) -> bool:
        return intent is not None and intent.intent in self.SUPPORTED_INTENTS

    def render(self, intent: StructuredIntent, translation_backend=None) -> str:
        if intent.intent == "addressing_patient":
            return self._render_addressing(intent, translation_backend)
        if intent.intent == "request_staff":
            return self._render_request_staff(intent)
        if intent.intent == "medication_reminder":
            return self._render_medication_reminder(intent)
        raise ValueError(f"不支援的intent: {intent.intent}")

    def _render_addressing(self, intent: StructuredIntent, translation_backend) -> str:
        # 姓名+稱謂完全不經過LLM，直接原樣接上——保證100%正確。
        # remainder_zh(稱呼之後剩下的句子)才交給翻譯backend處理。
        vocative = (intent.patient or "") + (intent.patient_title or "")
        if intent.remainder_zh and translation_backend is not None:
            remainder = translation_backend.translate(intent.remainder_zh).translated_text
            return f"{vocative}，{remainder}"
        return f"{vocative}。"

    def _render_request_staff(self, intent: StructuredIntent) -> str:
        location = intent.location or ""
        patient = intent.patient or ""
        role = intent.staff_role or "醫護人員"
        need = intent.need or "協助"
        subject = f"{location}的{patient}" if location else patient
        return f"{subject}需要{role}來{need}。"

    def _render_medication_reminder(self, intent: StructuredIntent) -> str:
        parts = []
        if intent.patient:
            parts.append(intent.patient)
        drug_part = intent.drug or "藥仔"
        dose_time = "、".join(p for p in [intent.dose, intent.time] if p)
        parts.append(f"愛食{drug_part}" + (f"，{dose_time}" if dose_time else ""))
        if intent.constraint:
            parts.append(intent.constraint)
        return "，".join(parts) + "。"
