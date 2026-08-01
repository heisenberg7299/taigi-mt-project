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
| [MERaLiON-OmniVoice-Hokkien-TTS](https://huggingface.co/MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS) | 可下載，未實測 | MERaLiON-3-Public-Licence（自訂條款，需另外詳讀是否允許研究/商用） | 0.8B參數，~2.7GB，支援聲音克隆 | 待確認（`generate(text=..., language="nan")`，文件沒明講吃漢字還是羅馬字） | 待實測後才知道 | **要注意的是這是新加坡福建話（Singapore Hokkien），不是台灣台語**——兩者同源但用詞、部分腔調有差異，混用可能被台灣母語者聽出「怪腔怪調」。自報指標：WER 0.33（不算低）、自然度8.4/10、DNSMOS 3.13/5 |
| Curiousfox / wenxinkoh06 的 `speecht5_tailo-hokkien` 系列 | **已實測，確認不能直接用（見下方細節）** | MIT | SpeechT5微調（0.1B），體積小 | Tâi-lô羅馬字 / 英文（漢字幾乎完全失效，見下） | Hanji→Tâi-lô G2P（目前專案沒有） | 命名用「tailo」明確針對台灣台語，授權最寬鬆 |
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

## 建議下一步優先順序（更新：改用淘汰漏斗式排序，不要在SpeechT5繼續投入）

1. **優先測能直接吃台語漢字的模型** — 避免多一層G2P依賴，`neurlang` VITS目前是唯一
   一個符合這個條件並已驗證的候選
2. **MERaLiON-OmniVoice-Hokkien-TTS** — 先確認它實際吃的是漢字還是羅馬字（目前文件
   沒寫清楚），是漢字才值得深測；是羅馬字則跟speecht5同樣先擱置G2P投入
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
