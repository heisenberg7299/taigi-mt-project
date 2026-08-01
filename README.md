# 台語機器翻譯研究計畫（Mandarin → Taiwanese Hokkien MT）

低資源中文—臺灣台語機器翻譯研究，結合書寫正規化、詞彙消歧與台語語音合成，
最終服務於醫療服務機器人的台語輸出能力。完整研究計畫、實測教訓、已驗證文獻與資源清單見 [`PLAN.md`](./PLAN.md)。

## 目前狀態

- 階段0-3已有實際產出：200句測試集、兩個真跑過的 baseline（辭典最長詞匹配 / Taigi-Llama-2-Translator-7B）、
  量化比較報告（[`reports/stage2_baseline_comparison.md`](./reports/stage2_baseline_comparison.md)）、
  安全檢查層腳本與結果（[`reports/stage3_safety_checks.md`](./reports/stage3_safety_checks.md)）
- 母語者驗證平台（`webapp/`）已完成，見下方

## 母語者驗證平台

Flask 網頁工具，讓台語母語者逐句驗證機器翻譯候選答案（文字＋語音），每輪隨機抽10句，
標記正確/需修改/錯誤並可直接編輯，結果存檔後可匯總成訓練/評估語料。

**目前測試連結（透過 Cloudflare Tunnel 打通到開發者本機，只要那台機器開著就有效，
重啟過會換新網址，失效請找開發者要新連結）：**

https://ate-state-engineering-bend.trycloudflare.com

測試者輸入名字後，系統會給一組專屬的 `?t=<token>` 網址，請加入書籤才能之後接續填寫，
不要用別人的名字或連結（每個人的連結不可互通、不可猜測）。

本機執行：
```bash
cd webapp
source ../venv/bin/activate   # 需先跑過下面「環境設置」
python3 app.py
# 瀏覽器開 http://127.0.0.1:5001
```

## 環境設置

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask jieba huggingface_hub coqui-tts[codec] "transformers<5" "setuptools<81"

python3 scripts/download_datasets.py      # 下載教育部辭典 / iCorpus-100 / TaigiSpeech
python3 scripts/build_test_set.py         # 產生 200 句測試集
python3 scripts/run_dict_baseline.py      # baseline 1：辭典最長詞匹配
python3 scripts/run_taigi_llama_baseline.py  # baseline 2：需先用 Ollama 跑 Taigi-Llama-2-Translator-7B GGUF
python3 scripts/run_stage3_checks.py      # 安全檢查層
python3 scripts/synthesize_audio.py       # 合成候選翻譯的語音（需要 models/neurlang-vits-suisiann/ 模型權重，另外下載，見 PLAN.md）
```

模型權重（`models/`）、原始資料集下載（`data/raw/`）與合成音檔（`tests/audio/`）不進版控，
需依上面指令重新產生。授權細節見 `data/licenses/`（下載後產生）與 `PLAN.md` 資源表。
