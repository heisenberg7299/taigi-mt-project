# Response Controller：大腦跟安全翻譯/TTS之間的把關層

日期：2026-08-03。目的：**不要讓「大腦」(意圖判斷+RAG+LLM)直接把自由文字
丟給TTS**，中間加一層Response Controller，負責風險判斷、安全閘門、決定
用哪種翻譯策略、失敗時要不要保持沉默。

```
Whisper/按鈕輸入
  -> 大腦：意圖+RAG+LLM
  -> 結構化回覆 JSON (BrainResponse)
  -> Response Controller：風險判斷與安全閘門
  -> tw_hokkien_tts_pipeline：中文->台語安全翻譯
  -> TTS Router
  -> Neurlang 即時生成 / MERaLiON 快取
  -> 播放語音
```

核心原則：**大腦負責「要回答什麼」，這裡負責「能不能安全說、怎麼翻成
台語、用什麼聲音播放」**。

## Code review後修正過的4個問題(2026-08-04)

有人只看文字描述(沒看程式碼)review過一次，點出4個從描述本身就看得出來
的漏洞，逐一核對程式碼後確認全部屬實，已修正：

1. **風險分級原本完全信任輸入JSON的`risk_level`，沒有任何規則式檢查**。
   一旦接上真的LLM，LLM可以自己說「這是low risk」然後繞過
   `StructuredMedicalRenderer`。修正：新增`enforce_deterministic_risk_level()`，
   只能把等級往上拉(low/medium→high)、絕不會往下降——`slots`裡出現
   `drug`/`dose`/`negation`任一個、或`intent`含醫療相關關鍵字，一律強制
   視為high，不管大腦自己標的值是什麼。
2. **原本只在翻譯前比對`response_zh`跟`slots`，翻譯後(`hanji_text`)完全
   沒有再檢查**，翻譯過程本身引入的錯誤會漏網。修正：翻譯完成後、TTS
   合成之前，再對最終`hanji_text`跟`slots`交叉比對一次。
3. **Schema驗證失敗(`status="rejected"`)原本不會觸發任何反應**——不播放
   固定回覆、不通知護理師，就是回一個JSON錯誤然後結束。修正：新增
   `_fail_safe()`，格式問題(`rejected`)跟翻譯/安全問題(`abstained`)一樣
   都會播放固定回覆+`action="call_nurse"`，`status`欄位保留區分只是方便
   查log，不影響「有沒有實際反應」。同時發現`BrainResponse.from_dict()`
   原本用`d["request_id"]`這種必要欄位直接索引，缺欄位時會raise
   `KeyError`直接讓程式crash(不會走到`validate()`)，一併改成`.get()`。
4. **`POST /v1/speech`原本零驗證**，任何連得到port的人都能呼叫，控制
   機器人對病患講什麼話卻沒有身份驗證。修正：加上`X-API-Key` header
   驗證(環境變數`ASSISTANT_SERVICE_API_KEY`設定)，沒設定時會印出明顯
   警告並以不驗證模式跑(方便本機開發，但正式部署前必須設定)。

新增8項測試涵蓋這4個修正(風險升級不降級、翻譯後比對、格式驗證失敗仍有
fallback、from_dict不會crash)，加上原本的全部46項測試通過。

## 這次review還沒動的部分(不是忽略，是需要更大投入或不同專業)

- **StructuredMedicalRenderer的模板內容有沒有醫療專業審核過**：目前完全
  沒有——這是工程手段補不了的，藥名/劑量/模板文字都需要藥師/護理師審核
  過的詞庫，不是這次架構修正的範圍。已經在`structured_renderer.py`跟
  fallback句子的說明裡明確標示「demo等級，尚未審核」，但**沒有審核過的
  內容，再嚴謹的架構保護的也是未經驗證的東西**，這點必須在正式使用前
  處理，不能靠程式碼解決。
- **`/nurse_alert`通知本身送出去之後，沒有重試機制或送達確認**：如果
  ROS訊息發布當下網路斷線或護理站系統掛掉，目前沒有任何重試或落地稽核
  紀錄，系統會誤以為已經安全交接。這需要接上真的訊息佇列/持久化紀錄
  機制，目前的`ros_bridge.py`只是單次publish。
- **多病患情境下的病患對應正確性沒有驗證過**：`slots.person`目前只是
  自由文字，沒有跟真正的病患資料庫/病患ID做比對，無法保證「這次回覆的
  病患」真的對應到`slots`裡講的那個人。目前所有測試都是單一情境，多
  病患部署前這塊需要獨立設計(例如強制`slots`帶`patient_id`、跟資料庫
  查詢比對，不能只靠文字姓名比對)。
- **Candidate A/B/C的通過標準**：`entities_ok`(候選文字裡是否包含
  Protected Token保護的實體原文)**且**`safety_ok`(`scripts/safety_checks.py`
  的五層檢查：否定詞/數字一致性/醫療術語白名單/長度異常/陷阱字，全部
  通過)兩者都成立才算「通過」，不是只看格式對不對。詳細順序邏輯在
  `tw_hokkien_tts_pipeline/adaptive_translation.py`的
  `translate_with_structured_fallback()`：候選A(原文)先試，通過就直接用；
  沒通過才試候選B(遮罩)；還沒通過、且屬於已支援的intent才用候選C；三個
  都沒通過才丟`UnsafeTranslationError`。
- **ROS bridge仍然沒有實機測試過**，這點在程式碼跟上次的說明裡已經強調
  過，這裡重申：正式接上機器人前一定要先在真的ROS環境跑過整合測試，
  尤其涉及機器人靠近病患的物理動作路徑，不能只靠這次的單元測試就上線。

## 目前進度：第一個里程碑已完成並實測

「手動JSON → Response Controller → 安全翻譯 → Neurlang → 真實WAV」這條路
已經端到端跑通並產生真實wav檔驗證過（見下方「快速測試」）。**還沒接真正
的Ollama大腦+RAG**——目前是拿手動寫的BrainResponse JSON當輸入，這是刻意
的分階段做法：先確認「JSON進來、安全機制擋得住、TTS真的會出聲」這條路
可靠，之後不管換什麼LLM/RAG當大腦，這條路都不用重做。

## voice_io_bridge.py：第一個真實(非手動填寫)輸入來源(2026-08-04)

接上[yuava22/Interactive-service-robots](https://github.com/yuava22/Interactive-service-robots)
的`voice_io_event_detector`套件——這不是LLM/RAG，是規則式(關鍵字比對)的
病床語音助理：Whisper ASR辨識文字 → `intent_rules.decide_event_and_reply()`
判斷3種意圖(喝水/上廁所/求助)並各自回傳固定中文回覆 → 原本用gTTS生成
中英雙語語音。

`voice_io_bridge.py`借用前兩步(ASR+規則式意圖判斷)，把`EventDecision`
轉成`BrainResponse`，取代原本的gTTS中英語音，改用已經驗證過的
`tw_hokkien_tts_pipeline`+neurlang輸出台語語音。實測過`WATER_REQUEST`
案例真的端到端跑出WAV（`translation_method="raw"`，因為`risk_level`
固定給`"low"`——這3種規則式意圖完全不涉及藥物/劑量/病歷，`slots`是空的，
不會被交叉比對擋下來，也不需要走`StructuredMedicalRenderer`）。

**risk_level跟priority是分開判斷的兩件事**：`HELP_REQUEST`(求助/救命)
的`priority`用`PRIORITY_NURSE_ALERT`(80，可能插播一般服務中的語音)，但
`risk_level`一樣是`"low"`，因為這句話的翻譯內容本身不涉及藥物/醫囑，
不需要`StructuredMedicalRenderer`把關——`priority`管的是播放佇列的插播
順序，`risk_level`管的是翻譯策略能不能讓adaptive A/B自由決定用字，兩者
互相獨立。

**這個轉換邏輯目前綁死一個假設**：對方repo的`intent_rules.py`只有3種
規則、完全不涉及藥物/醫囑，所以這裡才能安全地固定給`"low"`。如果對方
repo之後新增涉及藥物/醫囑的規則式意圖，`voice_io_bridge.py`必須跟著
更新(比照`response_controller.py`的`_HIGH_RISK_INTENT_KEYWORDS`)，不能
假設「規則式(非LLM)輸出」就永遠是低風險。

**`run_from_wav()`需要真的安裝對方套件**(`pip install -e path/to/
Interactive-service-robots`，含openai-whisper相依)才能跑ASR，這是刻意
delay-import的設計，讓`voice_io_bridge.py`本身不會因為對方套件沒裝而
整個import失敗——`event_decision_to_brain_response()`本身零相依，可以
獨立測試轉換邏輯(見`tests/test_voice_io_bridge.py`)。對方repo的
`gesture_detector.py`(YOLO鏡頭手勢偵測)跟`tts.py`(gTTS)完全沒有用到，
只借用ASR+意圖判斷這兩塊。

還沒做：真的裝這個套件跑`run_from_wav()`(目前只驗證過手動建構
`EventDecision`的轉換邏輯+後續管線，沒有真的餵Whisper辨識過的語音檔進去)、
`camera`子命令(手勢/物件偵測)完全沒有整合進來、意圖種類仍然只有對方
repo原本的3種(喝水/上廁所/求助)。

## 檔案結構

```
assistant_service/
  brain_response.py       BrainResponse dataclass + JSON schema驗證
  response_controller.py   核心路由邏輯：驗證JSON、比對response_zh與slots、
                            風險路由(high只用候選C/medium+low用adaptive A/B/C)、
                            失敗時的固定回覆
  tts_router.py             快取命中/已審核常用句用MERaLiON，其餘neurlang即時生成
  speech_request_queue.py   播放優先權佇列+狀態機(不依賴ROS，已用pytest驗證)
  ros_bridge.py             brain_tts_bridge.py，**沒有ROS環境測試過**，見下方說明
  api.py                    FastAPI包裝，POST /v1/speech
  voice_io_bridge.py         把yuava22/Interactive-service-robots的規則式意圖判斷
                            (EventDecision)轉成BrainResponse
  fallback_audio/           安全檢查失敗時的固定回覆音檔(neurlang生成的demo版本)
  cache/                    TTS Router的音檔快取(執行期產生，不進版控)
  tests/
    test_response_controller.py    12項測試(假backend, 決定性)
    test_speech_request_queue.py   6項測試(佇列/優先權/狀態機)
    test_voice_io_bridge.py        5項測試(EventDecision->BrainResponse轉換+端到端)
```

## Response Controller 的路由規則

`risk_level` 三選一，決定用哪種翻譯策略：

| risk_level | 策略 | 理由 |
|---|---|---|
| `high` | **只**用 `StructuredMedicalRenderer`(候選C) | 藥名/劑量/過敏、否定服藥、修改醫囑、呼叫特定醫護人員這類內容，不讓LLM自由決定最終文字。intent沒有對應模板時**直接abstain**，不會退回去用候選A/B(那樣還是讓LLM決定了高風險內容) |
| `medium` / `low` | `tw_hokkien_tts_pipeline.adaptive_translation.translate_with_structured_fallback()`(候選A/B/C) | 一般對話風險較低，允許LLM翻譯，但一樣有安全檢查把關 |

另外兩層檢查跟`risk_level`路由平行運作：

1. **JSON格式驗證**：`request_id`/`risk_level`/`action`等欄位不合法直接
   回傳`status="rejected"`(這是格式問題，跟翻譯安全是兩回事)。
2. **response_zh跟slots交叉比對**：如果大腦自己給的`slots.drug`沒有出現
   在它自己生成的`response_zh`裡，代表大腦內部就已經不一致，**在送去
   翻譯之前**就直接abstain，不用等翻譯完才發現問題。

## 安全檢查失敗時：不沉默、不亂講，播放固定回覆

三個候選(A/B/C)都失敗、或高風險intent沒有對應模板時，`status="abstained"`，
`action="call_nurse"`，播放固定句：

> 這个問題我無法度確定，我共你通知護理師。

**這句話目前是demo版本(neurlang生成)，還沒有經過台語母語者審核**，正式
使用前必須先確認這句話本身的用字/發音是正確的——不能因為它是「安全機制
的預設回覆」就假設它本身一定安全，這點跟`drug_lexicon`裡的藥名讀音一樣，
都需要人工審核才能真正信任。

## TTS Router

```python
if cached_audio_exists(text):
    play_cached()
elif is_approved_common_sentence(text):
    use_meralion_and_cache()
else:
    use_neurlang_realtime()
```

`approved_sentences.json`(在`cache/`底下，執行期查找)目前是空的demo檔案，
要放哪些句子需要由台語專業人士審核過的固定回覆決定，不是隨便什麼句子都
適合花35倍時間(MERaLiON RTF=3.63)預先生成快取。

## 快速測試

前置需求跟`live_test/`一樣(Ollama + 兩個TTS backend process)：
```bash
ollama serve
TTS_BACKEND=neurlang python3 live_test/tts_backend.py    # port 5010
TTS_BACKEND=meralion python3 live_test/tts_backend.py    # port 5011(只有approved_sentences命中才會用到)
```

跑pytest(不需要上面那些process，用假backend決定性測試)：
```bash
python3 -m pytest assistant_service/tests/ -v
```

啟動FastAPI服務並手動測試：
```bash
python3 -m uvicorn assistant_service.api:app --host 127.0.0.1 --port 8000

curl -X POST http://127.0.0.1:8000/v1/speech -H "Content-Type: application/json" -d '{
  "request_id": "req_001",
  "intent": "medication_reminder",
  "risk_level": "high",
  "language": "zh-TW",
  "response_zh": "請記得在晚餐後服用盤尼西林。",
  "slots": {"drug": "盤尼西林", "time": "晚餐後", "dose": null, "person": null, "negation": false},
  "action": "speak",
  "evidence_ids": [],
  "priority": 80
}'
```
會回傳`status="completed"`、`translation_method="structured_c"`、實際的
`audio_path`(真實wav檔)。實測過這個案例、一個low-risk一般對話案例(成功)、
一個高風險但沒有對應模板案例(正確abstain)、一個slots跟response_zh矛盾的
案例(正確在翻譯前就abstain)，四種情境都驗證過。

## 還沒做的部分(照建議的實作順序，這輪只做到第一個里程碑穩固為止)

- **真正的Ollama大腦+RAG**：`voice_io_bridge.py`接的是規則式(關鍵字比對)
  意圖判斷，不是LLM/RAG，`slots`固定是空的(對方repo的規則不輸出結構化
  藥物/劑量資料)——離「真正的LLM生成`response_zh`+`slots`」還有一段距離，
  但已經是第一個真實(非手動填寫)的BrainResponse來源。
- **`voice_io_bridge.run_from_wav()`沒有真的裝對方套件跑過**：只驗證過
  手動建構`EventDecision`的轉換邏輯+後續管線(含真實WAV輸出)，沒有真的
  裝`voice_io_event_detector`套件、餵Whisper辨識過的錄音檔進去過。
- **ROS bridge沒有實機測試過**：`ros_bridge.py`是照ROS2慣例寫的，這台
  開發機沒有裝rclpy，`BrainTTSBridge`會在沒有ROS環境時主動報錯而不是
  靜默失敗——正式部署前必須先在真的ROS環境跑過。核心優先權佇列/狀態機
  邏輯(`speech_request_queue.py`)已經獨立測試過，不依賴ROS。
- **`approved_sentences.json`是空的**：TTS Router的MERaLiON快取路徑目前
  永遠不會被觸發(因為沒有任何句子在清單裡)，需要台語專業人士先審核一批
  常用句才能真正發揮這個機制的價值。
- **fallback句子本身沒有母語者審核過**：見上方「安全檢查失敗時」章節。
