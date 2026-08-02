# 階段4：TTS 模型調研（候選盤點，尚未全部實測）

日期：2026-08-01

目標：找出除了目前在用的 `neurlang/coqui-vits-suisiann-minnan-hokkien` 之外，
還有哪些免費、可本機部署的台語 TTS 值得拿來跟同一份100句測試集比較。

## 候選清單

`Native input format`：模型原生吃什麼輸入。`Required frontend`：要接進我們pipeline
（輸出是台語漢字`nan_han`）還需要額外加哪一層前處理。

| 模型 | 狀態 | 授權 | 規模 | Native input format | Required frontend | 備註 |
|---|---|---|---|---|---|---|
| `neurlang/coqui-vits-suisiann-minnan-hokkien` | **已驗證可用（目前主力）** | CC-BY-SA-4.0 | VITS，CPU RTF~0.11-0.13 | Hanji（漢字，內建pygoruut自動轉IPA） | None | 已產生200句候選音檔，正在收母語者回饋 |
| MediaTek BreezyVoice-Taigi | **查無公開權重，無法實測** | 論文未揭露 | CosyVoice2微調，~10,000小時合成資料 | 不明（論文未寫） | 不明 | 論文（[arXiv:2603.19259](https://arxiv.org/html/2603.19259)）有報告數字但 HuggingFace 上找不到對應模型檔；已搜尋 MediaTek-Research 全部27個模型跟關鍵字「Taigi」「BreezyVoice」都沒有這個repo。**重要發現**：論文自報的「台語發音準確率只有59.2%」——連 MediaTek 專門投入的模型都只有六成不到的道地發音率，這代表台語TTS本身難度很高，不是我們資源不夠的問題 |
| [MERaLiON-OmniVoice-Hokkien-TTS](https://huggingface.co/MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS) | **已實測，重新評為積極候選（見下方）** | MERaLiON-3-Public-Licence（自訂條款，需另外詳讀是否允許研究/商用） | 0.8B參數，~2.7GB，支援聲音克隆 | Hanji（漢字），`generate(text=..., language="nan")` | None | 新加坡福建話模型，但實測發現可以voice clone成neurlang的聲音、且會自動對難字code-switch成中文發音（見下方詳細） |
| Curiousfox / wenxinkoh06 的 `speecht5_tailo-hokkien` 系列 | **Conditional fallback — frontend prototype available**（見下方 taibun 前端測試） | MIT（模型）+ MIT/CC-BY-SA-4.0（taibun） | SpeechT5微調（0.1B），體積小 | Tâi-lô羅馬字（漢字直接輸入會失敗，需前端轉換） | `taibun` Hanji→Tâi-lô（已接上，見下方） | 命名用「tailo」明確針對台灣台語，授權最寬鬆 |
| `chen778560489/coqui-vits-suisiann-minnan-hokkien` | 略過 | 同neurlang | - | 同neurlang | None | 看起來是 neurlang 模型的 fork/鏡像，非獨立模型，跳過 |

## `speecht5_tailo-hokkien`（wenxinkoh06/ver1.0.d）實測結果（2026-08-01）

**結論：這個checkpoint目前無法接進我們的pipeline，先擱置。**

### 怎麼測的

模型卡幾乎是空白模板（沒寫vocoder、speaker embedding、輸入格式），只能照SpeechT5的
標準用法回推：
- processor 用 base `microsoft/speecht5_tts`（這個repo自己沒附tokenizer/processor檔）
- vocoder 用標準搭配 `microsoft/speecht5_hifigan`
- speaker embedding 用 `Matthijs/cmu-arctic-xvectors` 隨便挑一個當佔位（不是這個模型
  訓練時用的真實語者，音色大概率不對，但足夠測「有沒有正常發出語音」）

### 發現：只吃羅馬字/英文，完全吃不了漢字

分別餵羅馬字（自己土法拼的Tâi-lo）、英文、繁體中文漢字，量測輸出音檔的能量與靜音比例：

| 輸入 | 範例 | 長度 | RMS能量 | 靜音比例 |
|---|---|---|---|---|
| Tâi-lo羅馬字 | `Gua2 su1-iau3 lim1 tsui2.` | 3.33s | 0.127 | 51% |
| Tâi-lo羅馬字 | `Ching-hui2 kiu3-ho7 tshia1.` | 3.58s | 0.126 | 50% |
| 英文（對照組） | `I need to drink some water please.` | 4.61s | 0.115 | 46% |
| **繁體中文漢字** | `我需要啉水。` | **0.96s** | **0.005** | **94%** |
| **繁體中文漢字** | `請幫我叫護理師。` | **0.96s** | **0.005** | **93%** |

羅馬字跟英文都合成出長度合理、有正常語音能量起伏的音檔；漢字輸入幾乎是純靜音
（能量趨近雜訊底噪），不是「發音不準」，是「模型根本沒真的發出語音」。

原因很清楚：這個repo沿用base SpeechT5的英文sentencepiece tokenizer，詞彙表裡沒有
中文字，漢字輸入被切成幾乎沒有語意的token，模型自然生不出東西。

### 對本專案的影響——注意這是G2P問題，不是翻譯問題

我們目前整個pipeline設計是以**台語漢字（`nan_han`）為主要表示法**（見`data/schema.md`），
`tailo`欄位目前全專案沒有任何一筆資料填過。要用這個模型，必須先有一個可信賴的
「台語漢字 → Tâi-lô」轉換層。

**要澄清的一點**：這跟「華語→台語翻譯」（PLAN.md記錄過辭典逐詞替換失敗的那個問題）
**不是同一個問題**，不能直接類比：

- 「華語→台語翻譯」：輸入是華語，要處理語意、詞彙選擇、語序轉換，才能得到自然台語句子
- 「台語漢字→Tâi-lô」：輸入本身**已經是**正確台語漢字（例如「我欲去便所」），
  只需要決定每個字詞的台語**讀音**——這是台語字音轉換／G2P問題

G2P仍然不簡單（一字多音、文白異讀、變調、詞組讀音、地區腔調、非教育部推薦字、
華語台語漢字混用），但跟翻譯是不同性質、不同難度的兩件事，不應該混為一談。

**工程結論仍然成立**：為了一個目前效果尚未證明優秀的SpeechT5 checkpoint，額外建立
一套完整可靠的台語G2P，不符合現在的投入效益。先擱置。

### 正式結論記錄

```text
Candidate: speecht5_tailo-hokkien
Status: Deferred / Not suitable for current pipeline

Finding:
- Tâi-lô and English inputs produce audible, non-flat speech.
- Traditional Chinese character inputs produce near-silent audio.
- The failure is caused by input-tokenization incompatibility rather
  than synthesis runtime failure.

Technical cause:
- The model retains the original SpeechT5 English-oriented tokenizer.
- Traditional Chinese characters are not represented meaningfully.
- The model therefore effectively requires romanized Tâi-lô input.

Integration cost:
- Requires a context-aware Taiwanese Hokkien Hanji-to-Tâi-lô G2P layer.
- Reliable conversion must handle polyphonic characters, lexical readings,
  literary/colloquial readings, tone sandhi and mixed orthography.
- This additional dependency is not currently justified by the model's
  unverified synthesis quality.

Decision:
- Exclude from the active TTS candidate shortlist.
- Retain only as a possible future Tâi-lô-input baseline.
```

**Update（2026-08-01，同日稍晚）**：接上 `taibun`（公開 Hanji→Tâi-lô 套件）當
frontend 後，原本判定 fail 的漢字輸入全部技術性成功（見下方「Hanji→Tâi-lô
Frontend」章節），狀態改為：

```text
Status (updated): Conditional fallback — frontend prototype available
Frontend: taibun (single tool, no additional G2P layer stacked)
Caveat: Only feasibility confirmed (audio is generated, silence/RTF normal).
        Phonetic correctness of taibun's Tâi-lô output NOT yet verified by
        a native speaker. Do not treat as production-ready.
```

## 建議下一步優先順序（2026-08-01 taibun frontend測完後更新）

1. **人工評分 `speecht5_tailo_via_taibun` 這6句** — 透過驗證平台讓母語者聽，補
   `omission_rate`／`intelligibility_score`，這才是決定taibun路線值不值得繼續
   投入（Phase 2/3）的關鍵資料，不是靠客觀指標自己判斷
2. **MERaLiON-OmniVoice-Hokkien-TTS** — 先確認它實際吃的是漢字還是羅馬字（目前文件
   沒寫清楚），是漢字才值得深測；是羅馬字可以直接套用同一個taibun frontend試試看
3. **CosyVoice／Qwen系列重新實測** — 用同一批漢字、Tâi-lô、英文、中英台混合輸入
   統一測過一輪，不要只憑今天稍早那次「無台語支援」的初步結論就完全排除，換句話說
   要用跟這次一樣的客觀量測方法（能量/靜音比例）重新確認，不能只憑主觀聽感
4. **建立候選淘汰門檻** — 靜音比例、有效語音長度、生成速度(RTF)、漏字率、人工可懂度
   五個指標，未來每測一個新候選都套用同一組門檻，不要每次都重新發明評分標準
5. **G2P最後才評估** — 只有在「最佳候選模型必須吃Tâi-lô輸入」且「音質明顯勝出現有
   neurlang VITS」兩個條件都成立時，才值得投入建置台語漢字→Tâi-lô的G2P層

## 統一 Benchmark Runner（已建好，2026-08-01）

`scripts/tts_benchmark/`：可重複使用的跑分框架，落實上面「淘汰漏斗」流程，
之後新增候選模型只要寫一個 adapter，不用重寫測試邏輯。

- `benchmark_set.py` — 固定測試集（12句：台語漢字/Tâi-lô/繁體華語/英文/
  中英台混合/數字病房號醫療詞彙/否定與較長句，每類2句）
- `metrics.py` — 統一算法：`audio_duration_sec` / `silence_ratio`（靜音門檻
  0.01振幅） / `effective_speech_sec` / `rtf`；`silence_ratio > 0.75` 自動判
  `fail_silence`（門檻依據：正常語音案例約46-57%靜音，speecht5漢字失敗案例
  93-94%，兩者間留安全邊界）
- `adapters/base.py` — 共同介面（`name` / `input_format` / `required_frontend`
  / `load()` / `synthesize()`），跑分時只挑跟adapter.input_format相容的測試句
- `adapters/neurlang_vits.py`、`adapters/speecht5_tailo.py` — 已實作並跑過
- 執行：`python scripts/run_tts_benchmark.py`，輸出 `tests/tts_benchmark_results.jsonl`
  和 `.csv`，音檔存 `tests/tts_benchmark_audio/{model}/`（不進版控，可重新產生）
- `omission_rate`、`intelligibility_score` 兩欄留null，等母語者人工補（其餘欄位全自動）

### 第一次跑分結果

| model | 測了幾句 | 平均silence_ratio | 平均rtf | decision |
|---|---|---|---|---|
| neurlang-vits-suisiann | 6（han+num+neg類，全相容） | 53% | **0.10**（CPU上比即時快約10倍） | 全部 pending_human_review |
| speecht5_tailo_Hokkien_ver1.0.d | 2（僅tailo類，格式相容的只有這些） | 53% | 0.20-0.68（明顯慢很多，其中一句慢到接近0.7） | 全部 pending_human_review |

兩個模型在各自相容的輸入格式下都正常產生語音（沒有觸發`fail_silence`），這跟稍早
單獨測試的結論一致。新發現：speecht5的RTF比neurlang慢3-7倍——雖然還沒到不能用
的程度，但這也是選型時的額外扣分項，一併記錄起來，之後每個新候選都會有這個欄位
可以直接比較。

## Hanji→Tâi-lô Frontend：接上 taibun（2026-08-01）

原本判斷「要用speecht5_tailo就得先建G2P，先擱置」。查證後發現已經有現成公開工具
`taibun`（PyPI，程式碼MIT授權，內建詞典CC-BY-SA-4.0，支援Tâi-lô/POJ/TLPA/IPA輸出，
含斷詞器），不用從零做，值得先測這條路能不能直接打通。

**刻意只接一個G2P工具**（taibun），不同時疊教育部辭典覆寫或臺灣言語工具正規化——
先確認單一工具夠不夠用，避免多個轉換來源同時作用時，出錯了搞不清楚是哪一層的問題。
不夠用再考慮加辭典覆寫當第二層（分階段投入，不要一次全做）。

### Phase 1：可行性測試（已完成）

新增 `SpeechT5TailoViaTaibunAdapter`（`scripts/tts_benchmark/adapters/speecht5_tailo_via_taibun.py`），
組合方式：`台語漢字 → taibun.Converter(system="Tailo") → speecht5_tailo-hokkien`。
跑同一個benchmark runner，測 han/num/neg 三類（原本speecht5完全無法處理的漢字輸入）：

| id | 原文 | taibun轉換結果 | silence_ratio | rtf |
|---|---|---|---|---|
| han_01 | 我需要啉水。 | Guá su-iàu lim tsuí. | 48% | 0.188 |
| han_02 | 請共我叫護理師。 | Tshiánn kā guá kiò hōo-lí-su. | 45% | 0.175 |
| num_01 | 請共我叫三號病房的護理師。 | Tshiánn kā guá kiò sann hō pēnn-pâng ê hōo-lí-su. | 46% | 0.179 |
| num_02 | 我這馬血壓一二零，體溫三十六度五。 | Guá tsit-má hueh-ap tsi̍t jī lîng, thé-un sann-tsa̍p-la̍k tōo gōo. | 44% | 0.186 |
| neg_01 | 我無胸疼，煩勞你共我確認一下這禮拜愛食的藥仔有偌濟種。 | Guá bô hing thiànn, huân lô lí kā guá khak jīn tsi̍t-ē tse lé-pài ài tsia̍h ê io̍h-á ū guā-tsē tsíng. | 43% | 0.19 |
| neg_02 | 我猶未做檢查，毋過我這幾工攏無食藥仔，會使先毋通叫醫生無？ | Guá iáu-buē tsò kiám-tsa, m̄-koh guá tse kuí kong láng bô tsia̍h-io̍h-á, ē-sái sing m̄-thang kiò i-sing bô? | 44% | 0.195 |

**結果：6句全部成功，靜音比例43-48%，落在neurlang（46-53%）跟原生tailo輸入
（50-54%）的同一個正常範圍內，沒有一句觸發`fail_silence`門檻。** RTF約0.18-0.20，
比稍早單獨測試時的0.20-0.68更快更穩定（推測前次偏慢是模型剛載入的暖機效應）。

技術結論：**taibun frontend prototype有效，`speecht5_tailo-hokkien`從
`Deferred`改列 `Conditional fallback — frontend prototype available`。**

### 這只證明「技術可行」，不等於「發音正確」——Phase 2還沒做

客觀指標（靜音比例、RTF）只能證明「這個pipeline有正常產生語音」，不能證明
taibun產生的Tâi-lô本身選字選音對不對——一字多音、文白異讀這些問題，taibun
是規則/詞典導向的轉換工具，不保證每句都對，需要母語者比對才能確認。

Phase 2（100句 gold-standard Hanji→Tâi-lô 驗證集，人工校正 vs taibun自動輸出
比對音節/聲調錯誤率）跟 Phase 3（醫療詞彙優先查表覆寫，例如用教育部辭典的
「護理師」「血壓」等詞條讀音蓋過taibun的預設猜測）都還沒做，先不投入，等
Phase 1 這批音檔透過驗證平台收到人工可懂度評分、確認taibun路線真的值得投入
之後再做。

### 開發者快聽（2026-08-01）：「有進步，但還是差一點味道」

開發者自己（非母語者，僅供初步參考，不能取代正式的母語者驗證）用Finder直接
對照聽了這6句 `speecht5_tailo_via_taibun` vs `neurlang-vits-suisiann` 的同句版本，
結論：**taibun frontend確實讓speecht5從完全發不出聲進步到聽得出是在講話，
但整體自然度、腔調的「台語味」還是不如neurlang這個目前的主力模型**。

這跟客觀指標（靜音比例、RTF）測不出來的東西吻合猜測：
- speecht5_tailo checkpoint本身規模小（0.1B）、社群熱度低，訓練資料量可能不足
- 目前用的是`cmu-arctic-xvectors`裡隨便挑的英語語者embedding當佔位（見前面
  「怎麼測的」章節），音色/韻律本來就不是為台語調的，這點neurlang（有自己
  訓練過的台語語者）天生佔優勢

**初步結論（待更嚴謹的母語者驗證確認）**：`speecht5_tailo_via_taibun`目前不足以
取代neurlang，維持`Conditional fallback`（備援選項）而非升級成主力候選。
是否值得投入Phase 2/3（改善G2P、換一個真正的台語語者embedding）取決於之後
有沒有更急迫的理由需要第二個TTS選項——目前neurlang還沒有已知的重大缺陷，
優先度不高。

### 追加驗證：換成TLPA數字調格式，沒有解決問題

開發者發現一個線索：早期用手打數字調羅馬字測試（例如`Gua2 su1-iau3 lim1 tsui2`）
時「除了音調不準，唸得還可以」，但taibun預設輸出的是Unicode符號標調（例如
`Guá su-iàu lim tsuí`），聽起來「最爛」。兩者的系統性差異只有標調符號 vs
數字，研判checkpoint訓練時可能用的是TLPA數字調格式而非Unicode符號調格式。

taibun剛好支援輸出TLPA格式（`Converter(system="TLPA")`），輸出跟手打版本幾乎
一致（`Gua2 su1 iau3 lim1 cui2.`），改用這個格式重新合成同樣6句，開發者再聽
一次——**結論是「不太行」，換格式沒有解決問題**。

這代表原本的假設（標調格式不match是主因）不成立，或至少不是主要瓶頸。
**真正的瓶頸回到最初的判斷：checkpoint本身規模小（0.1B、社群熱度低）+
用非台語語者的embedding佔位，這兩個結構性問題不是換個G2P輸出格式能解決的。**

這次的追加驗證也順便展示了 benchmark runner 的價值：改一個frontend參數、
重跑script、換一批音檔比較，整個循環只要幾分鐘，不用重新寫測試邏輯——
這正是當初建這套框架的目的。

**最終結論**：`speecht5_tailo_via_taibun`維持`Conditional fallback`，不再
投入嘗試調整G2P細節（標調格式已證明不是問題所在）。要讓這個候選變得可用，
下一個该做的事情是換掉speaker embedding（找真正的台語語者xvector或重新訓練），
而不是繼續在taibun的參數上打轉；但目前沒有急迫理由投入，維持擱置。

### 完整證據鏈與問題分層

```text
漢字直接輸入近乎靜音
→ 加入 taibun 後可正常出聲
→ 更換 Tâi-lô／TLPA 數字調格式仍無明顯改善
→ 排除輸入格式是主要品質瓶頸
→ 問題收斂到 checkpoint 容量與 speaker embedding
```

這代表要把「這個候選能不能用」拆成兩個獨立的問題看：

- **可發聲性問題**（Speakability）：Hanji→羅馬字 frontend 已經解決，taibun
  證明有效，這一層可以視為已解決
- **語音品質問題**（Quality）：仍受 0.1B checkpoint 能力本身、以及非台語
  語者 speaker embedding 限制，這一層還沒解決，而且已知不是靠調G2P能解的

`Conditional fallback` 是正確的分類，不是`rejected`——因為整條pipeline已經
能運作，只是輸出品質目前不足，繼續調G2P的邊際效益已經證明很低。

### 之後重新啟用時的優先順序

1. 用真正台語語者的乾淨參考音訊建立 speaker embedding（取代目前
   cmu-arctic-xvectors的英語語者佔位）
2. 確認 embedding extractor 跟 checkpoint 訓練時用的方法一致（不一致的
   extractor可能導致embedding空間對不上，即使語者是對的也沒用）
3. 換embedding後如果還是差，才評估用台語語音重新fine-tune SpeechT5
4. 最後才回頭檢查少數G2P錯誤，不要再把整體品質問題歸因於羅馬字格式
   （這輪已經驗證過格式不是主因）

## MERaLiON-OmniVoice-Hokkien-TTS 實測（2026-08-02）

裝套件過程再踩到一次版本衝突：`omnivoice`要求`transformers>=5.3.0`，
neurlang用的`coqui-tts`要求`transformers<5`，兩者不能在同一個venv session
共存——測試時用「先產生好的neurlang音檔」當voice clone參考，不在同一個
process裡同時import兩個套件，繞過這個衝突（正式要並用兩個模型，需要拆成
兩個venv或兩個獨立process）。

### 測試1：Voice cloning能不能模仿neurlang現有的聲音

用一段既有的neurlang輸出音檔（5.5秒，resample到16kHz）當`ref_audio`，
建立voice clone prompt，生成同樣3句話跟「用模型內建參考語音」的版本對照。
**開發者實際聽過，結論「蠻像的」**——voice cloning成功讓輸出聲音貼近
現有的neurlang語者，這代表如果之後要混用兩個TTS模型，不用忍受兩種完全
不同的音色。

### 測試2：擴大到10句「不在200句測試集裡」的新句子（來自safety-critical分析那批）

同樣用neurlang聲音複製，全部10句都成功生成，沒有crash。

### 意外發現：似乎會自動對難詞做中文code-switch

開發者聽過這批音檔後回報：**部分句子裡「比較難的字」（例如「輪椅」）會自動
用中文發音唸出來，不是硬套台語腔**。這如果屬實，代表MERaLiON可能從訓練
資料（新加坡福建話本來就常有中文/馬來語/英語code-switching，demo範例裡
就有「我 suka 食紅豆冰」這種例子）裡自然學到「難詞退回中文發音」這個行為，
不需要我們自己刻意做protected token或音檔拼接工程。

**這正好是稍早討論的「不會念就用中文念」的需求**——如果MERaLiON真的穩定
有這個行為，代表這個方向比手動拼接macOS `say`語音（`scripts/code_switch_tts.py`
那個陽春原型）更值得投入，因為是同一個模型/同一個語者一次生成，不用處理
兩種引擎銜接的問題。

**還沒確認的細節**：哪些字會觸發code-switch（真的是「難字」還是隨機的？）、
觸發比例多高、是不是跟voice cloning有關（用內建語音會不會也一樣）。需要
更系統性的測試才能下定論，目前只是聽感觀察。

### 也發現的問題：斷句在詞中間

部分句子聽起來「一個詞中間被斷開」，開發者形容「聽起來很怪」。具體是哪句
哪個詞、是否跟特定標點或詞彙有關，還沒有精確定位（問了但沒有得到具體回覆），
先記錄現象存在，之後有機會再具體定位。

### 初步結論

MERaLiON從原本「新加坡腔、當對照組」的定位，**因為voice cloning效果好+
可能自帶code-switch行為，重新評為積極候選**，優先度提升。下一步：

- [ ] 系統性測試code-switch行為的觸發條件（哪些詞會、哪些不會）
- [ ] 定位斷句問題的具體觸發條件
- [ ] 評估MERaLiON-3-Public-Licence條款是否允許研究/後續商用
- [ ] 如果code-switch行為穩定，重新評估是否要投入「兩個TTS引擎混用」
      還是直接讓MERaLiON取代/輔助neurlang

## 系統設計原則（這次的實測讓這件事變得明確）

> **TTS模型的輸入文字體系必須和上游翻譯輸出一致；否則模型音質再好，也會多出一個
> 高風險的語言前處理模組。** 選TTS候選時，「native input format跟我們的pipeline
> 相不相容」跟「音質好不好」同樣重要，甚至該排在音質評分之前先篩過一輪——不相容
> 的候選不管音質多好，都要先加計一整層G2P的開發與維護成本。

## 對本研究的意義

即使不實測，MediaTek論文的「59.2%台語發音準確率」這個數字本身就很有參考價值：
這代表就算用CosyVoice2這種較強的LLM-based TTS架構、餵進上萬小時合成資料，
台語發音準確率還是卡在六成左右。相較之下，我們目前用的 neurlang VITS
雖然架構簡單很多，但因為用 pygoruut 做規則式音標轉換（不是端到端學習發音），
在小規模主觀測試中反而没出現明顯的錯誤讀音問題。這提示一件事：**對台語這種
書寫系統不統一、聲調規則明確的語言，「規則式音標轉換+成熟TTS」可能比
「端到端LLM學發音」更穩定，這點會在正式跑完三個模型的100句比較後才能下定論。**
