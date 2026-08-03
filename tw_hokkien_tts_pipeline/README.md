# 中文 -> 台語 TTS Pipeline (骨架版)

華語文字輸入, 經 Protected Token 保護、整句翻譯、斷詞轉台羅、聲調正規化,
最後合成台語語音的完整流程骨架。

**目前狀態 (2026-08-03)**：翻譯層、斷詞層仍是 mock（示範詞庫，不是真的在
做這兩件事）；**TTS 層新增了 `NeurlangTTSBackend`，是已驗證能實際出聲的
正式後端**（沿用 `live_test/tts_backend.py` 同一套已驗證程式碼路徑）。
也就是說，這次只證實了「pipeline架構 + Protected Token安全機制 + 真實TTS
串接」可以動，**不能宣稱完整的中文→台語翻譯已經可靠**——翻譯/斷詞層換成
真的東西前，最終輸出的台語內容品質仍等同於示範詞庫的程度。

```
中文輸入
  -> Protected Token 遮罩 (保護藥名/人名/劑量)
  -> 台語整句翻譯 (translate.py)                    [目前: mock]
  -> 台語斷詞 + 漢字轉台羅 (segment.py)              [目前: mock]
  -> 台羅正規化 + 連讀變調 (romanize.py，變調預設關閉)
  -> Protected Token 還原：台羅讀音 + 原文漢字兩種都保留
  -> TTS 合成 (tts.py)                              [neurlang: 已驗證真實出聲]
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
  config.py             PipelineConfig: 選擇 mock/neurlang/real 後端與輸出設定
  protected_tokens.py    藥名/人名/劑量的遮罩與還原
  translate.py           TranslationBackend 介面 (Mock + HTTP 骨架)
  segment.py              SegmentationBackend 介面 (Mock 斷詞/轉台羅)
  romanize.py             台羅正規化 + 簡化版連讀變調 (預設關閉)
  tts.py                  TTSBackend 介面 (Mock WAV + Neurlang已驗證 + SpeechT5骨架)
  audio_metrics.py         讀取wav檔量測時長/非靜音比例/NaN/全零等品質指標
  pipeline.py              串接以上各層的主流程
  cli.py                    命令列介面
  tests/
    test_pipeline.py            pytest 測試 (7 項, 針對mock流程的回歸測試)
    test_tts_neurlang_smoke.py  真實TTS smoke test (需要neurlang模型權重才會跑, 否則自動skip)
```

跟這個repo其他部分的關係：`live_test/`(neurlang+MERaLiON)是已驗證能實際
出聲的保底方案，這個資料夾是另一條探索中的架構——TTS層現在也能用同一個
已驗證的neurlang模型出聲，但翻譯/斷詞層還是mock，不是完整替代方案。

## 快速執行

（以下指令從repo根目錄 `taigi-mt-project/` 執行，不是這個資料夾內）

```bash
pip install -r tw_hokkien_tts_pipeline/requirements.txt
python3 -m pytest tw_hokkien_tts_pipeline/tests/ -v

# 全部mock(預設，快，提示音不是真的語音)
python3 -m tw_hokkien_tts_pipeline.cli "請記得在晚餐後服用盤尼西林。" \
  --output-dir ./pipeline_output

# TTS層用真實的neurlang(需要 transformers<5 + models/neurlang-vits-suisiann/ 權重)
python3 -m tw_hokkien_tts_pipeline.cli "請記得在晚餐後服用盤尼西林。" \
  --tts-backend neurlang --output-dir ./pipeline_output
```

會在輸出資料夾產生 `output.wav` 與 `output.debug.json` (每個階段的中間結果,
方便定位問題出在翻譯、斷詞、拼音還是語音合成；`tts`欄位另外記錄backend名稱、
模型ID、實際送進模型的文字格式、推論時間、音檔時長、非靜音比例)。

## 目前是 mock, 換成真實後端前要做的事

### 1. 翻譯層 (`translate.py`)
- `MockTranslationBackend` 只用一個十幾個詞的示範詞庫做替換, **不是真的翻譯**。
- 換成真實 API 前, 逐一確認:
  - Lohankha / 教育部翻譯器 / Taigi AI Labs 是否真的開放 API (目前 Taigi AI Labs
    官方表示沒有免費 API), 以及自動化呼叫是否符合服務條款
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

- **翻譯/斷詞層仍是mock**：詞庫只有十幾個示範詞, 真實句子大部分字詞會
  fallback 成原字。這代表就算TTS層用neurlang真的出聲了, 講出來的內容品質
  仍等同示範詞庫程度, **不是真正可用的中文→台語翻譯**。
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
