# 台語機器翻譯研究計畫（Mandarin → Taiwanese Hokkien MT）

低資源中文—臺灣台語機器翻譯研究，結合書寫正規化、詞彙消歧與台語語音合成，
最終服務於醫療服務機器人的台語輸出能力。完整研究計畫、實測教訓、已驗證文獻與資源清單見 [`PLAN.md`](./PLAN.md)。

## 目前狀態

- 階段0-3已有實際產出：200句測試集、兩個真跑過的 baseline（辭典最長詞匹配 / Taigi-Llama-2-Translator-7B）、
  量化比較報告（[`reports/stage2_baseline_comparison.md`](./reports/stage2_baseline_comparison.md)）、
  安全檢查層腳本與結果（[`reports/stage3_safety_checks.md`](./reports/stage3_safety_checks.md)）
- 母語者驗證平台已上線，見下方

## 母語者驗證平台

**測試連結：https://heisenberg7299.github.io/taigi-mt-project/**
**開發者進度頁：https://heisenberg7299.github.io/taigi-mt-project/progress.html**
（用Firebase email/password登入才看得到）

靜態網站（`docs/`），GitHub Pages + Firebase Firestore，**不依賴任何一台特定電腦
開機或連網**——這是2026-08-01從本機Flask+Cloudflare Tunnel版本遷移過來的，
舊版本機服務已經關閉。沿用 `english-vocab-app` 專案的同一個Firebase，資料存在
獨立的 `taigi_reviews` / `taigi_tokens` collection，不會跟其他app的資料混。

讓台語母語者逐句驗證機器翻譯候選答案（文字＋語音），每輪隨機抽10句，標記
正確/需修改/錯誤並可直接編輯，結果即時存進Firestore。測試者輸入名字後可以
直接開始；同一個名字（含換裝置）會接回同一份進度。

本機開發/預覽：
```bash
cd docs && python3 -m http.server 8000
# 瀏覽器開 http://127.0.0.1:8000
```
改完 `docs/` 底下的檔案，`git push` 到 main 分支，GitHub Pages 會自動重新部署。
Firestore 安全規則定義在 `english-vocab-app` repo 的 `firestore.rules`（同一個
Firebase專案），改規則要在那邊 `firebase deploy --only firestore:rules`。

`webapp/`（舊版Flask）保留在repo裡供參考，已停用，不建議再啟動——目前所有
真實測試資料都在Firestore，本機 `data/human_review/` 底下的舊資料是遷移前的
歷史存檔（遷移腳本：`scripts/migrate_to_firestore.py`）。

## 開發者即時測試工具

跟上面的驗證平台不同：這是給開發者自己測任意新句子用的，不是固定200句，
也不給外部測試者用，只在本機跑，需要Ollama和neurlang模型都在本機才能動。

網頁版（`live_test/`）：
```bash
source venv/bin/activate
python3 live_test/app.py
# 瀏覽器開 http://127.0.0.1:5002
```
輸入任意中文句子，按下按鈕後跑完整pipeline（Taigi-Llama翻譯 + neurlang語音
合成），幾秒後網頁上直接顯示台語漢字並播放語音。

指令列版（`scripts/zh_to_taigi_speech.py`，一次可測多句，用Finder開結果資料夾）：
```bash
python3 scripts/zh_to_taigi_speech.py "你的中文句子"
python3 scripts/zh_to_taigi_speech.py "句子1" "句子2" "句子3"
```

兩者都需要venv是 `transformers<5`（neurlang用coqui-tts的要求）——如果剛測過
MERaLiON（需要`transformers>=5.3.0`），記得先 `pip install "transformers<5"` 切回來。

## 環境設置

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask jieba huggingface_hub coqui-tts[codec] "transformers<5" "setuptools<81" sentencepiece datasets taibun

python3 scripts/download_datasets.py      # 下載教育部辭典 / iCorpus-100 / TaigiSpeech
python3 scripts/build_test_set.py         # 產生 200 句測試集
python3 scripts/run_dict_baseline.py      # baseline 1：辭典最長詞匹配
python3 scripts/run_taigi_llama_baseline.py  # baseline 2：需先用 Ollama 跑 Taigi-Llama-2-Translator-7B GGUF
python3 scripts/run_stage3_checks.py      # 安全檢查層
python3 scripts/synthesize_audio.py       # 合成候選翻譯的語音（需要 models/neurlang-vits-suisiann/ 模型權重，另外下載，見 PLAN.md）
python3 scripts/run_tts_benchmark.py      # 階段4：統一TTS候選跑分（見 scripts/tts_benchmark/，新增候選寫個adapter就好）
```

模型權重（`models/`）、原始資料集下載（`data/raw/`）與合成音檔（`tests/audio/`）不進版控，
需依上面指令重新產生。授權細節見 `data/licenses/`（下載後產生）與 `PLAN.md` 資源表。
