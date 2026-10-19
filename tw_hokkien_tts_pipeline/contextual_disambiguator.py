"""
Stage 5: 上下文多音字消歧(contextual disambiguator)。

## 為什麼現在做這個, 以及做成什麼樣子

Stage 4錯誤分析(見ambiguity_gold_benchmark_v1.jsonl跟對話記錄)發現,
majority-vote在「敢」「敢會」這種case上系統性答錯——不是樣本太小的
雜訊問題, 是kám(疑問語氣「是不是」)/kánn(「大概、敢於」語意)這兩個
讀音對應到真正不同的語法功能, 純粹看詞庫哪個讀音收錄比較多筆, 永遠
無法對這種case做對判斷, 需要看整句在問問題還是在講勇氣/大概。

## 設計原則(採用使用者明確要求的路線, 不是自由生成)

  不要讓模型自由生成台羅讀音(模型可能生出詞庫根本沒有、不存在的讀音),
  而是把問題限定成「從詞庫已經查到的candidates裡選一個」的分類問題。
  模型只能回傳一個選項編號, 這個編號被嚴格驗證一定要落在candidates
  的合法範圍內, 才會被接受——回傳格式錯誤、編號超出範圍、或者
  Ollama根本連不上, 一律回傳DisambiguationResult(chosen=None, ...),
  不會硬猜一個候選頂替, 這跟這個專案一路的「沒把握就不要冒充答案」
  原則(DRUG_LEXICON的None、supplemental_lexicon的verified=false、
  gold_reading在真人標註前維持null)是同一套紀律。

## 為什麼選qwen2.5:7b-instruct, 不是這個repo已經有的Taigi-Llama-2-Translator-7B

Taigi-Llama-2-Translator-7B(見translate.py)是針對「華語->台語整句翻譯」
fine-tune過的模型, 用的是[TRANS]/[HAN]這種固定格式的翻譯任務prompt,
不是通用指令模型, 沒有理由預期它能理解「這是選擇題, 從候選裡選一個
編號」這種跟它訓練任務完全不同的指令格式。qwen2.5:7b-instruct是這台
機器上已經另外裝好的通用instruction-following模型, 適合這種分類任務,
但**這個模型本身沒有針對台語語言學做過任何fine-tune或驗證**, 它對
kám/kánn語法差異的判斷正確與否, 完全取決於它在預訓練資料裡對台語/
閩南語語法的一般知識, 品質未知, 這正是為什麼要先在12筆已驗證的gold
benchmark上實測、不能假設它會表現好。

## 已知限制(誠實列出)

  - 目前gold benchmark只有12筆已驗證資料, 用來評估這個backend的準確率
    統計上非常不可靠(見eval_ambiguity_disambiguation.py的pending_rows),
    這裡的評估結果只能當初步方向參考, 不是可信賴的最終數字。
  - 需要本機跑Ollama + qwen2.5:7b-instruct(4.7GB), 不是隨處可用的
    輕量方案, 正式部署到機器人上前需要重新考慮硬體/延遲成本。
  - 每次呼叫都是即時LLM推論, 沒有做任何快取/批次處理, 不適合直接
    當成正式pipeline裡segment.py的即時呼叫路徑使用(那裡目前還是走
    詞庫查表, 沒有接這個模組), 這裡先只做成獨立可評估的模組。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DisambiguationResult:
    chosen: str | None  # None表示模型沒有給出可信的答案, 不是猜的
    backend_name: str
    raw_response: str | None = None
    error: str | None = None  # 沒有選到候選時, 記錄原因(連線失敗/格式錯誤/編號超出範圍)


class ContextualDisambiguatorBackend(ABC):
    name: str = "base"

    @abstractmethod
    def disambiguate(
        self, sentence: str, target: str, candidates: list[str]
    ) -> DisambiguationResult:
        """從candidates裡選一個, 回傳的chosen(若非None)保證是candidates的
        其中一個字串, 不會是模型自己生成的其他字串。"""
        raise NotImplementedError


class MockContextualDisambiguator(ContextualDisambiguatorBackend):
    """離線可執行的假後端, 固定選第一個candidate, 只用於pipeline串接測試,
    不代表真實消歧能力。"""

    name = "mock"

    def disambiguate(
        self, sentence: str, target: str, candidates: list[str]
    ) -> DisambiguationResult:
        if not candidates:
            return DisambiguationResult(
                chosen=None, backend_name=self.name, error="candidates為空"
            )
        return DisambiguationResult(chosen=candidates[0], backend_name=self.name)


_PROMPT_TEMPLATE = """你是臺灣台語(臺灣閩南語)語言學專家。請根據句子語境，判斷「{target}」這個字/詞在這句話裡最正確的台羅讀音(Tâi-lô)。

句子：{sentence}
目標字/詞：{target}

候選讀音(只能選其中一個編號，不能自己創造新的讀音)：
{candidate_list}

請只回答一個阿拉伯數字(候選編號)，不要有任何其他文字、標點或解釋。"""


class OllamaContextualDisambiguator(ContextualDisambiguatorBackend):
    """透過本機Ollama呼叫通用instruction-following模型(預設
    qwen2.5:7b-instruct)做候選分類。跟translate.py的
    TaigiLlamaTranslationBackend一樣走本機Ollama /api/generate,
    但這裡刻意換一個通用指令模型, 原因見本檔案docstring。"""

    name = "ollama_contextual"

    def __init__(
        self,
        model_id: str = "qwen2.5:7b-instruct",
        ollama_url: str = "http://localhost:11434/api/generate",
        timeout: float = 60.0,
    ):
        self.model_id = model_id
        self.ollama_url = ollama_url
        self.timeout = timeout

    def disambiguate(
        self, sentence: str, target: str, candidates: list[str]
    ) -> DisambiguationResult:
        import requests

        if not candidates:
            return DisambiguationResult(
                chosen=None, backend_name=self.name, error="candidates為空"
            )
        if len(candidates) == 1:
            # 沒有真正的歧義, 不需要浪費一次LLM呼叫
            return DisambiguationResult(chosen=candidates[0], backend_name=self.name)

        candidate_list = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(candidates))
        prompt = _PROMPT_TEMPLATE.format(
            target=target, sentence=sentence, candidate_list=candidate_list
        )

        body = {
            "model": self.model_id,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            resp = requests.post(self.ollama_url, json=body, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            return DisambiguationResult(
                chosen=None,
                backend_name=self.name,
                error=f"連不到 Ollama ({self.ollama_url}): {exc}",
            )
        resp.raise_for_status()
        raw_text = resp.json().get("response", "").strip()

        match = re.search(r"\d+", raw_text)
        if not match:
            return DisambiguationResult(
                chosen=None,
                backend_name=self.name,
                raw_response=raw_text,
                error=f"回應裡找不到數字: {raw_text!r}",
            )

        idx = int(match.group()) - 1
        if not (0 <= idx < len(candidates)):
            return DisambiguationResult(
                chosen=None,
                backend_name=self.name,
                raw_response=raw_text,
                error=f"編號{idx + 1}超出候選範圍(1-{len(candidates)}): {raw_text!r}",
            )

        return DisambiguationResult(
            chosen=candidates[idx], backend_name=self.name, raw_response=raw_text
        )


_GLOSS_PROMPT_TEMPLATE = """你是臺灣台語(臺灣閩南語)語言學專家。請根據句子語境，判斷「{target}」這個字/詞在這句話裡最正確的台羅讀音(Tâi-lô)。

句子：{sentence}
目標字/詞：{target}

候選讀音(只能選其中一個編號，不能自己創造新的讀音)，每個候選附上辭典裡對應的中文釋義供你判斷：
{candidate_list}

請只回答一個阿拉伯數字(候選編號)，不要有任何其他文字、標點或解釋。"""


class OllamaGlossAwareContextualDisambiguator(ContextualDisambiguatorBackend):
    """跟OllamaContextualDisambiguator("contextual_llm_romanization_only")
    是刻意保留的兩個獨立baseline, 不是覆蓋關係——這個版本額外把每個候選
    讀音在ChhoeTaigi詞庫裡對應的中文釋義(見taihoa_dict_loader.py的
    glosses_for_surface())放進prompt, 讓LLM比對「候選釋義」跟「句子語意」
    是否吻合, 而不是只憑羅馬字拼寫本身猜測。

    動機: 純羅馬字版本(見OllamaContextualDisambiguator)在12筆gold
    benchmark上實測只有25%準確率(3/12), 比first(41.7%)/majority(50%)
    兩個簡單頻率baseline都差, 且在Stage 4認定「真正需要語境」的敢/敢會
    案例上答錯——合理懷疑是模型光看kam2/kann2這種羅馬字拼寫, 沒有能力
    分辨kám(疑問語氣「是不是」)/kánn(「大概、敢於」語意)這兩種完全不同
    的語法功能。這個版本把辭典釋義也給模型看, 直接測試「給了語意之後,
    LLM能不能真的利用上下文選對」這個問題(這是使用者明確要求的下一步
    實驗, 不是隨意的prompt調整)。

    釋義從glosses_for_surface()查詢, 若某候選讀音查無釋義(理論上不該
    發生, 因為candidates本身就是從同一個詞庫查出來的, 但仍防呆處理),
    會誠實標註「(無釋義資料)」, 不會假裝有釋義或省略不提。"""

    name = "ollama_contextual_gloss_aware"

    def __init__(
        self,
        model_id: str = "qwen2.5:7b-instruct",
        ollama_url: str = "http://localhost:11434/api/generate",
        timeout: float = 60.0,
    ):
        self.model_id = model_id
        self.ollama_url = ollama_url
        self.timeout = timeout

    def disambiguate(
        self,
        sentence: str,
        target: str,
        candidates: list[str],
        glosses: dict[str, list[str]] | None = None,
    ) -> DisambiguationResult:
        import requests

        if not candidates:
            return DisambiguationResult(
                chosen=None, backend_name=self.name, error="candidates為空"
            )
        if len(candidates) == 1:
            return DisambiguationResult(chosen=candidates[0], backend_name=self.name)

        glosses = glosses or {}
        lines = []
        for i, c in enumerate(candidates):
            gloss_list = glosses.get(c)
            gloss_text = "、".join(gloss_list) if gloss_list else "(無釋義資料)"
            lines.append(f"{i + 1}. {c} —— 釋義：{gloss_text}")
        candidate_list = "\n".join(lines)

        prompt = _GLOSS_PROMPT_TEMPLATE.format(
            target=target, sentence=sentence, candidate_list=candidate_list
        )

        body = {
            "model": self.model_id,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            resp = requests.post(self.ollama_url, json=body, timeout=self.timeout)
        except requests.exceptions.ConnectionError as exc:
            return DisambiguationResult(
                chosen=None,
                backend_name=self.name,
                error=f"連不到 Ollama ({self.ollama_url}): {exc}",
            )
        resp.raise_for_status()
        raw_text = resp.json().get("response", "").strip()

        match = re.search(r"\d+", raw_text)
        if not match:
            return DisambiguationResult(
                chosen=None,
                backend_name=self.name,
                raw_response=raw_text,
                error=f"回應裡找不到數字: {raw_text!r}",
            )

        idx = int(match.group()) - 1
        if not (0 <= idx < len(candidates)):
            return DisambiguationResult(
                chosen=None,
                backend_name=self.name,
                raw_response=raw_text,
                error=f"編號{idx + 1}超出候選範圍(1-{len(candidates)}): {raw_text!r}",
            )

        return DisambiguationResult(
            chosen=candidates[idx], backend_name=self.name, raw_response=raw_text
        )


def build_contextual_disambiguator(config) -> ContextualDisambiguatorBackend:
    if config.contextual_disambiguator_backend == "mock":
        return MockContextualDisambiguator()
    if config.contextual_disambiguator_backend == "ollama":
        return OllamaContextualDisambiguator(
            model_id=config.contextual_disambiguator_model_id,
            ollama_url=config.ollama_url,
        )
    raise ValueError(
        f"未知的 contextual_disambiguator_backend: {config.contextual_disambiguator_backend}"
    )
