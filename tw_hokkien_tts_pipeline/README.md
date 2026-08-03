# 中文 -> 台語 TTS Pipeline (骨架版)

華語文字輸入, 經 Protected Token 保護、整句翻譯、斷詞轉台羅、聲調正規化,
最後合成台語語音的完整流程骨架。目前所有外部依賴 (翻譯 API、斷詞工具、
TTS 模型) 都提供 **mock 版本**, 可以離線直接跑通整條 pipeline 並通過測試;
真實後端需依下方說明自行串接。

```
中文輸入
  -> Protected Token 遮罩 (保護藥名/人名/劑量)
  -> 台語整句翻譯 (translate.py)
  -> 台語斷詞 + 漢字轉台羅 (segment.py)
  -> 台羅正規化 + 連讀變調 (romanize.py)
  -> Protected Token 還原為台羅讀音
  -> TTS 合成 (tts.py)
  -> WAV 語音輸出
```

## 檔案結構

```
tw_hokkien_tts_pipeline/
  __init__.py          套件進入點
  config.py             PipelineConfig: 選擇 mock/real 後端與輸出設定
  protected_tokens.py    藥名/人名/劑量的遮罩與還原
  translate.py           TranslationBackend 介面 (Mock + HTTP 骨架)
  segment.py              SegmentationBackend 介面 (Mock 斷詞/轉台羅)
  romanize.py             台羅正規化 + 簡化版連讀變調
  tts.py                  TTSBackend 介面 (Mock WAV + SpeechT5 骨架)
  pipeline.py              串接以上各層的主流程
  cli.py                    命令列介面
  tests/
    test_pipeline.py       pytest 測試 (7 項, 全部針對 mock 流程)
```

跟這個repo其他部分的關係：`live_test/`(neurlang+MERaLiON)是已驗證能實際
出聲的保底方案，這個資料夾是另一條探索中的架構，目前所有backend都是mock，
還沒接上任何真實模型。

## 快速執行

（以下指令從repo根目錄 `taigi-mt-project/` 執行，不是這個資料夾內）

```bash
pip install -r tw_hokkien_tts_pipeline/requirements.txt
python3 -m pytest tw_hokkien_tts_pipeline/tests/ -v

python3 -m tw_hokkien_tts_pipeline.cli "請記得在晚餐後服用盤尼西林。" \
  --output-dir ./pipeline_output
```

會在輸出資料夾產生 `output.wav` 與 `output.debug.json` (每個階段的中間結果,
方便定位問題出在翻譯、斷詞、拼音還是語音合成)。

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
- `SpeechT5TailoBackend` 是串接骨架, 需要:
  ```bash
  pip install transformers torch soundfile sentencepiece
  ```
  並且務必先看清楚目標模型 (例如 `Curiousfox/speecht5_tailo-hokkien_ver1.0.b`)
  的 model card, 確認輸入格式與 speaker embedding 需求, 骨架中的隨機 speaker
  embedding 只是佔位, 正式使用前要換成合適的值。
- 其他可考慮的替代方案: 改接受台羅/IPA 輸入的 Coqui VITS、Neurlang 台語 VITS,
  或其他有正式 API 的台語 TTS 服務。

## 醫療安全設計

- **Protected Token**: 藥名/人名/劑量在送進翻譯層前先遮罩成 `__DRUG_0__` 等
  佔位符, 避免翻譯模型誤譯、漏譯或竄改; 翻譯完成後才用人工校正過的發音詞庫
  換回台羅讀音。
- **Fail-closed 選項**: `PipelineConfig.require_full_protected_coverage=True`
  時, 只要有任何藥名沒有經人工校正的台羅讀音, `pipeline.run()` 會直接
  `raise ValueError` 擋下合成, 而不是讓 TTS 用猜測的發音念出藥名。
- `drug_lexicon` 的值務必由台語專業人士確認過再放進去, 這個 repo 本身**不**
  內建任何未經審核的醫療發音資料, 範例詞庫僅供串接測試。

## 已知限制 (mock 版本)

- 翻譯/斷詞詞庫只有十幾個示範詞, 真實句子大部分字詞會 fallback 成原字。
- 連讀變調只在數字調格式上運作, 詞庫本身的 diacritic 讀音未套用變調。
- TTS 輸出只是提示音, 不是真人語音。
- `HTTPTranslationBackend` / `SpeechT5TailoBackend` 是可運作的骨架, 但沒有
  對應任何一個已驗證存在的正式 API/模型端點, 使用前一定要照上面的步驟自行
  串接與驗證。
