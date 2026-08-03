"""
華語 -> 台語 整句翻譯層。

TranslationBackend 是抽象介面, 真實串接 (Lohankha / 教育部翻譯器 / Taigi AI Labs
等) 前, 務必先確認:
  - 是否提供正式 API (不是只有網頁可用)
  - 自動化使用是否符合該服務條款
  - 輸入輸出格式 (台語漢字? 台羅? 白話字?)
  - 費用與流量限制
  - 是否有醫療內容的隱私政策疑慮

目前僅提供 MockTranslationBackend, 用簡單詞庫替換模擬「整句翻譯」的行為,
方便在還沒有真實 API 權限時, 先把整條 pipeline 跑通、抓出其他階段的問題。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranslationResult:
    source_text: str
    translated_text: str
    backend_name: str
    raw_response: dict | None = None  # 保留原始 API 回應供 debug


class TranslationBackend(ABC):
    name: str = "base"

    @abstractmethod
    def translate(self, zh_text: str) -> TranslationResult:
        """輸入含有 Protected Token 佔位符的中文整句, 回傳台語(漢字/漢羅)整句。"""
        raise NotImplementedError


class MockTranslationBackend(TranslationBackend):
    """離線可執行的假翻譯後端, 僅用於開發/測試, 不代表真實翻譯品質。"""

    name = "mock"

    # 極簡示範詞庫, 僅供 pipeline 串接測試用, 非正式翻譯資料
    _DEMO_LEXICON = {
        "請": "請",
        "記得": "愛記得",
        "在": "佇",
        "晚餐": "暗頓",
        "後": "後",
        "服用": "食",
        "。": "。",
    }

    def translate(self, zh_text: str) -> TranslationResult:
        translated = zh_text
        for zh, tai in self._DEMO_LEXICON.items():
            translated = translated.replace(zh, tai)
        return TranslationResult(
            source_text=zh_text,
            translated_text=translated,
            backend_name=self.name,
            raw_response={"note": "mock backend, for pipeline wiring only"},
        )


class HTTPTranslationBackend(TranslationBackend):
    """真實 API 串接骨架 (尚未指向特定服務, 需依實際 API 規格調整)。

    使用前必須:
      1. 確認目標服務有開放 API (例如聯絡 Lohankha 或教育部平台申請)
      2. 依官方文件調整 endpoint / 請求格式 / 認證方式
      3. 補上錯誤處理、逾時重試、流量限制
    """

    name = "http"

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 10.0):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout

    def translate(self, zh_text: str) -> TranslationResult:
        import requests  # 延遲載入, 避免 mock 模式也需要安裝 requests

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # TODO: 依實際 API 規格調整 payload 與回應解析欄位
        resp = requests.post(
            self.base_url,
            json={"text": zh_text, "target": "hokkien"},
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        translated_text = data.get("translated_text") or data.get("result") or ""

        return TranslationResult(
            source_text=zh_text,
            translated_text=translated_text,
            backend_name=self.name,
            raw_response=data,
        )


def build_translation_backend(config) -> TranslationBackend:
    if config.translation_backend == "mock":
        return MockTranslationBackend()
    if config.translation_backend == "real":
        if not config.translation_api_base_url:
            raise ValueError("real 翻譯後端需要設定 translation_api_base_url")
        return HTTPTranslationBackend(
            base_url=config.translation_api_base_url,
            api_key=config.translation_api_key,
        )
    raise ValueError(f"未知的 translation_backend: {config.translation_backend}")
