"""
真正的LLM大腦：呼叫Ollama的通用對話模型（不是`translate.py`的
`TaigiLlamaTranslationBackend`——那個模型是專門微調做中文→台語翻譯的，
拿來理解使用者意圖、生成中文回覆品質沒把握，職責必須分開），把ASR辨識出來
的文字（中文或英文）轉成`BrainResponse`。

跟`voice_io_bridge.py`(yuava22規則式意圖判斷)的分工：
  - `intent_rules.decide_event_and_reply()`：快速、決定性，涵蓋3種最常見的
    病床請求(喝水/上廁所/求助)，不需要LLM推論延遲，優先當快速路徑用。
  - `OllamaBrain`(這個檔案)：規則式沒匹配到時的通用路徑，處理任何開放式輸入
    (一般對話、非那3種預設請求的其他需求)——這是`PLAN.md`裡明確標示過的
    「還沒接真正的Ollama大腦+RAG」缺口，大腦(LLM)跟RAG(`evidence_ids`
    檢索)這次都補上了，見下方「RAG」章節說明整合方式。

**大腦自己標的risk_level/slots不能被信任**：這裡的system prompt要求LLM
自己判斷風險等級並填slots，但`response_controller.py`的
`enforce_deterministic_risk_level()`才是最終防線(只能往上拉、不能往下降)，
這裡不重複做那層防護，只是盡量讓LLM的輸出「配合」規則式檢查(drug/dose/
negation欄位盡量填，risk_level涉及藥物就自己標high)，就算LLM標錯，規則式
那層還是會擋下來。

## RAG(2026-09-10新增)：只當輔助上下文，不繞過既有安全機制

`medical_kb.py`提供一個小型公共衛生常識知識庫(SQL關鍵字比對，不是向量
檢索，見該模組docstring)。這裡的整合方式刻意保守：知識庫查到的內容只
附加進送給LLM的訊息裡當參考資料，**LLM還是要照原本的JSON schema輸出，
一樣要走過response_controller.py完整的風險分級/安全檢查**——不會因為
知識庫查到答案就繞過去直接播放，那樣等於在既有安全機制之外另開一條路。
查到的知識庫entry id會填進回傳的`BrainResponse.evidence_ids`，讓這次
回覆用了哪些依據有跡可查。

**這仍然不是「查病歷/醫囑資料庫」**：`medical_kb.py`裡的內容是一般公共
衛生常識(血壓/血糖正常值、發燒/跌倒/失眠處理原則等)，不是特定病人的
個人化醫囑資料——回答「病人的醫囑劑量是多少」這種問題，這個知識庫一樣
答不出正確答案，跟前面`絕對不要自己編造醫療建議`的要求沒有衝突。

**沒有做的部分**：
- 對話歷史(多輪對話上下文)——目前每次呼叫都是單輪，沒有帶入之前的對話。
"""

from __future__ import annotations

import json
import re
import uuid

from assistant_service.brain_response import BrainResponse
from assistant_service.medical_kb import KnowledgeEntry, get_default_kb

DEFAULT_MODEL = "qwen2.5:7b-instruct"

_SYSTEM_PROMPT = """你是病房服務機器人的「大腦」，只負責『理解病人(或家屬)說的話、決定要回答什麼』，不負責怎麼翻譯成台語、也不負責語音合成——那是後面的安全把關層跟TTS的工作，你只需要輸出這一輪要講的中文內容跟結構化資訊。

你會收到這一刻觀察到的內容，可能只有一行(單純語音辨識文字，中文或英文都有可能)，也可能有兩行——一行是「使用者說的話」，一行是「鏡頭觀察到的畫面」(來自姿態偵測的描述，例如「使用者的手靠近嘴巴」，這種描述本身沒有語意，需要你自己判斷代表什麼需求)。如果只有語音、沒有鏡頭觀察，就只憑語音內容判斷；如果同時有語音又有鏡頭觀察，要綜合兩者判斷使用者真正的需求，兩者衝突時(例如語音說「不用了」但鏡頭觀察到疑似求助動作)以語音內容為準，因為語音是明確的語意表達，鏡頭觀察只是姿態推測。你必須只回傳一個JSON物件，不要有任何JSON以外的文字、不要用markdown code block，格式如下：

{
  "intent": "簡短英文snake_case意圖代碼，例如medication_question/request_staff/family_notice/general_chat/emergency",
  "risk_level": "high" 或 "medium" 或 "low",
  "response_zh": "要對病人講的中文回覆(繁體中文；不管使用者用中文還是英文問，這裡永遠輸出中文)",
  "response_en": "response_zh的英文翻譯(給不懂中文/台語的家屬或工作人員補充聽的，意思要跟response_zh一致，不要多加內容)",
  "slots": {"drug": null或藥名字串, "dose": null或劑量字串, "time": null或時間字串, "person": null或人名字串, "negation": true或false},
  "action": "speak"
}

風險判斷原則(你的判斷只是參考，後面還有規則式的強制升級機制做最終把關，不是只靠你判斷)：
- 只要牽涉到藥物名稱、劑量、是否服藥、過敏、緊急狀況(胸痛/呼吸困難/意識不清)，risk_level一定要標"high"，並且把牽涉到的藥名/劑量/是否服藥(negation)填進slots，不要留空——這樣後面的規則式檢查才抓得到，就算你這裡判斷錯也有第二層防護。
- 一般問候、日常生活需求(不涉及藥物/醫囑)標"low"或"medium"即可。

絕對不要自己編造醫療建議：如果病人問的是「要不要換藥」「可以加劑量嗎」這種需要醫療專業判斷的問題，不要自己生成具體建議內容，response_zh只能說類似「這個問題我會轉達給護理人員確認」，risk_level標"high"，action維持"speak"(讓病人聽到「已轉達」這句話本身)。

只回傳JSON物件本身，沒有其他文字，也不要用```包起來。"""


def _build_kb_context(entries: list[KnowledgeEntry]) -> str:
    """把知識庫查到的條目組成一段額外的system訊息，明確要求LLM「這只是
    參考資料，還是要照JSON schema輸出、還是要遵守原本的風險判斷原則」——
    不能讓LLM誤以為看到這段參考資料就可以放寬「絕對不要自己編造醫療建議」
    的要求，這段參考資料本身也可能被使用者的問題誤觸發(關鍵字比對不是
    精準語意匹配)，需要LLM自己判斷是否真的相關。"""
    lines = [
        "以下是知識庫查到、可能跟這句話有關的參考資料(用關鍵字比對找到的，",
        "不保證完全對應這句話的意思，請自行判斷是否真的相關；不相關就忽略，",
        "不要硬套)。如果相關，請優先根據這些內容回答，不要跟這些內容矛盾；",
        "仍然要照原本規定的JSON schema輸出、仍然要遵守風險判斷原則——",
        "看到這裡有參考資料不代表可以放寬「不自己編造醫療建議」的要求。",
        "",
    ]
    for entry in entries:
        lines.append(f"- [{entry.category}] {entry.question}：{entry.answer}")
    return "\n".join(lines)


class OllamaBrainError(RuntimeError):
    pass


class OllamaBrain:
    """呼叫Ollama的通用對話模型，把使用者說的話轉成BrainResponse。"""

    name = "ollama_brain"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        ollama_url: str = "http://localhost:11434/api/chat",
        timeout: float = 60.0,
        kb=None,
    ):
        self.model = model
        self.ollama_url = ollama_url
        self.timeout = timeout
        # kb可注入假物件方便測試(不用每次都真的建SQLite知識庫)，預設用
        # process共用的singleton(見medical_kb.get_default_kb())。
        self._kb = kb if kb is not None else get_default_kb()

    def generate(self, user_text: str, request_id: str | None = None) -> BrainResponse:
        import requests

        request_id = request_id or f"llm_{uuid.uuid4().hex[:8]}"
        kb_matches = self._kb.search(user_text)
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        if kb_matches:
            messages.append({"role": "system", "content": _build_kb_context(kb_matches)})
        messages.append({"role": "user", "content": user_text})

        body = {
            "model": self.model,
            "messages": messages,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2},
        }
        try:
            resp = requests.post(self.ollama_url, json=body, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            raise OllamaBrainError(
                f"連不到Ollama({self.ollama_url})，請確認`ollama serve`有在跑，"
                f"且已經pull過{self.model}(`ollama pull {self.model}`)"
            ) from exc
        resp.raise_for_status()
        raw = resp.json()
        content = raw.get("message", {}).get("content", "")

        parsed = self._parse_json(content)
        parsed.setdefault("request_id", request_id)
        parsed.setdefault("language", "zh-TW")
        # 大腦自己沒標priority時，用risk_level概略推斷播放優先權(高風險內容
        # 通常也比較急，可能需要插播)——這只是預設值，跟response_controller
        # 的risk_level規則式升級是兩件獨立的事，不互相取代。
        parsed.setdefault("priority", 80 if parsed.get("risk_level") == "high" else 50)
        # RAG：不管LLM自己的JSON輸出有沒有填evidence_ids欄位，都用我們
        # 實際查到的知識庫entry id覆蓋——這個欄位的真實性不該讓LLM自己
        # 決定(它也不知道我們背後查了什麼)，一律由呼叫端如實填入。
        parsed["evidence_ids"] = [entry.id for entry in kb_matches]
        return BrainResponse.from_dict(parsed)

    @staticmethod
    def _parse_json(content: str) -> dict:
        """理論上`format="json"`會強制Ollama只輸出合法JSON，但這裡仍然防禦性
        處理解析失敗的情況(模型不支援format=json、輸出被截斷等)——回傳空dict
        讓呼叫端組出來的BrainResponse在Response Controller的validate()階段
        被規則式擋下來(status="rejected"+fail-safe回覆)，而不是讓例外往上
        炸穿整個request。"""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            return {}
