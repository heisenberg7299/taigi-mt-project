# 中文 -> 台語 TTS Pipeline (骨架版)

華語文字輸入, 經 Protected Token 保護、整句翻譯、斷詞轉台羅、聲調正規化,
最後合成台語語音的完整流程骨架。

**目前狀態 (2026-08-03)**：**斷詞層仍是 mock**（示範詞庫，不是真的在做斷詞/
轉台羅）；**翻譯層跟TTS層都已經接上正式後端**——`TaigiLlamaTranslationBackend`
（透過本機Ollama）跟`NeurlangTTSBackend`（沿用`live_test/tts_backend.py`
同一套已驗證程式碼路徑），兩個都能實際跑出真的翻譯/真的語音。**但這不代表
輸出內容安全可信**：Taigi-Llama只當baseline，實測過10句非測試集句子有4句
出現safety-critical等級的語意流失（見
`reports/safety_critical_translation_failures.md`），所以翻譯完成後
額外加了Protected Token完整性檢查+台語語意安全檢查(見下方)當把關層，
預設只記錄警告不阻擋，要fail-closed需自己開config開關。斷詞層還是示範
詞庫，會限制實際能正確轉出台羅的詞彙量。

```
中文輸入
  -> Protected Token 遮罩 (保護藥名/人名/劑量)
  -> 台語整句翻譯 (translate.py)          [taigi_llama: 已驗證能實際翻譯, 只當baseline]
  -> Protected Token 完整性檢查            [檢查佔位符有沒有被LLM弄丟/複製]
  -> 台語語意安全檢查                      [scripts/safety_checks.py 既有四層+陷阱字]
  -> 台語斷詞 + 漢字轉台羅 (segment.py)    [目前: mock]
  -> 台羅正規化 + 連讀變調 (romanize.py，變調預設關閉)
  -> Protected Token 還原：台羅讀音 + 原文漢字兩種都保留
  -> TTS 合成 (tts.py)                    [neurlang: 已驗證真實出聲]
  -> WAV 語音輸出
```

TTS層會同時拿到「翻譯後台語漢字」跟「正規化台羅」兩種格式，由backend自己
選——neurlang訓練時吃的是漢字（內建phonemizer自動轉IPA），不能假設pipeline
最後產生的台羅字串一定能直接餵給任何TTS模型。**明確說明：`segment.py`跟
`romanize.py`產生的台羅字串(`TTSInput.tailo_text`)並沒有送進neurlang**，
`NeurlangTTSBackend`固定只用還原後的台語漢字(`TTSInput.hanji_text`)；
台羅字串只供其他吃台羅輸入的backend使用(目前是尚未驗證的`SpeechT5TailoBackend`
骨架)。

## 檔案結構

```
tw_hokkien_tts_pipeline/
  __init__.py          套件進入點
  config.py             PipelineConfig: 選擇 mock/taigi_llama/neurlang/real 後端、translation_strategy與安全開關
  protected_tokens.py    藥名/人名/劑量的遮罩與還原
  translate.py           TranslationBackend 介面 (Mock + Taigi-Llama已驗證 + HTTP骨架)
  adaptive_translation.py Adaptive Protected Token: 雙路翻譯(原文/遮罩)+安全檢查選擇
  segment.py              SegmentationBackend 介面 (Mock 斷詞/轉台羅)
  romanize.py             台羅正規化 + 簡化版連讀變調 (預設關閉)
  tts.py                  TTSBackend 介面 (Mock WAV + Neurlang已驗證 + SpeechT5骨架)
  audio_metrics.py         讀取wav檔量測時長/非靜音比例/NaN/全零等品質指標
  pipeline.py              串接以上各層的主流程, 含Protected Token完整性/安全檢查/adaptive策略
  cli.py                    命令列介面
  tests/
    test_pipeline.py                       pytest 測試 (7 項, 針對mock流程的回歸測試)
    test_protected_tokens_integrity.py     多個同類Protected Token的完整性測試 (5項)
    test_adaptive_translation.py           Adaptive Protected Token雙路策略測試, 假backend決定性 (4項)
    test_translate_taigi_llama_smoke.py    真實翻譯 smoke test (需要Ollama在跑, 否則自動skip)
    test_tts_neurlang_smoke.py             真實TTS smoke test (需要neurlang模型權重才會跑, 否則自動skip)
```

跟這個repo其他部分的關係：`live_test/`(neurlang+MERaLiON)是已驗證能實際
出聲的保底方案，這個資料夾是另一條探索中的架構——TTS層現在也能用同一個
已驗證的neurlang模型出聲，但翻譯/斷詞層還是mock，不是完整替代方案。

## 快速執行

（以下指令從repo根目錄 `taigi-mt-project/` 執行，不是這個資料夾內）

```bash
pip install -r tw_hokkien_tts_pipeline/requirements.txt
python3 -m pytest tw_hokkien_tts_pipeline/tests/ -v

# 全部mock(預設，快，示範詞庫+提示音，都不是真的)
python3 -m tw_hokkien_tts_pipeline.cli "請記得在晚餐後服用盤尼西林。" \
  --output-dir ./pipeline_output

# 翻譯用真實的Taigi-Llama(需要 ollama serve 且已pull過模型)
python3 -m tw_hokkien_tts_pipeline.cli "請記得在晚餐後服用盤尼西林。" \
  --translation-backend taigi_llama --output-dir ./pipeline_output

# 翻譯+TTS都用真的(斷詞仍是mock)
python3 -m tw_hokkien_tts_pipeline.cli "請記得在晚餐後服用盤尼西林。" \
  --translation-backend taigi_llama --tts-backend neurlang --output-dir ./pipeline_output
```

會在輸出資料夾產生 `output.wav` 與 `output.debug.json` (每個階段的中間結果,
方便定位問題出在翻譯、斷詞、拼音還是語音合成；`tts`欄位另外記錄backend名稱、
模型ID、實際送進模型的文字格式、推論時間、音檔時長、非靜音比例；
`protected_token_integrity`/`safety_checks`欄位記錄翻譯完成後的把關結果)。

## 翻譯完成後的把關層

真實LLM翻譯(生成式、非決定性)跟mock翻譯(決定性字典替換)不一樣，有可能把
Protected Token佔位符當一般文字改寫、複製、或整個漏掉——這是
`reports/safety_critical_translation_failures.md`記錄過的問題模式(藥名被
吃掉)的另一種可能形式。所以`pipeline.py`在翻譯完成、斷詞之前, 插入兩層
檢查:

1. **Protected Token完整性檢查**：用`Counter`比對每個佔位符在翻譯前後的
   出現次數，抓missing(翻譯完不見了)跟duplicated(被重複輸出)兩種問題。
2. **台語語意安全檢查**：直接重用`scripts/safety_checks.py`既有的四層+
   陷阱字檢查(否定詞/數字一致性/醫療術語白名單/長度異常/語意反轉陷阱字)，
   不重新發明一套，比對原文zh_text跟還原後的hanji_text。

兩者預設都**只記錄進debug trace的warnings，不阻擋合成**——這些檢查本身
有已知誤報率(見`reports/stage3_safety_checks.md`，medical_terms白名單
誤報率偏高)，預設關閉避免過度阻擋。要fail-closed(檢查沒過就直接
`raise ValueError`擋下合成)，用CLI的`--require-safety-checks`，或
`PipelineConfig(require_protected_token_integrity=True, require_safety_checks_pass=True)`。

## Adaptive Protected Token (2026-08-03)

實測10句泛化測試發現「一律遮罩」策略不是穩賺不賠：「普拿疼」這種模型本來
就認得的常見詞，遮罩成`DRUGA`後模型反而當成陌生詞去泛化翻譯，退步成籠統的
「藥仔」，比不遮罩還差；但「盤尼西林」這種生僻詞遮罩後才成功保留。所以
`adaptive_translation.py`改成雙路策略，不是所有專名一律遮罩：

1. 候選A(原文不遮罩)：如果每個protected entity的原文字面完整保留在輸出裡、
   且安全檢查通過 → 直接用這個(最好狀況只花一次LLM呼叫)。
2. 候選A失敗，但候選B(遮罩後翻譯)的佔位符完整、且安全檢查通過 → 還原後使用。
3. 兩者都失敗 → `UnsafeTranslationError`，**fail closed，不合成語音**，不是
   警告了事——因為這代表兩種策略都救不回這句話。

開啟方式：`PipelineConfig(translation_strategy="adaptive")`。

### 用真實Taigi-Llama重跑10句泛化測試集的結果

| 句子 | 舊策略(一律遮罩) | Adaptive策略 |
|---|---|---|
| 盤尼西林過敏 | Level 3，藥名消失 | 兩候選都失敗，**fail closed**(候選B技術上保留了藥名，但被否定詞檢查的已知誤報擋下，見下方) |
| 王小明先生 | Level 3，名字消失 | 兩候選都失敗，**fail closed**(即使改用完整姓名`王小明`遮罩，LLM仍把佔位符整個丟掉) |
| 呼吸治療師（幻覺成氧氣治療師） | Level 3，職稱被幻覺 | 兩候選都失敗，**fail closed**(這個詞不在任何保護詞庫裡，兩條路輸出相同，正確地被擋下——比舊策略「幻覺內容照樣播出去」安全) |
| 隔壁床陳太太 | Level 3，情境整個跑掉 | 選了候選A，**但内容其實還是錯的**(「隔壁床」變「厝邊兜」、「呼叫鈴」變「哨音」)，因為「陳太太」這個詞本身有保留、安全檢查也没抓到domain shift，所以被判定通過 |
| 胰島素冷藏 | Level 1，藥名被改述 | 候選A失敗、候選B成功，**選了遮罩版本，藥名正確保留** |
| 心律不整 | Level 2，語意流失 | 沒有配置保護詞庫，兩策略結果相同，問題未解決(預期內) |
| 普拿疼六顆 | Level 0(本來就對) | 候選A直接成功，**沒有像舊策略那樣退步** |
| 其餘3句(輪椅/營養師/麻醉科) | Level 0 | 不受影響，維持正確 |

**重要限制，不能過度解讀這次結果**：

- **人名保護依然不可靠**：改用完整姓名(`王小明`而非只有名字`小明`)遮罩，
  沒有解決LLM把佔位符整個丟掉的問題——不管遮不遮罩、遮罩格式如何調整，
  這句人名都保留不住。這代表問題不是遮罩格式，可能需要更根本的做法(結構化
  模板生成、或從病患資料庫直接取名字而不是靠文字比對，而不是繼續在
  「怎麼遮罩」上做文章)。
- **`protected_token_integrity`可靠，`safety_checks`不能涵蓋所有問題**：
  這次測試裡`protected_token_integrity`正確抓到每一次佔位符遺失，沒有漏判；
  但「陳太太」這個案例證明safety_checks**無法**偵測到「實體有保留、但周邊
  語境整個跑掉」(domain shift/角色關係消失)這類問題——這類問題目前完全
  沒有自動化檢查手段，是translation safety這塊還需要擴大測試才能回答的
  open question，不能因為這次protected_token_integrity表現好就誤以為整體
  翻譯安全已經有把握。
- **修正了否定詞清單的一個漏洞**：`scripts/safety_checks.py`原本的
  `NAN_NEGATION`清單漏收「莫」(標準台語否定詞，「莫食」=「不要吃」)，
  導致「普拿疼」案例一開始被誤判擋下——已補上。「盤尼西林」案例殘留的
  「敢會」(疑問句形式，語法上不一定需要顯式否定標記)則還沒修，是更細緻的
  文法規則問題，不是簡單加關鍵字能解決的。

## 候選C：StructuredMedicalRenderer + 50句四方法比較 (2026-08-03)

用50句新建的結構化標註資料集(5類x10句，分層切30句dev+20句locked，見
`tests/data/`)正式比較四種翻譯安全策略：No protection / Always mask /
Adaptive A-B / **Adaptive A-B+C**。候選C(`structured_renderer.py`的
`StructuredMedicalRenderer`)是A、B都失敗後，針對已支援的高風險intent
(`addressing_patient`/`request_staff`/`medication_reminder`)用人工審核
模板生成，不靠LLM生成，保證結構化欄位(人名/位置/職稱/藥名/劑量)100%正確。

人名保護也重新設計(`person_records.py`)：不再靠LLM保留佔位符，句首是
「已知病患姓名+稱謂,」這種呼格用法時，姓名整段完全不送進LLM，翻譯完
確定性接回句首——姓名保證100%正確，剩下的句子才交給翻譯backend。

**核心量化發現**（完整方法論、每個指標定義、dev/locked紀律見
`reports/translation_safety_4method_comparison.md`，不在這裡重複）：
Protected Token的「文字完整性」不能拿來當「整句語意安全」的替代指標——
locked set上90%的遮罩候選佔位符完整還原，但其中只有33.3%整句語意也真的
安全，即**66.7%的情況「token完整、句子仍不安全」**。也誠實記錄了一次
locked set的「不理想結果」（Adaptive A/B+C的unsafe pass rate在locked set
上比A/B還差）並依照pre-registration紀律沒有回頭修規則重跑——追查原因是
評分方法論(required/forbidden meanings的同義詞覆蓋)不夠完整，不是系統
邏輯錯誤，但這就是鎖定測試的意義：暴露dev set調整時看不到的問題。

新增`test_structured_fallback.py`(9項)涵蓋呼格判斷、候選C模板渲染、
A→B→C→fail closed完整順序，跟`scripts/eval_translation_safety.py`
(可重跑`dev`或`locked`模式的評估腳本)。

## 目前是 mock, 換成真實後端前要做的事

### 1. 翻譯層 (`translate.py`)
- `MockTranslationBackend` 只用一個十幾個詞的示範詞庫做替換, **不是真的翻譯**。
- **`TaigiLlamaTranslationBackend` 已驗證能實際翻譯**，透過本機Ollama呼叫
  Taigi-Llama-2-Translator-7B，跟`live_test/app.py`同一套已驗證prompt格式/
  stop token。**只當baseline，不代表結果安全可信**——實測過10句非測試集
  句子有4句出現safety-critical等級的語意流失(藥名被整個吃掉、病人姓名被
  丟掉只剩姓)，見`reports/safety_critical_translation_failures.md`。授權
  CC-BY-NC-SA-4.0(非商業限制)，只能研究/內部評估用。
- 若要換成其他真實API(Lohankha / 教育部翻譯器 / Taigi AI Labs等)前, 逐一確認:
  - 是否真的開放API (目前 Taigi AI Labs 官方表示沒有免費 API), 以及自動化
    呼叫是否符合服務條款
  - 輸入輸出格式 (台語漢字? 台羅? 白話字?)
  - 費用、流量限制
  - 醫療內容送到第三方服務的隱私政策疑慮
- 拿到 API 規格後, 繼承 `TranslationBackend` (可參考 `HTTPTranslationBackend` 骨架)
  實作對應類別, 並在 `config.py` 把 `translation_backend` 設為 `"real"`。

### 2. 斷詞層 (`segment.py`)
- `MockSegmentationBackend` 只有十幾個詞的示範詞庫, 查不到就整字輸出且信心分數為 0。
- 真實環境建議整合「臺灣言語工具」或教育部台語辭典資料建立正式詞庫, 並實作
  `SegmentationBackend`。
- 未來也可以在這層加入一字多音消歧邏輯 (依上下文選音)。

### 3. 台羅正規化 / 連讀變調 (`romanize.py`)
- `apply_tone_sandhi_numbered()` 是**簡化版**連讀變調循環表, 僅在數字調表示法
  (例如 `tai5`) 上運作, 尚未接上目前詞庫使用的附加符號調 (diacritic, 例如 `tâi`)。
- 正式使用前必須:
  1. 建立 diacritic <-> 數字調 雙向轉換表
  2. 由台語語言學背景的人確認變調規則 (泉腔/漳腔可能不同)
  3. 決定變調要在轉換前或轉換後套用, 並補齊單元測試涵蓋率

### 4. TTS 層 (`tts.py`)
- `MockTTSBackend` 只產生固定音高的提示音, 用來驗證檔案輸出流程, **不是真的語音**。
- **`NeurlangTTSBackend` 已驗證能實際出聲**, 沿用 `live_test/tts_backend.py`
  同一套已驗證程式碼路徑 (`TTS.utils.synthesizer.Synthesizer`)。用法：
  ```bash
  pip install coqui-tts[codec] "transformers<5"   # 跟MERaLiON要的>=5.3.0互斥
  ```
  輸入格式固定用**台語漢字**（`TTSInput.hanji_text`），不是台羅——模型內建
  pygoruut phonemizer 自己轉IPA。模型權重路徑預設是
  `models/neurlang-vits-suisiann/`（跟`live_test/`同一份），可用
  `PipelineConfig.neurlang_model_dir` 覆寫。模型權重不存在或套件版本不對時
  會直接丟出 `FileNotFoundError`/`ImportError`，**不會fallback成mock**。
- `SpeechT5TailoBackend` 是串接骨架, **尚未實際驗證過**, 需要:
  ```bash
  pip install transformers torch soundfile sentencepiece
  ```
  並且務必先看清楚目標模型 (例如 `Curiousfox/speecht5_tailo-hokkien_ver1.0.b`)
  的 model card, 確認輸入格式與 speaker embedding 需求, 骨架中的隨機 speaker
  embedding 只是佔位, 正式使用前要換成合適的值。這個backend用台羅
  (`TTSInput.tailo_text`)。

### 漢羅混合輸入實驗 (2026-08-03)

**動機**：neurlang固定吃漢字, Protected Token的人工校正台羅讀音
(`drug_lexicon`的值) 目前沒辦法真的影響neurlang的發音——想確認能不能
把藥名部分直接嵌入台羅拼音、其餘維持漢字 (「漢羅混合」), 讓藥名發音
真的照人工校正過的版本念, 而不是靠neurlang自己的phonemizer重新猜。

**實測方法**：直接呼叫 `Synthesizer.tts()`, 分別測試 (a) 純漢字整句
(對照組, 已知正常) (b) 純台羅單詞 (c) 漢字整句裡嵌入台羅拼音的藥名片段。

**結果**：
- 純台羅輸入 (例如 `puân-nî-se-lîm`) 會讓 `syn.tts()` **卡死**, 手動測試
  超過120秒沒有回應, 只能強制中止進程, 不是單純變慢。
- 漢羅混合 (例如「請愛記得佇暗頓後食puân-nî-se-lîm。」) 沒有直接crash,
  但phonemizer的debug trace出現了不該存在的雜訊字元 (數字 `1` 混進IPA
  音素序列裡, 正常IPA輸出不會有阿拉伯數字), 且輸出音檔明顯比對照組短
  (59152 samples vs 對照組81936 samples, 同樣句子長度), 研判台羅片段
  的部分沒有被正確音素化, 而不是「支援但比較慢」。

**結論**：**neurlang不安全支援台羅或漢羅混合輸入, 沒有採用這個方向。**
`NeurlangTTSBackend` 維持只用純漢字輸入 (`TTSInput.hanji_text`), 不強行
修改模型輸入格式。這代表 Protected Token 在neurlang這個backend身上
**只能保證藥名文字被正確保留**, 不能保證發音等於人工校正過的台羅讀音——
見下面「醫療安全設計」章節的 `protected_pronunciation_enforced` 說明。
若要讓TTS真的照人工校正過的台羅讀音念藥名, 需要換一個吃台羅輸入的模型
(例如骨架化但尚未驗證的 `SpeechT5TailoBackend`), 或是等有支援漢羅混合的
neurlang版本/替代模型出現。

## 醫療安全設計

- **Protected Token**: 藥名/人名/劑量在送進翻譯層前先遮罩成純大寫英文格式
  的佔位符 (例如 `DRUGA`, `PERSONB`, `DOSEC`, 見 `protected_tokens.py`
  docstring說明格式選擇的理由), 避免翻譯模型誤譯、漏譯或竄改; 翻譯完成後
  才用人工校正過的發音詞庫換回台羅讀音 (或原文漢字, 供不同TTS backend使用)。
  同一類別若有多個實體 (例如兩個藥名), 依序用不同字母 (`DRUGA`/`DRUGB`/...)
  區分, 不會互相覆蓋; 也處理了「藥名+劑量緊接沒有分隔字元」時兩個佔位符
  黏在一起 (例如`DRUGADOSEA`) 仍能正確切分還原的情況 (見
  `tests/test_protected_tokens_integrity.py`)。
- **`protected_text_preserved` / `protected_pronunciation_enforced`**
  (`pipeline.py` debug trace欄位)：前者表示每個protected span的原文
  是否都完整出現在最終送進TTS的文字裡 (文字沒有遺失/改序/類型互換)；
  後者表示TTS**發音**是否真的用了人工校正過的台羅讀音, 不是backend自己
  重新推導的。**`NeurlangTTSBackend` 因為只吃漢字、發音靠自己內建
  phonemizer決定, 這個欄位固定是 `False`**——文字保留成功不等於發音
  受保護, 兩者是分開的保證, 不能混為一談。只有真的消費台羅文字的backend
  (`consumes_verified_pronunciation=True`, 且該藥名有查到詞庫讀音)
  才會是 `True`。
- **Fail-closed 選項**: `PipelineConfig.require_full_protected_coverage=True`
  時, 只要有任何藥名沒有經人工校正的台羅讀音, `pipeline.run()` 會直接
  `raise ValueError` 擋下合成, 而不是讓 TTS 用猜測的發音念出藥名。
- `drug_lexicon` 的值務必由台語專業人士確認過再放進去, 這個 repo 本身**不**
  內建任何未經審核的醫療發音資料, 範例詞庫僅供串接測試。

## 已知限制

- **斷詞層仍是mock**：詞庫只有十幾個示範詞, 真實句子大部分字詞會fallback
  成原字/查無台羅讀音，`unresolved_count`/`mean_confidence`會反映出來。
- **翻譯層(`TaigiLlamaTranslationBackend`)已經是真的在翻譯，但只當baseline，
  不代表結果安全可信**：實測過10句非測試集句子有4句出現safety-critical
  等級的語意流失。pipeline.py新增的Protected Token完整性檢查+台語語意
  安全檢查是把關層，能抓到「這次翻譯可能有問題」，但**不會自動修正**，
  預設也不會阻擋合成(見上方「翻譯完成後的把關層」)。
- 連讀變調預設關閉 (`apply_tone_sandhi=False`)，且就算開啟也只在數字調格式
  上運作，詞庫本身的 diacritic 讀音是no-op。
- `MockTTSBackend` 輸出只是提示音, 不是真人語音。
- `HTTPTranslationBackend` / `SpeechT5TailoBackend` 是可運作的骨架, 但沒有
  對應任何一個已驗證存在的正式 API/模型端點, 使用前一定要照上面的步驟自行
  串接與驗證。
- `NeurlangTTSBackend` 已驗證能實際出聲，但沿用的是neurlang本身既有的限制
  （見 `reports/tts_oov_audit.md`）：送氣/鼻化符號(ʰ/ã/ĩ等)會被內建
  phonemizer丟棄，這是模型詞彙表本身的問題，不是這次串接造成的。
- **`NeurlangTTSBackend` 的Protected Token只保護文字，不保護發音**：
  `protected_pronunciation_enforced` 固定是 `False`，藥名等關鍵詞的漢字
  雖然保證會出現在送進模型的文字裡，但實際念法是neurlang自己的phonemizer
  決定的，不是`drug_lexicon`裡人工校正過的台羅讀音——已實測過漢羅混合
  輸入不安全（見上方「漢羅混合輸入實驗」），沒有辦法在不影響穩定性的前提下
  繞過這個限制。
