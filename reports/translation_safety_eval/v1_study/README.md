# Study v1 — 凍結存檔，不可覆寫

日期：2026-08-03。這個資料夾是 `reports/translation_safety_4method_comparison.md`
（evaluator v1）第一次執行的完整原始結果，**永久保留，不再修改、不再刪除、
不用新評分器重算後取代這裡的數字**。`SHA256SUMS.txt` 是當時檔案的雜湊值，
之後如果懷疑內容被動過，可以用它驗證。

## 內容

- `translation_safety_dev_30.jsonl` / `translation_safety_locked_20.jsonl`：
  當時用的50句資料集（evaluator v1當下的版本，還沒有v2補的同義詞）
- `eval_translation_safety_v1.py`：當時用的評分腳本（`scripts/eval_translation_safety.py`
  在這個commit時間點的快照，之後那支腳本可能會為了v2繼續演進，這裡凍結一份）
- `dev_metrics.json` / `dev_raw_results.json`：dev set(30句)結果
- `locked_metrics.json` / `locked_raw_results.json`：locked set(20句)結果，
  **只執行過一次**
- `translation_safety_4method_comparison.md`：完整報告

## 重要：這20句locked set已經失效，不能再當作「未見過的泛化測試」

因為我們已經查看過這20句的輸出、也已經知道其中的Hokkien同義詞覆蓋問題
（見報告「Development set 調整記錄」跟「誠實的重點」章節），這20句
**不能再被宣稱為任何新方法的unseen locked test**。之後如果需要對這20句
重新評分（例如用evaluator v2重跑），只能標示成 **post-hoc evaluator
analysis**，不是新的locked測試結果。

真正要驗證新方法/新評分器泛化能力，必須用另外建立的locked v2測試集
（見 `reports/translation_safety_eval/v2_study/`，若尚未建立代表這個步驟
還沒執行到）。
