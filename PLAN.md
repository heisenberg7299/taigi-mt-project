# 低資源中文—臺灣台語機器翻譯研究計畫（Safe Medical Taiwanese Translation）

研究定位：**低資源中文—臺灣台語機器翻譯，結合書寫正規化、詞彙消歧與台語語音合成**，最終服務於醫療服務機器人的台語輸出能力。

**2026-08-02更新**：實測發現Taigi-Llama在200句curated測試集之外的新句子上，
40%（4/10）出現safety-critical等級的語意流失（見
`reports/safety_critical_translation_failures.md`）——不是隨機亂翻，是流暢、
通順但關鍵資訊（人名/藥名/職稱/情境）消失或被幻覺成別的內容，這種錯誤比
明顯的錯譯更危險，BLEU這類傳統指標也量不出來。**研究定位因此收斂成
「Safe Medical Taiwanese Translation」，不只是「翻得通不通」，而是「哪些
資訊類型絕對不能讓模型自由生成」。**

**目前優先順序改成 P0（翻譯安全）> P1（TTS品質）**：如果翻譯階段已經把
「盤尼西林」這類關鍵藥名吃掉，後面TTS再標準也沒有意義。之前重心在TTS
（階段4、OOV audit）的工作仍然有效、仍然要做，但階段6的模型選擇不能再
繞過翻譯安全這一層。

## 技術鏈

```
中文文字／中文語音
      ↓
中文 ASR（語音輸入時）
      ↓
中文→台語機器翻譯（研究核心）
      ↓
台語漢字／台羅正規化
      ↓
台語 TTS
      ↓
台語語音
```

真正困難的部分不是 TTS，是「華語語意 → 自然台語句子」這一步——涉及詞義選擇、語序轉換、語氣詞、慣用句、多種書寫系統。**單靠辭典逐詞替換已驗證行不通**（見下方「今天的實測教訓」）。

---

## 今天的實測教訓（2026-07-30 ~ 07-31）

已經實測過，作為本計畫的前提，不要重複踩坑：

1. **CosyVoice3-0.5B**：無可用台語支援。用「請用台語表達」指令測試，Whisper 回轉錄證實輸出對不上原文語意；連官方驗證過的廣東話方言指令都幾乎跟無指令版本一樣，方言指令機制本身不可靠。已刪除本機安裝。
2. **Qwen3-TTS-12Hz-1.7B-CustomVoice**：無可用台語支援（無台語母語音色，僅北京話/四川話兩種中文方言）。CPU 載入模型耗時 49 分鐘，不適合互動情境。已刪除本機安裝。
3. **neurlang/coqui-vits-suisiann-minnan-hokkien**：唯一驗證過真的會講台語的免費模型。VITS 架構，CPU 上 RTF ~0.11-0.13（比即時快 8 倍），內建 pygoruut 音標轉換器可正確產生台語 IPA 音標（含聲調）。授權 CC-BY-SA-4.0。**但只做「漢字→台語讀音」逐字轉換，不做「中文詞彙→台語詞彙」轉換**——這正是本研究要解決的問題。
4. **純字典替換（9,864 筆教育部辭典反查）**：規模擴大後出現嚴重錯誤，包括「我」被轉成「朕」（皇帝自稱）、「協助」變「支持」、「前面」變「對面」、固定用語「對不起」被拆散成「著不起」。**證實純規則/字典替換不足以泛用**，需要句子級別的翻譯模型。
5. 語意反轉陷阱字範例：台語「走(tsáu)」= 跑，「行(kiânn)」= 走路。逐字硬讀會把「請慢慢走」講成「請慢慢跑」，語意完全相反。這類陷阱在醫療情境是安全風險，不只是發音不準的問題。

---

## 已驗證的文獻（2026-07-31 逐篇核對過摘要，非幻覺）

| 文獻 | 重點 | 對本計畫的價值 |
|---|---|---|
| [Enhancing Taiwanese Hokkien Dual Translation by Exploring and Standardizing of Four Writing Systems](https://arxiv.org/abs/2403.12024)（LREC-COLING 2024） | LLaMA2-7B 微調，26.3萬筆平行資料，處理漢字/POJ/台羅/漢羅四種書寫系統 | 證明書寫正規化該獨立成一層；資料處理方法可參考 |
| [Exploring Methods for Building Dialects-Mandarin Code-Mixing Corpora](https://arxiv.org/abs/2301.08937) | 台語—華語混用語料建構，XLM 遷移學習 | 中英台混合句（如「幫我叫 nurse」）的處理方法 |
| [Breeze Taigi: Benchmarks and Models for Taiwanese Hokkien Speech Recognition and Synthesis](https://arxiv.org/abs/2603.19259)（2026） | Whisper 微調 ASR，~10,000小時合成語料，30.13% CER benchmark | TTS/ASR 評測基準可直接採用，而非只憑主觀聽感 |
| [TG-ASR](https://arxiv.org/abs/2602.22039)（LREC 2026） | 翻譯導引 ASR，YT-THDC 語料（30小時台語戲劇+華語字幕+人工校正轉錄），14.77% CER 相對降幅 | 資料建構方法論：影片語音+既有字幕+人工校正=三方對齊資料 |
| [Evaluating Self-supervised Speech Models on a Taiwanese Hokkien Corpus](https://arxiv.org/pdf/2312.06668) | 內含 iCorpus 描述（83,544句平行語料）；模型大小不是決定性因素 | 平行語料規模參考；選 ASR/TTS 底座模型的判準 |

**待查證/存疑**：TAT Corpus 官網未列出具體報價（不是 US$1,350，此數字查無出處，需直接聯繫 ACLCLP）。

---

## 已驗證的公開資源

| 資源 | 授權 | 規模 | 用途 | 備註 |
|---|---|---|---|---|
| [Taigi-Llama-2-Translator-7B](https://huggingface.co/Bohanlu/Taigi-Llama-2-Translator-7B) | **CC-BY-NC-SA-4.0**（已核實） | 26.3萬筆平行資料微調 | **首選 baseline**，中/英/台(HAN/POJ/HL)互譯 | 非商業限定，只當 baseline／teacher model，不可部署商用；已用 Ollama 本機跑 GGUF Q4_K_M（4.2GB），prompt 格式 `[TRANS]\n{句子}\n[/TRANS]\n[HAN]\n` |
| [Bohanlu/iCorpus-100](https://huggingface.co/datasets/Bohanlu/iCorpus-100) | **CC BY-NC-4.0**（已核實） | 100句（完整 iCorpus 子集） | 資料格式測試、pipeline 開發 | 非商業限定；完整版 iCorpus 取得方式待確認 |
| 教育部臺灣台語常用詞辭典（[g0v/moedict-data-twblg](https://github.com/g0v/moedict-data-twblg)） | 開源 | 14,489條目 | 辭典約束、術語檢查、未登錄詞 fallback | 已下載至本機，見 `~/hokkien-tts-test/dict-twblg.json` |
| [TaigiSpeech](https://huggingface.co/datasets/TaigiSpeech/TaigiSpeech) | **CC-BY-4.0**（已核實） | 3,079筆音檔，21位語者，8種服務/緊急意圖 | 台語語音→意圖分類（方向1，見下） | 醫療/長照情境高度相關 |
| [臺灣台語語料庫應用檢索系統](https://tggl.naer.edu.tw/) | 各子語料各自授權 | 208小時標註語音 | 查詢詞彙在自然句中的搭配，解決辭典多候選消歧問題 | 批次爬取前需確認各子語料授權 |
| [BreezeASR-Taigi](https://huggingface.co/MediaTek-Research/Breeze-ASR-26) | 待查 | Whisper微調 | 台語語音→華語文字（意圖理解用） | 非逐字台語轉錄，適合「理解意圖」而非「保留原句」 |
| [NUTN Whisper-Taiwanese-v0.5](https://huggingface.co/NUTN-KWS/Whisper-Taiwanese-model-v0.5) | CC BY-NC-4.0 | ~90小時 | ASR 比較基準 | 非商業授權，不可直接產品化 |
| TAT Corpus | 需申請，價格未知 | ~300小時，600位語者 | 高品質語音庫 | 先不申請，等免費資源證實不足再考慮 |

---

## 系統分成兩個獨立方向，不要一開始就端到端整合

### 方向 1：機器人理解台語（台語輸入）
```
台語語音 → 台語ASR/speech encoder → 意圖分類 → 槽位擷取 → 服務任務
```
可直接用 TaigiSpeech 起步，最快出成果。

### 方向 2：機器人講台語（台語輸出，本計畫主軸）
```
系統中文回答 → 中文→台語翻譯 → 用字/術語檢查 → 台語TTS → 播放
```

兩者分開驗證，才能定位錯誤來源（是 ASR 錯、翻譯錯、意圖辨識錯，還是 TTS 錯）。

---

## 執行階段（方向 2 為主）

- [x] **階段0：內部格式標準化** — 內部文字統一用「教育部推薦台語漢字」，輔助保留台羅欄位；訂出 JSON schema（見 `data/schema.md`）
- [x] **階段1：資源盤點與下載腳本** — `scripts/download_datasets.py`，每筆資料另存來源/日期/授權/可否商用/可否再散布
- [x] **階段2（進行中）：三個 baseline 比較** — 200句測試集已建（`tests/test_set_200.jsonl`）。(1) 辭典最長詞匹配 已跑完，確認不可用 (2) Taigi-Llama-2-Translator 已跑完，品質足夠當研究參考但授權排除商用 (3) 現有規則/翻譯流程 待量化重跑。結果見 `reports/stage2_baseline_comparison.md`
- [x] **階段3（第一版）：可控式翻譯 pipeline** — `scripts/safety_checks.py` 四層檢查（否定詞/數字一致性/醫療術語白名單/長度異常）已實作並套用在 Baseline 2 輸出上。結果見 `reports/stage3_safety_checks.md`：negation 1.0%、number_consistency 1.5%、medical_terms 9.5%（含假警報）、length_anomaly 1.5% 被攔下。medical_terms 白名單比對誤報率偏高，需要迭代；number_consistency 抓到真實的病房號唸法不一致問題
- [ ] **階段4（`speecht5_tailo-hokkien`接上taibun前端後轉為conditional fallback）：TTS 模型比較** — 調研結果見 `reports/stage4_tts_candidates.md`。**BreezyVoice-Taigi 查無公開權重，無法實測**（論文自報台語發音準確率只有59.2%，顯示台語TTS本身難度高，非資源問題）。**`speecht5_tailo-hokkien` 只吃Tâi-lô/英文，漢字直接輸入會失敗**（G2P問題，跟「華語→台語翻譯」不是同一件事：翻譯要處理語意/詞彙/語序，G2P輸入已經是正確台語漢字只需決定讀音）——查到公開套件 `taibun`（Hanji→Tâi-lô，MIT+CC-BY-SA-4.0）可以直接當frontend，接上後6句漢字測試全部技術性成功（靜音比例43-48%，跟其他正常案例同一範圍），狀態改為`Conditional fallback`。**注意：只證明技術可行，taibun轉出的Tâi-lô是否字音正確仍需母語者驗證，還沒做**。已建好可重複使用的統一跑分框架 `scripts/tts_benchmark/`（12句固定測試集×5指標+frontend_output欄位，新增候選只要寫一個adapter），目前已測3個adapter組合。`MERaLiON-OmniVoice-Hokkien-TTS` 已實測：吃漢字輸入(`language="nan"`)；voice cloning可以模仿neurlang現有聲音（開發者聽感「蠻像的」），這點確認可行。**中台混讀TTS這個方向測了三條路都卡住**：(1) macOS say+neurlang拼接，音色不一致 (2) MERaLiON統一引擎切換`language="zh"/"nan"`，音色一致但語言差異不明顯，沒有真的講出中文腔 (3) 原本觀察到的「難詞自動code-switch」例子（輪椅）後來確認是聽錯，已撤回。目前沒有可行做法，先擱置這個方向，維持現有的「pygoruut轉不出來就是轉不出來」，不強行補救。裝套件時再踩一次`omnivoice`(要transformers>=5)跟`coqui-tts`(要transformers<5)版本衝突，正式並用兩個TTS需要拆venv。**授權查過了：MIT+OpenAI Whisper-Large-V3 Community License，沒有非商業限制**，只要放致謝聲明即可，比Taigi-Llama的CC-BY-NC-SA-4.0寬鬆很多。開發者整體聽感評價「目前覺得mer的表現最好」。**已接進正式benchmark跑客觀指標，發現RTF=3.63（比即時慢3.6倍），比neurlang的0.103慢35倍**——CPU上不是即時的，互動式場景會有明顯延遲，這是目前MERaLiON最大的實際問題，音質可能較好但速度是硬傷，除非能上GPU。詳見 `reports/stage4_tts_candidates.md`
- [x] **階段4.5（新增）：錯誤分析（Error Analysis）** — 卡在TTS驗證跟自建語料中間，目的是讓階段6的模型選擇有真實錯誤分布依據，不要先選模型再找理由。用驗證平台已收集的69筆真實回覆分析，結果見 `reports/stage4.5_error_analysis.md` + `reports/errors.csv`（`scripts/build_error_analysis.py`可重跑）。**分布**：MEDICAL_TERM 18%、NEGATION 15%、STYLE 15%、CODE_SWITCH 13%、NUMBER 9%、PRONUNCIATION 7%、UNKNOWN 24%。**意外發現**：有備註的資料裡好幾筆講的是「發音錯」不是「翻譯錯」（例如「梯錯了」「燒錯了」），跟階段3的OOV audit（84%句子送氣/鼻化符號缺vocab）直接對得上——代表部分「需修改」判定其實是TTS發音問題，不是翻譯模型的問題，階段6決策不能把兩者混為一談。**方法論限制**：95%問題資料測試者沒填實際修改內容，大部分分類是弱訊號，樣本量(55筆)也還不夠，**現在不能用這份分布下結論**，下一步要先改驗證平台表單區分「翻譯錯/發音錯」，累積到200-300筆有效資料再重跑
- [ ] **階段5：自建領域資料** — 目標建立正式的 Medical Taigi Corpus v1（train/valid/test split，欄位含zh/nan_han/tailo/intent/speaker/verified/votes/domain/difficulty），1,000~3,000組醫療/服務情境句對，每個意圖多種問法，母語者校正。應同時收集「翻譯correction」和「發音correction」兩種標註（見階段4.5教訓）
- [x] **階段4.6（新增）：Safety-Critical Translation Failure Analysis** — 用10句**不在200句測試集裡**的新句子測Taigi-Llama泛化能力，結果見 `reports/safety_critical_translation_failures.md`。**40%(4/10)出現safety-critical等級失敗**：藥名「盤尼西林」被整個吃掉、病人名字「小明」被丟掉只剩姓、職稱被幻覺（呼吸治療師→氧氣治療師）、情境被誤譯（隔壁床呼叫鈴→鄰居吹哨子）。定義四層嚴重度：Level 0正確/Level 1可接受改寫/Level 2語意流失/Level 3安全等級。**Protected Token pipeline原型**（`scripts/protected_token_pipeline.py`）：用純大寫英文佔位符（如`DRUGA`）遮蓋關鍵詞再翻譯、譯完還原——盤尼西林案例成功救回，人名案例失敗，證實方法有效但用「文字替換+生成式LLM」不是100%可靠，救回率跟句子上下文有關。樣本只有4個案例，下一步要擴大測試量化真實救回率
- [ ] **階段6：決定是否訓練專用模型** — 由階段4.5/4.6的發現共同推動決策，不是先選模型。**P0是翻譯安全**：先確認人名/藥名/病房號/醫療器材/職稱這類關鍵資訊能不能穩定保留（擴大Protected Token測試、或評估constrained decoding／非生成式架構），這比P1(TTS，含語者embedding/G2P)更優先。若翻譯安全問題能用輕量的Protected Token解決 → 可能不需要換模型架構；若救回率太低 → 才需要考慮LoRA/mBART/constrained decoding這類更大的投入。三選一：(A) baseline+檢查層已夠用 (B) LoRA領域微調 (C) 堅持不用LLM則微調 mBART/NLLB/自建小型Transformer

---

## 目錄結構

```
taigi-mt-project/
├── PLAN.md              <- 本檔案
├── data/
│   ├── raw/              <- 原始下載資料，不修改
│   ├── processed/        <- 清理/標準化後資料
│   ├── licenses/         <- 每個資料來源的授權紀錄
│   └── human_review/     <- 每位測試者的驗證平台回覆（JSONL，一人一檔）
├── models/               <- 模型權重/checkpoint
├── scripts/              <- 處理/訓練/評估腳本
├── tests/                <- 200句測試集、baseline輸出、安全檢查結果、音檔
├── webapp/               <- Flask 驗證平台（給母語者測試者用）
└── reports/              <- 各階段結果報告
```

## 母語者驗證平台

**2026-08-01起改用靜態版，正式上線網址：https://heisenberg7299.github.io/taigi-mt-project/**
（本repo的 `docs/` 資料夾，GitHub Pages + Firebase Firestore，不依賴這台Mac開機/網路，
沿用`english-vocab-app`的同一個Firebase專案，資料存在獨立的`taigi_reviews`/`taigi_tokens`
collection，不會跟單字app的資料混）。開發者進度頁：
https://heisenberg7299.github.io/taigi-mt-project/progress.html （用email/password登入）。

一開始建了獨立的`taigi-verify` repo，後來決定併回本repo，不要多開一個——
所有靜態網站檔案都在 `docs/`，Firestore資料完全不受影響（資料存在雲端，跟哪個
git repo發布網站無關），不用重新遷移。

舊版 `webapp/app.py`（Flask，本機+cloudflared tunnel）累積的62筆真實回覆（5位測試者：
鐘/Angel/Yiching/正男/yuki）已用 `scripts/migrate_to_firestore.py` 全部遷移進新系統
（去重複後59筆不重複句子，同一句測過兩次取最新那筆）。Flask版本身還留著沒刪，
之後如果新版證實穩定，可以考慮把 `webapp/`、`scripts/tunnel_watchdog.sh` 這些檔案
標記淘汰。

舊版說明（保留供參考）：`cd webapp && source ../venv/bin/activate && python3 app.py`，
測試者輸入名字後，逐句看「中文原句 / Taigi-Llama候選台語翻譯 / 語音播放 / 安全檢查警示標籤」，
標記正確/需修改/錯誤，可直接編輯出正確版本，附流暢度與保真度評分。

## 安全檢查清單（醫療情境必測）

- [x] 否定詞是否遺失（「我沒有胸痛」不能變成「我有胸痛」）— `scripts/safety_checks.py::check_negation`
- [x] 數字/病房號/時間是否一致 — `check_number_consistency`（規則：病房號/電話逐位數唸，其他整數唸）
- [x] 陷阱字：走(跑)/行(走) — `check_trap_words`，目前只收錄這一組有把握的，套用在 Baseline 2 上 0/200 誤觸發（代表這個模型已經處理對了，這層是給未來其他模型的防護網）。其他待發現的語意反轉字，計畫靠驗證平台測試者的備註持續補充，不要自己亂猜
- [x] 中英台混合句是否崩潰 — 已納入200句測試集 code_mixing 類別，Baseline 2 抽樣看起來沒有崩潰
- [x] 主力TTS未知字元靜默丟棄（OOV audit）— `check_unconverted_characters` + `scripts/check_tts_oov.py`。實測發現pygoruut碰到生僻字（如「𧙕」）會靜默丟棄整個字、不報錯不警示（比整句失敗更危險，因為聽起來還是正常一句話）。**掃200句真實候選：0句有整字被丟棄（好消息），但168/200句（84%）有IPA音標符號本身缺vocab**（送氣ʰ、鼻化母音ãĩũẽõ）——不是漏字，是這些音素特徵被系統性簡化，可能唸不準，嚴重程度待母語者驗證確認
