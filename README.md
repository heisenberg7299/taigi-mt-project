# 台語機器翻譯研究計畫（Mandarin → Taiwanese Hokkien MT）

低資源中文—臺灣台語機器翻譯研究，結合書寫正規化、詞彙消歧與台語語音合成，
最終服務於醫療服務機器人的台語輸出能力。完整研究計畫、實測教訓、已驗證文獻與資源清單見 [`PLAN.md`](./PLAN.md)。

## 目前狀態

- **翻譯**：以開源 Taigi-Llama-2-Translator-7B 當baseline，在200句精選測試集上表現不錯
  （量化比較見 [`reports/stage2_baseline_comparison.md`](./reports/stage2_baseline_comparison.md)）。
  但額外測試10句**不在**測試集裡的新句子後發現：**40%出現嚴重語意流失，其中包含
  醫療安全等級的風險**（例如藥名整個消失）——這是目前最重要的風險發現，已有初步
  解法原型（Protected Token機制），但還沒到能保證100%可靠的程度。詳見
  [`reports/safety_critical_translation_failures.md`](./reports/safety_critical_translation_failures.md)
- **語音合成**：主力用 neurlang VITS（快、CPU可即時），另外實測過
  MERaLiON-OmniVoice-Hokkien-TTS（品質較好，但比即時慢約35倍，適合離線生成、
  不適合即時互動）。完整候選比較見 [`reports/stage4_tts_candidates.md`](./reports/stage4_tts_candidates.md)
- **母語者驗證平台已上線**：邀請台語母語者對翻譯候選逐句打分，24小時可用，見下方
- **開發者測試playground**：可以當場輸入任意中文句子、即時聽到台語語音輸出、
  比較不同TTS引擎，見下方「開發者即時測試工具」

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
只在本機跑，需要Ollama和TTS模型都在本機才能動，本機關機/沒開這個服務就
連不到——這點跟已經遷到GitHub Pages+Firebase、不依賴任何一台電腦的驗證
平台不一樣。

網頁版（`live_test/`）可以在同一個頁面切換 neurlang（快）/ MERaLiON（品質
較好但慢約35倍）兩種語音引擎，**也可以選翻譯策略**：「簡單版」（直接呼叫
Ollama，跟以前一樣）或「Adaptive Protected Token」（重用
`tw_hokkien_tts_pipeline/adaptive_translation.py` 的雙路翻譯+安全檢查，
句子裡含有已收錄的藥名/人名時會觸發保護，畫面上會顯示選用了哪個候選、
偵測到哪些Protected Token，兩個候選都不安全時會顯示fail closed擋下的
原因，不會硬合成語音）。這個網頁沒有結構化表單輸入，候選C(結構化模板)
不會被觸發，只會用到候選A/B。一鍵啟動/關閉：

```bash
ollama serve   # 先確保這個有在跑（另開一個終端機視窗）

bash scripts/start_live_test.sh   # 啟動neurlang後端+MERaLiON後端+gateway+對外tunnel
bash scripts/stop_live_test.sh    # 全部關閉
```
啟動完成後終端機會印出本機網址（`http://127.0.0.1:5002`）跟對外網址
（`CURRENT_TUNNEL_URL.txt`，同一個Wi-Fi的其他裝置或外部網路都能連，網址
每次啟動都會變，斷線每60秒自動偵測重啟——沿用驗證平台當初用過的
watchdog機制，只是現在指到這個開發測試用的gateway，不是驗證平台，驗證
平台本身已經不需要靠本機了）。

背後架構：因為neurlang跟MERaLiON要的transformers版本互斥（`<5` vs
`>=5.3.0`），沒辦法同一個process同時載入，所以拆成三個process——
gateway（`live_test/app.py`，只做翻譯+轉發，用主venv）+ 兩個獨立的
`live_test/tts_backend.py`（各自跑在獨立venv，內部port互不干擾），
`start_live_test.sh`/`stop_live_test.sh` 會照順序啟動/關閉全部。

指令列版（`scripts/zh_to_taigi_speech.py`，只用neurlang、一次可測多句，用
Finder開結果資料夾），要另外手動確保主venv是 `transformers<5`：
```bash
source venv/bin/activate
python3 scripts/zh_to_taigi_speech.py "你的中文句子"
python3 scripts/zh_to_taigi_speech.py "句子1" "句子2" "句子3"
```

## 新架構探索：`tw_hokkien_tts_pipeline/`

跟上面`live_test/`「單一LLM直接輸出台語漢字→TTS直接吃漢字」的做法不同，這是
一個分層更明確的骨架：**遮罩(Protected Token) → 翻譯 → 斷詞轉台羅 → 正規化/
連讀變調 → 還原 → TTS**，把藥名/人名保護做成pipeline的第一層而不是事後補救，
還有一個`require_full_protected_coverage`開關——查無人工校正過的台羅讀音時
直接擋下不合成，而不是讓TTS用猜的發音念藥名。

**目前所有backend都是mock**（翻譯/斷詞/TTS都是佔位邏輯，不是真的在跑），
用途是先把分層架構、debug trace、安全門檻的邏輯骨架驗證過一遍：
```bash
pip install -r tw_hokkien_tts_pipeline/requirements.txt
python3 -m pytest tw_hokkien_tts_pipeline/tests/ -v

python3 -m tw_hokkien_tts_pipeline.cli "請記得在晚餐後服用盤尼西林。" \
  --output-dir ./pipeline_output
```
換成真實backend前要做的事、各層現況，見 [`tw_hokkien_tts_pipeline/README.md`](./tw_hokkien_tts_pipeline/README.md)。

`live_test/`（neurlang+MERaLiON）目前維持現有、已驗證能實際出聲的版本，當作
保底方案，不受這個探索中的新方向影響。

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

MERaLiON-OmniVoice-Hokkien-TTS 要的 `transformers>=5.3.0` 跟主venv用的
`transformers<5`（neurlang/coqui-tts的要求）互斥，所以另外開一個獨立venv：
```bash
python3 -m venv venv_meralion
source venv_meralion/bin/activate
pip install torch torchaudio torchcodec omnivoice soundfile flask
```
