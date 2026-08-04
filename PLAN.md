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
- [ ] **階段6候補架構（新增，2026-08-03）：`tw_hokkien_tts_pipeline/` 骨架** — 跟目前`live_test/`用的「單一LLM直出Hanji→neurlang/MERaLiON直接吃Hanji」不同，改成明確分層：遮罩→翻譯→斷詞轉台羅→正規化/連讀變調→還原→TTS，把Protected Token做成pipeline第一層而非事後補救，並加了`require_full_protected_coverage`這個「查無人工校正讀音就直接擋下不合成」的fail-closed安全開關，直接對應階段4.6發現的40%安全性失誤問題。**TTS層已接上真實的neurlang**（`NeurlangTTSBackend`，沿用`live_test/tts_backend.py`同一套已驗證程式碼路徑，固定用台語漢字輸入——pipeline同時保留翻譯後漢字跟正規化台羅兩種格式，由backend自己選，不假設台羅字串一定能餵給任何TTS模型；連讀變調預設關閉，避免輸入偏離neurlang訓練資料的樣子）；實測`output_neurlang.wav`非靜音比例68.56%、推論0.449秒、時長3.867秒，確認不是mock beep。**翻譯/斷詞層仍是mock**，所以這次只驗證了「pipeline架構+安全機制+真實TTS串接」可行，還不能宣稱完整中文→台語翻譯已經可靠。原本7個mock回歸測試全過（沒被破壞）+ 新增2個真實TTS smoke test（模型權重不存在時自動skip，不會擋下其他測試）。換成真的翻譯/斷詞backend前要做的事列在`tw_hokkien_tts_pipeline/README.md`。**`live_test/`(neurlang+MERaLiON)維持現有、已驗證能實際出聲的版本，當作保底**，這個骨架是探索中的新方向。**後續修正（同日）**：(1) Protected Token佔位符格式從`__DRUG_0__`改成`scripts/protected_token_pipeline.py`實測過較穩定的純大寫字母格式(`DRUGA`/`PERSONB`/`DOSEC`)，同類多實體用字母遞增(A,B,...Z,AA,...)不折返覆用，還原邏輯改成單一combined regex pass一次處理所有佔位符——開發過程中實際測到「藥名+劑量緊接無分隔字元」(例如「盤尼西林120毫克」)會讓佔位符黏成`DRUGADOSEA`，原本逐一replace的寫法會出錯，已修正並補了`tests/test_protected_tokens_integrity.py`5項測試涵蓋這個case。(2) debug trace新增`protected_text_preserved`(文字有沒有完整保留)/`protected_pronunciation_enforced`(發音是否真的用了人工校正台羅)兩個欄位——**neurlang因為只吃漢字、發音靠自己內建phonemizer決定，`protected_pronunciation_enforced`固定是False**，文字保留成功不代表發音受保護。(3) 實測過「漢羅混合輸入」(藥名部分直接嵌入台羅拼音)：純台羅句子會讓`syn.tts()`卡死(手動測試超過120秒無回應，強制中止)，漢羅混合雖不crash但phonemizer trace出現雜訊字元、音檔明顯偏短，判定不安全，**結論是neurlang不支援台羅/漢羅混合輸入，維持純漢字模式**，詳見`tw_hokkien_tts_pipeline/README.md`「漢羅混合輸入實驗」章節。全部14項測試（7 mock回歸+5 protected token完整性+2真實TTS smoke）實測通過，用兩個藥名+劑量緊鄰的句子重新產生`output_neurlang.wav`確認正確。**再後續（同日，翻譯層接上真實Taigi-Llama）**：新增`TaigiLlamaTranslationBackend`(透過本機Ollama，跟`live_test/app.py`同一套已驗證prompt格式)，並在`pipeline.py`翻譯完成後新增兩層把關——(a) Protected Token完整性檢查：用Counter比對翻譯前後每個佔位符出現次數，抓真實LLM(生成式、非決定性)有沒有把佔位符弄丟或複製，這是mock翻譯(決定性字典替換)不會出現、真實LLM才需要防的問題模式；(b) 台語語意安全檢查：直接重用`scripts/safety_checks.py`既有的四層+陷阱字檢查，不重新發明一套，比對原文zh跟還原後的hanji_text。兩者預設都只記錄進debug trace的warnings，不阻擋合成（這些檢查已知有誤報率），要fail-closed需自己開`require_protected_token_integrity`/`require_safety_checks_pass`。開發過程中順便抓到一個bug：`protected_text_preserved`欄位原本不分TTS用漢字還是台羅格式，一律拿「原文中文字」去找，結果backend用台羅格式時（例如MockTTSBackend）中文字當然永遠找不到台羅字串裡，已修正成依格式分別檢查，並補了回歸測試鎖住這個case。跑過真實翻譯(Taigi-Llama)+真實TTS(neurlang)完整串接（斷詞仍是mock），全部15項測試通過，實際產出`output_full_real_translate_tts.wav`：翻譯出「請你愛會記得佇暗頓食了後食盤尼西林。」，Protected Token完整性/安全檢查/文字保留全部通過，語音inference 0.689秒、時長4.61秒、非靜音比例75.84%。**再再後續（同日，Adaptive Protected Token）**：重跑10句泛化測試發現「一律遮罩」策略不是穩賺不賠——「普拿疼」這種模型本來就認得的常見詞，遮罩成`DRUGA`後模型當成陌生詞去泛化翻譯，退步成籠統的「藥仔」，比不遮罩還差；但「盤尼西林」這種生僻詞遮罩後才成功保留。改成新增`adaptive_translation.py`：雙路翻譯(候選A原文不遮罩/候選B遮罩後翻譯)+安全檢查選擇，不是所有專名一律遮罩，兩者都失敗時`raise UnsafeTranslationError`直接fail closed不合成，不是警告了事。用真實Taigi-Llama重跑10句結果：**普拿疼不再退步**（候選A直接成功）、**胰島素成功修復**（候選A失敗、候選B成功保留藥名）、**盤尼西林/王小明先生/呼吸治療師三句被fail closed擋下**（其中呼吸治療師是正確行為——這句不管遮不遮罩都會幻覺成「氧氣治療師」，兩條路一致失敗，adaptive策略正確擋下，比舊策略「幻覺內容照樣播出去」安全；盤尼西林被擋是因為`scripts/safety_checks.py`的否定詞清單漏收「莫」這個標準台語否定詞，已修正——但「敢會」疑問句形式的殘留誤判還沒修，是更細緻的文法規則問題）。**人名保護依然不可靠**：即使改用完整姓名(`王小明`而非只有名字`小明`)遮罩，LLM仍把佔位符整個丟掉，代表問題不是遮罩格式，需要更根本的做法(結構化模板生成、或直接從病患資料庫取名字而非文字比對)，尚未實作。**重要發現**：`protected_token_integrity`這次3次失敗全部正確偵測到，沒有漏判；但「陳太太」案例證明`safety_checks`**無法**偵測「實體有保留但周邊語境整個跑掉」(隔壁床→厝邊兜、呼叫鈴→哨音的domain shift)這類問題——這代表token完整性檢查可信，但translation safety的涵蓋範圍還遠遠不夠，不能因為這次結果好就誤以為整體翻譯安全已經有把握。新增`test_adaptive_translation.py`4項測試(假backend、決定性)，全部19項測試(7 mock回歸+5 protected token完整性+4 adaptive+1真實翻譯smoke+2真實TTS smoke)通過。下一步：擴大到30-50句涵蓋常見藥名/生僻藥名/完整姓名/姓名+稱謂/多人同句/藥名+姓名+劑量，比較no-protection/always-mask/adaptive三種方法；人名改用結構化模板或資料庫查詢。**再再再後續（同日，50句四方法比較+dev/locked紀律）**：新建50句結構化標註資料集(5類x10句：藥名劑量時間/完整姓名稱謂多人/職稱床位關係/否定過敏禁止緊急/一般控制組)，每句標`critical_entities`/`person_roles`/`location_bed_relation`/`medication_dose_time`/`negation`/`required_meanings`/`forbidden_meanings`/`expected_severity_if_failed`，依類別分層切30句dev+20句locked（見`tw_hokkien_tts_pipeline/tests/data/`）。新增`person_records.py`(`PersonRecord`結構化full_name/title，呼格偵測`is_vocative_address`——句首「姓名+稱謂,」時姓名完全不經過LLM，翻譯完確定性接回句首，保證100%正確)跟`structured_renderer.py`(候選C `StructuredMedicalRenderer`，人工審核模板涵蓋`addressing_patient`/`request_staff`/`medication_reminder`三種intent，13/50句有定義)。`adaptive_translation.py`新增`translate_with_structured_fallback()`：A→B→C→fail closed完整順序。新增`scripts/eval_translation_safety.py`跑四方法比較(No protection/Always mask/Adaptive A-B/Adaptive A-B+C)，8項指標(Unsafe Pass/Safe Completion/Abstention/False Block Rate、Critical Entity/Context Preservation、Level0-3分布)。**Dev set調整**：抓到2個資料標註bug(structured_intent的time欄位誤把"/"同義詞分隔記法當成模板實際值、required_meanings漏列Hokkien同義詞)，修正後Adaptive A/B+C在dev set上unsafe pass rate跟A/B打平(0.4)但safe completion更高(0.4 vs 0.333)。**Locked set(只跑一次，結果不回頭修改)**：Adaptive A/B+C的unsafe pass rate(0.55)反而比A/B(0.45)差，追查是候選C在locked set遇到dev set沒覆蓋到的Hokkien同義詞/複合詞組合導致評分方法誤判(不是系統邏輯錯誤)，**依紀律誠實記錄、沒有回頭修規則重跑**。**核心量化發現**：token完整性(`entities_ok=True`)跟整體語意安全是兩回事——locked set上90%的遮罩候選token完整，但其中只有33.3%整句語意也安全，即66.7%的情況「token完整、句子仍不安全」，比10句測試時的觀察(陳太太案例)更大樣本量化確認。兩種adaptive方法都讓Level 3(安全關鍵)數量明顯下降(dev: 11→5，locked: 4→2)，代價是20-30%的abstention。完整報告見`reports/translation_safety_4method_comparison.md`。新增`test_structured_fallback.py`9項測試，全部28項測試(19+9)通過。**再X4後續（同日，evaluator v2：改評分方法論，不動翻譯策略）**：`reports/translation_safety_eval/v1_study/`凍結第一輪(evaluator v1)完整原始結果不可再覆寫，舊locked_20已查看過，後續只能是post-hoc analysis。新增`concept_taxonomy.py`(9種concept、72條entry、153同義詞，來源標記dev_output/moe_dict/manual，刻意不含任何locked set學到的詞)+`scripts/evaluator_v2.py`(Unicode正規化+漢羅格式正規化+concept-aware比對+forbidden排除複合詞子字串+否定範圍用「敢/甘」問句標記判uncertain而非硬判)。v2解決3個v1已知誤判案例(跌倒/跋倒同義詞、藥膏複合詞誤判、盤尼西林否定範圍)，但**誠實記錄兩個新發現、沒有偷偷修掉重算**：(1) taxonomy把「治療師」「復健科醫師」錯誤列成同義詞，讓v2在role_location_009誤判成safe(v1反而抓對)；(2) drug_003胰島素「冷凍vs冷藏」案例證明required/forbidden schema本身有臨床邏輯盲點，跟評分演算法無關。建立74項人工gold label(safe 47/unsafe 24/uncertain 3)，**單一評估者，無法算Cohen's kappa**，明確寫入限制。v1 vs v2對gold的表現：v2的precision(0.556 vs 0.491)/F1(0.694 vs 0.650)/false-block(0.426 vs 0.574)都更好，但**false-safe rate v2反而更高**(0.074 vs 0.037，2/74 vs 1/74，信賴區間重疊但方向如此)——示範「不能只看F1」的具體案例。用gold label重新看4方法的risk-coverage：Adaptive A/B+C在真正的人工判斷下**沒有任何一項比A/B差**(unsafe pass同樣是6/50，但safe completion更高、abstention更低)，證實先前locked set用v1自動評分器算出的「A/B+C變差」主要是評分方法論的同義詞覆蓋不足造成的假象。建立全新locked v2測試集(20句，5類x4句)，**先算SHA256存檔再執行**，執行後雜湊值核對一致，v2的同義詞感知比對在這組真正沒看過的新句子上依然降低誤判率(no_protection unsafe 14→13、always_mask 15→12)，但**沒有配套人工gold label**，證據力弱於v1_study。完整方法論、發現、限制見`reports/translation_safety_evaluator_v2.md`。全部28項既有測試維持通過(這輪只新增評分工具，沒改翻譯策略程式碼)
- [ ] **Response Controller架構（新增，2026-08-03/04）：`assistant_service/`** — 不讓「大腦」(意圖+RAG+LLM)直接把自由文字丟給TTS，中間加一層：`BrainResponse` JSON(`request_id`/`intent`/`risk_level`/`response_zh`/`slots`/`action`/`evidence_ids`/`priority`) → `ResponseController`(風險判斷+安全閘門) → `tw_hokkien_tts_pipeline`安全翻譯 → `TTSRouter`(neurlang即時/MERaLiON快取) → 播放。路由規則：`risk_level=high`**只**用`StructuredMedicalRenderer`(候選C)，intent沒有對應模板時直接abstain，不退回候選A/B(不讓LLM決定高風險內容最終文字)；`medium`/`low`用`translate_with_structured_fallback()`(候選A/B/C)。翻譯前先比對`response_zh`跟`slots`是否矛盾，矛盾就在送翻譯之前直接abstain。三個候選都失敗時播放固定回覆「這个問題我無法度確定，我共你通知護理師。」(demo版本，**尚未經母語者審核**)+`status=abstained`/`action=call_nurse`，不沉默也不亂講。**第一個里程碑(手動JSON→Controller→安全翻譯→Neurlang→真實WAV)已端到端實測**：範例JSON(high risk medication_reminder)正確走candidate C產生真實wav；low risk一般對話正確用candidate A；high risk但無對應模板正確abstain且**不呼叫TTS**；slots與response_zh矛盾正確在翻譯前就abstain。包成FastAPI `POST /v1/speech`，用curl實測跟pytest結果一致。新增`speech_request_queue.py`(播放優先權佇列：緊急100>護理通知80>一般服務50>陪伴聊天10，高優先權可中止低優先權播放)，這部分不依賴ROS已用pytest驗證。`ros_bridge.py`(brain_tts_bridge.py)照ROS2慣例撰寫，**這台開發機沒有rclpy，完全沒有實機測試過**，`BrainTTSBridge.__init__`偵測不到rclpy時主動raise而非靜默失敗。新增14項測試(8 response_controller+6 speech_request_queue)，加上既有28項全部42項測試通過。**還沒做**：真正的Ollama大腦+RAG(目前手動JSON)、ROS bridge實機驗證、`approved_sentences.json`是空的(MERaLiON快取路徑目前不會被觸發)、fallback句子本身沒有母語者審核。完整說明見`assistant_service/README.md`。**Code review後修正（2026-08-04）**：有人只看文字描述review出4個真實漏洞，逐一核對程式碼後確認屬實並修正：(1) `risk_level`原本完全信任輸入JSON、沒有規則式檢查，新增`enforce_deterministic_risk_level()`只能往上拉不能往下降，`slots`含drug/dose/negation或intent含醫療關鍵字強制high；(2) 原本只在翻譯前比對`response_zh`跟`slots`，新增翻譯後對`hanji_text`再比對一次，抓翻譯過程本身引入的錯誤；(3) schema驗證失敗(`status=rejected`)原本不會觸發任何反應，新增`_fail_safe()`讓格式問題也一樣播固定回覆+通知護理師，同時發現並修正`BrainResponse.from_dict()`用必要欄位直接索引、缺欄位時會直接crash的問題(改用`.get()`)；(4) `POST /v1/speech`原本零驗證，新增`X-API-Key` header驗證(`ASSISTANT_SERVICE_API_KEY`環境變數)，未設定時印出明顯警告。新增8項測試，全部46項測試通過。**這次review還沒動、需要更大投入或不同專業的部分**：Structured C模板內容沒有藥師/護理師審核過(工程手段補不了)、`/nurse_alert`通知沒有重試/送達確認機制、多病患情境下`slots.person`只是自由文字沒有跟真正病患ID比對、ROS bridge仍未實機測試。詳見`assistant_service/README.md`。**接上yuava22/Interactive-service-robots，第一個真實輸入來源（2026-08-04）**：使用者要求把外部repo[yuava22/Interactive-service-robots](https://github.com/yuava22/Interactive-service-robots)(規則式病床語音助理，非LLM：Whisper ASR+關鍵字比對意圖判斷`intent_rules.decide_event_and_reply()`，3種意圖：喝水/上廁所/求助，原本用gTTS輸出中英雙語)跟台語語音+大腦結合。新增`voice_io_bridge.py`：`event_decision_to_brain_response()`把對方的`EventDecision(event, reply_zh, reply_en)`轉成`BrainResponse`，取代gTTS改用既有的`tw_hokkien_tts_pipeline`+neurlang輸出台語。刻意用duck typing+delay-import設計，不要求`assistant_service`一定要裝對方的openai-whisper/YOLO等重依賴；`event_decision_to_brain_response()`本身零相依可獨立測試，`run_from_wav()`才需要真的裝對方套件。`risk_level`固定為`"low"`(對方3種規則完全不涉及藥物/醫囑，這個假設寫死在檔案裡並註明要是對方新增醫療相關規則必須跟著改)；`priority`則依事件類型分級(`HELP_REQUEST`用`PRIORITY_NURSE_ALERT`=80可插播，其餘`PRIORITY_GENERAL_SERVICE`=50)，明確區分「風險等級(翻譯策略)」跟「優先權(播放順序)」是兩個獨立維度。實測：`WATER_REQUEST`案例真的端到端跑過完整Controller+真實Ollama翻譯+真實neurlang TTS，產生真實wav檔(`translation_method="raw"`)，非mock。新增5項測試(`test_voice_io_bridge.py`)，全部51項測試(46+5)通過。**還沒做**：沒有真的裝`voice_io_event_detector`套件跑`run_from_wav()`(只驗證過手動建構`EventDecision`的轉換邏輯+後續管線)，對方的`camera`手勢/物件偵測子命令完全沒有整合，意圖種類仍只有對方原本的3種。詳見`assistant_service/README.md`「voice_io_bridge.py」章節。

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
├── webapp/               <- Flask 驗證平台（給母語者測試者用，已停用保留參考）
├── live_test/            <- 開發者即時測試網頁（neurlang+MERaLiON，已驗證能實際出聲，目前保底方案）
├── tw_hokkien_tts_pipeline/  <- 階段6候補架構骨架（分層pipeline，目前mock，見內部README）
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
