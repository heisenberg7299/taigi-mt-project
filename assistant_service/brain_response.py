"""
BrainResponse：「大腦」(意圖+RAG+LLM，這次還沒接，先用手動JSON代替)輸出的
結構化格式，取代直接把自由文字丟給TTS。

核心原則：大腦負責「要回答什麼」，`slots`是獨立於`response_zh`之外的安全
依據——就算LLM生成的句子本身寫錯或不完整，Response Controller也能拿
`slots`裡的藥名/劑量/時間去交叉比對，抓出「大腦自己講的話跟自己給的
結構化資料對不上」這種矛盾，不需要等翻譯完才發現問題。
"""

from __future__ import annotations

from dataclasses import dataclass, field

VALID_RISK_LEVELS = ("high", "medium", "low")
VALID_ACTIONS = ("speak", "call_nurse", "silent")


@dataclass
class BrainResponse:
    request_id: str
    intent: str
    risk_level: str
    language: str
    response_zh: str | None
    slots: dict = field(default_factory=dict)
    action: str = "speak"
    evidence_ids: list[str] = field(default_factory=list)
    priority: int = 50

    @classmethod
    def from_dict(cls, d: dict) -> "BrainResponse":
        """故意全部用.get()而不是d["key"]這種必要欄位直接索引：大腦(尤其
        是接上真正的LLM之後)輸出的JSON不保證每個欄位都存在，這個函式必須
        在欄位缺漏時也能建構出一個(不合法但不會crash的)BrainResponse物件，
        讓後面的validate()有機會正常回報「哪裡有問題」，而不是讓程式在
        還沒走到驗證邏輯之前就先丟出未預期的例外中止掉。"""
        return cls(
            request_id=d.get("request_id") or "",
            intent=d.get("intent") or "",
            risk_level=d.get("risk_level") or "",
            language=d.get("language", "zh-TW"),
            response_zh=d.get("response_zh"),
            slots=d.get("slots") or {},
            action=d.get("action", "speak"),
            evidence_ids=d.get("evidence_ids") or [],
            priority=d.get("priority", 50),
        )

    def validate(self) -> list[str]:
        """回傳驗證錯誤清單, 空list代表通過。不在這裡檢查翻譯安全(那是
        Response Controller的下一步), 這裡只檢查JSON本身的格式/欄位合法性。"""
        errors: list[str] = []

        if not self.request_id:
            errors.append("request_id 不能是空字串")
        if not self.intent:
            errors.append("intent 不能是空字串")
        if self.risk_level not in VALID_RISK_LEVELS:
            errors.append(f"risk_level 必須是 {VALID_RISK_LEVELS} 之一, 收到: {self.risk_level!r}")
        if self.action not in VALID_ACTIONS:
            errors.append(f"action 必須是 {VALID_ACTIONS} 之一, 收到: {self.action!r}")
        if self.action == "speak" and not self.response_zh:
            errors.append("action=speak 時 response_zh 不能是空的")
        if not isinstance(self.priority, int) or not (0 <= self.priority <= 100):
            errors.append(f"priority 必須是0-100的整數, 收到: {self.priority!r}")
        if not isinstance(self.slots, dict):
            errors.append("slots 必須是物件(dict)")

        return errors

    @property
    def is_valid(self) -> bool:
        return not self.validate()
