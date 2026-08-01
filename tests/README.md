# 200句測試集與 Baseline 比較

## 檔案

- `test_set_200.jsonl` — 200句中文來源句，6個分類（見 `scripts/build_test_set.py`）
- `baseline_taigi_llama.jsonl` — Baseline 2（Taigi-Llama-2-Translator-7B，GGUF Q4_K_M，本機 Ollama）產生的台語漢字候選
- `baseline_dict_match.jsonl`（待建立）— Baseline 1：辭典最長詞匹配
- `baseline_rule.jsonl`（待建立）— Baseline 3：現有規則/翻譯流程（今天測試過的小型辭典替換版本）

## 分類與安全檢查對應

| category | 數量 | check_type | 對應 PLAN.md 安全檢查 |
|---|---|---|---|
| daily | 40 | - | 一般流暢度 |
| medical | 40 | - | 醫療術語白名單 |
| robot_service | 40 | - | 一般流暢度 |
| negation_risk | 30 | negation | 否定詞是否遺失 |
| numbers_id | 20 | number_consistency | 數字/病房號/時間是否一致 |
| code_mixing | 30 | code_mixing | 中英台混合句是否崩潰 |

## 下一步

1. 三個 baseline 都跑完後，逐句比較，特別聚焦 `negation_risk` 和 `numbers_id` 兩類（醫療安全風險最高）
2. 找台語母語者（至少1位）校對 `baseline_taigi_llama_han` 欄位，標記 `verified: true`，作為 `nan_han` 參考答案來源之一
3. 三個 baseline 比較完，寫 `reports/stage2_baseline_comparison.md`，回答 PLAN.md 階段2要回答的問題：辭典知識和預訓練分別帶來多少改善
