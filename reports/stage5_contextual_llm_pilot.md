# Stage 5 試驗：通用LLM能不能做台語多音字上下文消歧

日期：2026-08-27
測試對象：`tw_hokkien_tts_pipeline/tests/data/ambiguity_gold_benchmark_v1.jsonl`
已驗證的12筆gold case（`native_verified=true` 且未被 `excluded_from_evaluation` 排除）
模型：本機Ollama `qwen2.5:7b-instruct`（4.7GB, Q4_K_M量化），temperature=0

## 背景

Stage 4錯誤分析發現，`majority`（詞庫多數決）在「敢」「敢會」這類case上
系統性答錯——不是樣本雜訊，是kám（疑問語氣「是不是」）/kánn（「大概、
敢於」語意）對應到真正不同的語法功能，純粹的頻率統計永遠無法對這種
case做對判斷。這個試驗回答一個明確問題：**通用instruction-following
LLM，光靠句子語境，能不能真的選對候選讀音？**

## 方法

三個獨立backend（見`tw_hokkien_tts_pipeline/contextual_disambiguator.py`），
全部設計成「從詞庫候選裡選一個編號」的分類問題，不允許模型自由生成
讀音——編號格式錯誤、超出範圍、或連不上Ollama，一律回傳`chosen=None`，
不會硬猜：

1. `contextual_llm_romanization_only`：只給候選的台羅羅馬字（例如
   `kam2`/`kann2`），不給任何語意資訊。
2. `contextual_llm_gloss_aware`：額外把每個候選在ChhoeTaigi詞庫裡對應
   的中文釋義（例如kám=「怎麼、敢」、kánn=「大約、大概、大膽、有勇氣、
   恐怕、敢於」）放進prompt，讓模型比對候選釋義跟句子語意是否吻合。

跟`first`（詞庫第一筆）、`majority`（詞庫多數決）兩個既有baseline在
完全同一批12筆case上並列比較。

## 結果

| 方法 | 準確率 |
|---|---|
| first | 5/12 = 41.7% |
| majority | 6/12 = 50.0% |
| contextual_llm_romanization_only | 3/12 = 25.0% |
| contextual_llm_gloss_aware | 4/12 = 33.3% |

逐筆結果見`scripts/eval_contextual_disambiguator_gloss.py`執行輸出。

## 結論：這是一個負結果（negative result），但有價值

- **兩個LLM版本都輸給簡單的詞庫頻率統計**，不是統計雜訊——樣本雖小
  (n=12)，但方向一致：通用7B模型目前沒有顯示出「值得繼續做prompt
  engineering」的訊號。
- 加入辭典釋義有帶來小幅改善（25%→33%），證明語意資訊確實有幫助，
  但幅度遠不足以追上majority的50%，更遠遠不到「可信賴」的水準。
- **最關鍵的失敗案例**：「敢」「敢會」——這兩筆是Stage 4認定「真正
  需要語境理解」的案例——gloss-aware版本即使拿到正確的中文釋義，
  仍然兩次都選錯（跟majority一樣選了kann2，但gold是kam2）。這代表
  問題不是「模型缺乏候選讀音的語意資訊」，而是**這個通用模型即使
  給了正確釋義，也沒能力把句子的語法功能（疑問語氣 vs 大概/敢於）
  跟正確釋義對應起來**——是台語語法理解本身的極限，不是prompt設計
  的問題。
- 唯一一個gloss-aware版本答對、純羅馬字版本答錯的案例是「轉」：
  tng2的釋義「調處、調解」明顯跟醫療轉診語境不符，模型抓到了這個
  訊號選對tsoan2——證明釋義並非完全沒用，只是不夠穩定、不夠普遍。

## 決策（依事先訂好的門檻）

門檻：gloss-aware準確率 ≥ 8/12 → 有明顯訊號，擴充gold benchmark到
50-100筆；3-5/12 → 停止對這個模型做prompt tuning，改考慮小型
supervised contextual ranker。

實測4/12，落在「停止prompt tuning」區間。**下一步不是換prompt或換
更大的通用LLM，是先把gold benchmark從12筆擴充到≥100筆，之後再評估
是否訓練專用的小型supervised contextual ranker（候選逐一評分的
cross-encoder設計，不是固定分類器——理由：新的多音字只要詞庫有候選
跟釋義，理論上仍可推論，不需要每次重新訓練新的class）**，且訓練前
必須做「同字未見語境」跟「未見surface」兩種切分評估，避免模型只是
記住「敢固定念kam2」這種死記硬背、而不是真的學會利用上下文判斷。

## 現有樣本量的限制

本報告的12/12比較全部基於Stage 3已標註完成的gold case，樣本數本身
就小到讓「哪個方法比較強」這個結論的可信度有限——不只是LLM輸的這個
結論可能隨樣本擴大而改變，`majority`目前領先的50%同樣未經大樣本驗證。
這是本報告下一步要解決的問題，不是本報告能回答的問題。
