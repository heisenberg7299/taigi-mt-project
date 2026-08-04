"""
把 Response Controller 包成 FastAPI 服務：POST /v1/speech 接BrainResponse
JSON，回傳結構化結果。這樣之後換Ollama、RAG、TTS模型，都不需要重寫整個
系統——大腦(不管是誰生成的)只要輸出符合BrainResponse schema的JSON打這支
API就好。

執行前置需求（Response Controller內部依賴，這支API本身不會幫你啟動）：
  1. ollama serve
  2. TTS_BACKEND=neurlang python3 live_test/tts_backend.py（port 5010）
  3. TTS_BACKEND=meralion python3 live_test/tts_backend.py（port 5011，
     只有approved_sentences快取命中時才會真的用到）

**API key驗證**：這支API會控制機器人對病患實際講什麼話，不能不設防護就
對內網開放。用環境變數`ASSISTANT_SERVICE_API_KEY`設定，request要帶
`X-API-Key` header。**啟動時如果沒設定這個環境變數，會印出明顯警告並
以「完全不驗證」模式跑起來**——這是為了本機開發方便，但正式部署前一定
要設定，不能默默用不安全的預設值上線卻沒有任何提示。

執行：
  pip install fastapi uvicorn
  ASSISTANT_SERVICE_API_KEY=your-secret-key python3 -m uvicorn assistant_service.api:app --host 0.0.0.0 --port 8000

測試：
  curl -X POST http://127.0.0.1:8000/v1/speech \
    -H "Content-Type: application/json" -H "X-API-Key: your-secret-key" -d '{...}'
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from assistant_service import tts_router  # noqa: E402
from assistant_service.brain_response import BrainResponse  # noqa: E402
from assistant_service.response_controller import ResponseController  # noqa: E402
from tw_hokkien_tts_pipeline.protected_tokens import ProtectedTokenGuard  # noqa: E402
from tw_hokkien_tts_pipeline.structured_renderer import StructuredMedicalRenderer  # noqa: E402
from tw_hokkien_tts_pipeline.translate import TaigiLlamaTranslationBackend  # noqa: E402

# 跟 scripts/eval_translation_safety.py 用同一份詞庫, 避免API跟評估腳本
# 兩邊各自維護一份、彼此不同步
from scripts.eval_translation_safety import DRUG_LEXICON, PERSON_NAMES  # noqa: E402


class BrainResponseIn(BaseModel):
    request_id: str
    intent: str
    risk_level: str
    language: str = "zh-TW"
    response_zh: str | None = None
    slots: dict = Field(default_factory=dict)
    action: str = "speak"
    evidence_ids: list[str] = Field(default_factory=list)
    priority: int = 50


app = FastAPI(title="Taigi Assistant Speech Service", version="0.1.0")

_guard = ProtectedTokenGuard(drug_lexicon=DRUG_LEXICON, person_names=PERSON_NAMES)
_backend = TaigiLlamaTranslationBackend()
_renderer = StructuredMedicalRenderer()
_controller = ResponseController(
    guard=_guard, translation_backend=_backend, renderer=_renderer, tts_router=tts_router,
)

_API_KEY = os.environ.get("ASSISTANT_SERVICE_API_KEY")
if not _API_KEY:
    print(
        "\n"
        "========================================================================\n"
        "警告: 沒有設定 ASSISTANT_SERVICE_API_KEY 環境變數，/v1/speech 完全沒有\n"
        "身份驗證，任何連得到這個port的人都能呼叫。這支API會控制機器人對病患\n"
        "實際講什麼話，只適合本機開發用，正式部署前必須設定這個環境變數。\n"
        "========================================================================\n",
    )


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="缺少或錯誤的 X-API-Key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/speech", dependencies=[Depends(verify_api_key)])
def speech(payload: BrainResponseIn):
    brain_response = BrainResponse.from_dict(payload.model_dump())
    try:
        result = _controller.handle(brain_response)
    except Exception as exc:  # noqa: BLE001 - 這一層是服務邊界, 任何未預期例外都要轉成500而不是讓process掛掉
        raise HTTPException(status_code=500, detail=f"內部錯誤: {exc}") from exc
    return result.to_dict()
