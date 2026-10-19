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

**更新(2026-08-04，見下方「LLM大腦+中英雙語+鏡頭手勢整合」章節)**：
`run_from_wav()`本身沒有直接被使用(`web/app.py`用自己的`asr_bridge.py`，
支援中英雙語自動偵測，不是對方寫死中文的`asr.py`)，但整條「真的語音檔
->Whisper->規則式意圖判斷->BrainResponse->Response Controller->真實台語
WAV」的路已經端到端實測過(用gTTS合成語音當輸入模擬麥克風錄音)；`camera`
子命令對應的手勢偵測功能也已經整合進來(`gesture_bridge.py`)，用真實YOLO
模型在測試圖片上驗證過。意圖種類確實仍然只有對方repo原本的3種，這點沒變。

## LLM大腦+中英雙語輸入+三語輸出+鏡頭手勢整合(2026-08-04)

使用者要求把yuava22/Interactive-service-robots(語音I/O+規則式意圖判斷+
鏡頭手勢偵測)跟這個專案已經做好的台語安全翻譯/Response Controller結合，
並且要接真正的LLM大腦、支援中英文語音輸入輸出、加上鏡頭手勢偵測，最後
用一個網頁把整條路串起來驗證。這一輪全部完成，而且是**真實跑過**(真的
Ollama呼叫、真的Whisper辨識、真的YOLO偵測、真的產生可播放音檔)，不是
只有mock測試。

### 新增模組

- **`brain_llm.py`(`OllamaBrain`)**：真正的LLM大腦，呼叫Ollama的通用對話
  模型(`qwen2.5:7b-instruct`，另外`ollama pull`的，跟翻譯用的
  Taigi-Llama-2-Translator是不同模型、職責分開)。system prompt要求LLM
  輸出`intent`/`risk_level`/`response_zh`/`response_en`/`slots`的JSON，
  用Ollama的`format=json`強制合法JSON，仍然防禦性處理解析失敗(回傳空dict
  讓下游`validate()`自然擋下來，不會crash)。**大腦自己標的risk_level/
  slots不能被信任**，`response_controller.py`的
  `enforce_deterministic_risk_level()`才是最終防線；這裡只是讓prompt
  盡量配合規則式檢查(藥物相關一律要求標high、填slots)。真實測試：一般
  聊天正確生成合理回覆；「我可以多吃一顆普拿疼止痛藥嗎」被正確標記
  risk_level=high、slots.drug=普拿疼——而且因為LLM的安全回覆(「這個問題
  我會轉達給護理人員」)沒有把藥名寫進`response_zh`本文，跟`slots.drug`
  對不上，被pre-translation交叉比對正確攔下來abstain，走固定回覆+通知
  護理師——這正是這層層防護設計要達到的效果：就算LLM遵照指示給出「安全」
  的迴避回答，只要跟自己給的結構化資料兜不起來，照樣不會被放行。
- **`BrainResponse`新增`response_en`欄位**(選填)：LLM在同一次生成順便
  給的英文翻譯，**沒有跟`response_zh`->`hanji_text`同等的Protected
  Token/安全檢查**，純粹輔助用。
- **`asr_bridge.py`**：中英雙語語音輸入，用openai-whisper的Python API
  (不是像對方原本shell出去呼叫CLI)，自動偵測語言而不是寫死中文。真實
  測試：gTTS合成的中文/英文語音都能被正確辨識出文字+正確偵測語言代碼
  (`zh`/`en`)。
- **`multilingual_output.py`**：中文/英文補充語音(gTTS)，明確跟主線的
  台語安全通道分開——中文音檔念的是已經過pre-translation交叉比對的
  `response_zh`原文(安全)，英文音檔念的是`response_en`(**沒有**同等安全
  檢查，純參考)。只有`status=completed`且`action=speak`才會產生，
  fail-safe的固定回覆不重複做三語版本。
- **`gesture_bridge.py`**：鏡頭手勢/物件偵測(借用對方的
  `BedsideGestureDetector`，YOLO姿態+物件模型)，拿掉對方`run_camera()`
  裡`cv2.imshow()`的阻塞式GUI迴圈，改成適合網頁後端逐張frame呼叫的
  `GestureDetectorSession`。事件->BrainResponse的轉換重用
  `voice_io_bridge.event_decision_to_brain_response()`，不重複定義
  intent/priority對應表。真實測試：用ultralytics官方範例圖(`zidane.jpg`)
  跑過`GestureDetectorSession.process_frame()`，YOLO模型(`yolov8n.pt`+
  `yolov8n-pose.pt`)真的載入、真的推論、回傳正確形狀的標註畫面，沒有
  crash(該測試圖不是病床手勢動作，正確回傳`stable_event=None`，沒有誤判)。
- **`web/app.py`**：整合驗證網站(Flask, port 5020)。文字輸入/瀏覽器錄音
  /鏡頭手勢三種輸入方式，都走同一條`_finish_pipeline()`：Response
  Controller安全把關->三語輸出。規則式快速路徑(yuava22 intent_rules)優先，
  沒匹配到才用LLM大腦。任何選用依賴(whisper/voice_io_event_detector/
  ultralytics)沒裝都優雅降級、明確告知前端哪個功能停用，不會整個500。
  **真實HTTP測試**(不是test client，是真的啟動server用curl/requests打)：
  規則式路徑(「我想要喝水」)、LLM路徑(一般聊天、醫療問題)、真實語音上傳
  (gTTS合成「我想要上廁所」當模擬錄音，Whisper正確辨識、正確判斷語言、
  正確路由)、鏡頭手勢frame上傳、三語音檔(Hokkien wav/中文mp3/英文mp3)
  下載都驗證過是真的可播放檔案。也修過一個real bug：fail-safe的固定
  回覆音檔在`fallback_audio/`、跟一般案例的`cache/audio/`是不同目錄，
  原本的音檔路由沒有處理這個情況會404，已修好並加上會真的下載檔案驗證
  的回歸測試。

### 環境設置注意事項(這次是怎麼裝起來的，供之後重建環境參考)

- `ollama pull qwen2.5:7b-instruct`(4.7GB)
- `pip install openai-whisper gtts ultralytics opencv-python`(見
  `requirements-optional.txt`)
- **`voice_io_event_detector`套件沒有標準packaging(對方repo沒有
  setup.py/pyproject.toml)**，不能用`pip install -e`，這次是用一個
  `.pth`檔案把對方`src/`目錄加進venv的`sys.path`解決的。這次clone的
  路徑是job暫存目錄(session結束會被清掉)，**不是long-term可靠的設置**，
  之後要重建環境的人需要自己clone一份到穩定路徑、重新指定`.pth`(或改成
  對方repo補上packaging後直接`pip install -e`)。
- YOLO權重(`yolov8n.pt`/`yolov8n-pose.pt`)用`ultralytics`自動下載，
  手動放到對方repo的`models/`目錄下(對方的`model_config.py`會自動找到，
  不需要額外設定`YOLO_DETECT_MODEL`/`YOLO_POSE_MODEL`環境變數)。

### 還沒做的部分

- 對方repo的`voice_io_event_detector`套件目前不是穩定的pip相依(見上面
  packaging問題)，正式部署前需要對方補上`setup.py`/`pyproject.toml`，
  或把需要的邏輯用正式的方式vendor/打包。
- 鏡頭手勢偵測只驗證過靜態測試圖片能跑起來、不crash，**沒有用真實攝影機
  對著真人做「舉手求助/摸嘴巴要喝水/摸骨盆要上廁所」這些動作實測過**，
  準確度完全未知，正式使用前一定要用真人在真實病床環境驗證。
- 語音輸入的即時串流延遲、多輪對話(LLM大腦目前是單輪、沒有對話歷史)、
  RAG(`evidence_ids`檢索)都還沒做，見`brain_llm.py`docstring。
- `response_en`(英文補充語音)沒有Protected Token等級的安全檢查，`README`
  跟程式碼註解都明確標註這點，不能誤以為三語輸出都同等可信。

## fail-safe時三語都要有聲音(2026-08-04)

原本`multilingual_output.py`只在`status=="completed"`時產生中英文補充
語音，fail-safe(`status`為`abstained`/`rejected`)時中英文都是空的，只有
台語會播放固定回覆——使用者測試後要求三語都要有。修正：`response_controller.py`
新增`FALLBACK_SENTENCE_ZH`/`FALLBACK_SENTENCE_EN`兩句固定翻譯好的句子
(跟`FALLBACK_SENTENCE_HAN`意思一致)，`synthesize_multilingual()`偵測到
`controller_result.hanji_text == FALLBACK_SENTENCE_HAN`時，中英文改用這
兩句固定句子合成語音，**不是**`brain_response`原本的`response_zh`/
`response_en`——這是刻意的：進到fail-safe代表大腦原本要講的內容已經被
判定不安全/跟slots不一致(例如藥名沒出現在回覆本文裡)，如果中英文語音
講出那份被擋下來的內容，等於讓台語那邊的安全把關失去意義(病人聽不懂
中/英文沒關係，但陪同的家屬/工作人員聽得懂，一樣不該聽到被擋下來的
內容)。三句固定句**都還沒經過母語者審核**，跟原本`FALLBACK_SENTENCE_HAN`
一樣的限制。已用真實HTTP請求驗證：「我可以多吃一顆普拿疼嗎」被安全機制
abstain後，三語音檔全部產生且都是真實可下載播放的檔案。新增2項測試
(驗證fixed句子被使用、且brain_response原本被擋下的文字絕對不會被拿去
合成)，全部**85 passed, 2 skipped**。

## 語音+視覺統一分類：multimodal_brain.py + MediaPipe Pose(2026-08-04)

使用者要求把語音跟視覺(影音)訊號放進同一個模組，視覺辨識要包含MediaPipe
Pose，而且分類判斷要依靠LLM，最後整合成一個介面。這一輪把原本各自獨立的
`voice_io_bridge.py`(語音查表)+`gesture_bridge.py`(視覺查表直接決定回覆)
兩條互相看不到對方的路徑，改成統一經過新的`multimodal_brain.py`分類。

### `multimodal_brain.py`：統一分類入口

`classify(voice_text=None, vision_description=None, ...) -> (BrainResponse, 分類路徑)`。
規則：**純語音**輸入且對得到yuava22規則式關鍵字(喝水/上廁所/求助)時，走
原本驗證過的快速路徑，不需要LLM推論延遲；除此之外的情況(任何視覺訊號、
語音沒對到規則式關鍵字、或語音+視覺同時出現)一律組合所有可得訊號一起
交給LLM大腦判斷——視覺訊號本身(「手靠近嘴巴」這種姿態描述)沒有語意，
用固定查表決定最終回覆文字並不合理，需要LLM的判斷力去解讀，這是這次
要求「視覺辨識也要依靠LLM分類」的核心改動。語音+視覺同時出現時，就算
語音對到規則式關鍵字，也不會走快速路徑，因為視覺訊號可能提供衝突或補充
資訊(例如語音說「不用了」但鏡頭觀察到疑似求助動作)，必須讓LLM綜合兩者
判斷，查表法完全無法處理這種情境——`brain_llm.py`的system prompt也更新
成能接收「語音+視覺觀察」兩行輸入，並明確規定衝突時以語音內容為準(語音
是明確語意表達，鏡頭觀察只是姿態推測)。

### `vision_bridge.py`：MediaPipe Pose(視覺辨識的新backend)

新增`MediaPipePoseDetector`，跟既有`gesture_bridge.py`的YOLO-pose backend
並存(不是取代)，兩者都產生統一的`VisionSignal(event, description_zh)`
格式。網頁後端(`web/app.py`的`_vision_backend()`)MediaPipe優先，沒裝好
(套件或模型檔缺任一個)才退回YOLO-pose。

**用MediaPipe新版Tasks API(`PoseLandmarker`)，不是舊版`mp.solutions.pose`**
——這次裝的`mediapipe==1.0.0`已經完全移除`mp.solutions`(比對方examples
裡`mediapipe_pose_gesture.py`參考的舊版API新，那份程式碼直接搬過來會
import錯誤)，改用Tasks API，需要另外下載pose landmarker模型檔(`.task`，
`requirements-optional.txt`裡有下載指令)，放在`assistant_service/models/`
(已被`.gitignore`的`models/`規則涵蓋，不進版控，跟YOLO權重處理方式一致)。

判斷邏輯跟YOLO版本不完全一樣(BlazePose 33個landmark、座標系統也不同，轉成
pixel座標後沿用類似的距離閾值)：YOLO版本的「求助」要看最近幾幀手腕有沒有
**橫向擺動**(揮手)，這裡簡化成「手腕目前y座標高於肩膀」(單純舉手姿勢，
不要求擺動)——這是刻意簡化，不是想做出一致的判斷準則，因為兩個backend
產生的訊號最終都會送進LLM由LLM判斷，這裡的規則只是產生「觀察到什麼」的
粗略描述，不是最終決策，不需要跟YOLO版本追求同樣的精確度。

**已用真實環境端到端驗證**：MediaPipe模型真的載入、真的在測試圖片上跑
(3項測試，非mock)；`vision_description`真的送進真實Ollama、真實
Response Controller、真實neurlang TTS，產生真實可播放wav檔(見下方「還沒
做」，這裡驗證的是「訊號能不能正確流過整條管線」，不是「偵測準不準」)。

### `web/app.py`：真的統一成一個介面

文字/語音/視覺三種輸入現在全部經過同一個`_run_pipeline()`->
`multimodal_brain.classify()`，不再是「文字/語音一套邏輯、鏡頭又是另一套」
——`/api/gesture_frame`改名`/api/vision_frame`，回傳格式一致，前端頁面
本來就是同一個頁面(文字輸入框+錄音按鈕+鏡頭偵測都在同一個HTML)，這次
補上了後端邏輯真正統一，不是只有UI擺在一起。

### 還沒做

- **MediaPipe backend完全沒有用真人在鏡頭前做實際手勢動作驗證過**，跟
  YOLO backend的既有限制一樣，只驗證過靜態測試圖片能跑起來、不crash。
- 判斷準則(「舉手」/「靠近嘴巴」/「靠近骨盆」的距離閾值)是沿用YOLO版本
  抄過來的概略數值，沒有針對MediaPipe的座標系統/攝影機視角重新校準過。
- 語音+視覺同時輸入的組合prompt只做過陽性案例的手動測試(見上方)，沒有
  系統性測過大量「語音視覺矛盾」的情境LLM判斷得準不準。

## 檔案結構

```
assistant_service/
  brain_response.py       BrainResponse dataclass + JSON schema驗證
                           (含選填的response_en欄位)
  response_controller.py   核心路由邏輯：驗證JSON、比對response_zh與slots、
                            風險路由(high只用候選C/medium+low用adaptive A/B/C)、
                            失敗時的固定回覆
  tts_router.py             快取命中/已審核常用句用MERaLiON，其餘neurlang即時生成
  speech_request_queue.py   播放優先權佇列+狀態機(不依賴ROS，已用pytest驗證)
  ros_bridge.py             brain_tts_bridge.py，**沒有ROS環境測試過**，見下方說明
  api.py                    FastAPI包裝，POST /v1/speech
  voice_io_bridge.py         把yuava22/Interactive-service-robots的規則式意圖判斷
                            (EventDecision)轉成BrainResponse
  brain_llm.py               真正的LLM大腦(Ollama通用對話模型)
  asr_bridge.py               中英雙語語音輸入(Whisper自動偵測語言)
  multilingual_output.py     中文/英文補充語音輸出(gTTS)
  gesture_bridge.py           鏡頭YOLO-pose偵測->BrainResponse(視覺辨識備援backend)
  vision_bridge.py             鏡頭MediaPipe Pose偵測(視覺辨識主要backend)
  multimodal_brain.py         語音+視覺訊號統一分類入口(依靠LLM判斷，不用查表)
  web/                        整合驗證網站(Flask, port 5020)
  models/                    MediaPipe pose landmarker模型檔(執行期下載，不進版控)
  fallback_audio/           安全檢查失敗時的固定回覆音檔(neurlang生成的demo版本)
  cache/                    TTS Router+multilingual_output的音檔快取(執行期產生，不進版控)
  requirements-optional.txt  選用依賴清單(這次整合新增的部分)
  tests/
    test_response_controller.py    12項測試(假backend, 決定性)
    test_speech_request_queue.py   6項測試(佇列/優先權/狀態機)
    test_voice_io_bridge.py        5項測試(EventDecision->BrainResponse轉換+端到端)
    test_brain_llm.py               7項mock測試
    test_brain_llm_smoke.py         2項真實Ollama測試
    test_asr_bridge_smoke.py        2項真實Whisper測試
    test_multilingual_output.py     5項測試(4 mock+1真實gTTS)
    test_gesture_bridge.py          2項測試(需要對方套件才會跑)
    test_vision_bridge.py           3項真實MediaPipe測試
    test_multimodal_brain.py        6項測試(假brain, 決定性)
    test_web_app.py                 9項路由邏輯測試(mock)
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
