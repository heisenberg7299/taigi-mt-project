# 階段4：TTS 模型調研（候選盤點，尚未全部實測）

日期：2026-08-01

目標：找出除了目前在用的 `neurlang/coqui-vits-suisiann-minnan-hokkien` 之外，
還有哪些免費、可本機部署的台語 TTS 值得拿來跟同一份100句測試集比較。

## 候選清單

| 模型 | 狀態 | 授權 | 規模 | 備註 |
|---|---|---|---|---|
| `neurlang/coqui-vits-suisiann-minnan-hokkien` | **已驗證可用（目前主力）** | CC-BY-SA-4.0 | VITS，CPU RTF~0.11-0.13 | 已產生200句候選音檔，正在收母語者回饋 |
| MediaTek BreezyVoice-Taigi | **查無公開權重，無法實測** | 論文未揭露 | CosyVoice2微調，~10,000小時合成資料 | 論文（[arXiv:2603.19259](https://arxiv.org/html/2603.19259)）有報告數字但 HuggingFace 上找不到對應模型檔；已搜尋 MediaTek-Research 全部27個模型跟關鍵字「Taigi」「BreezyVoice」都沒有這個repo。**重要發現**：論文自報的「台語發音準確率只有59.2%」——連 MediaTek 專門投入的模型都只有六成不到的道地發音率，這代表台語TTS本身難度很高，不是我們資源不夠的問題 |
| [MERaLiON-OmniVoice-Hokkien-TTS](https://huggingface.co/MERaLiON/MERaLiON-OmniVoice-Hokkien-TTS) | 可下載，未實測 | MERaLiON-3-Public-Licence（自訂條款，需另外詳讀是否允許研究/商用） | 0.8B參數，~2.7GB，支援聲音克隆 | **要注意的是這是新加坡福建話（Singapore Hokkien），不是台灣台語**——兩者同源但用詞、部分腔調有差異，混用可能被台灣母語者聽出「怪腔怪調」。自報指標：WER 0.33（不算低）、自然度8.4/10、DNSMOS 3.13/5 |
| Curiousfox / wenxinkoh06 的 `speecht5_tailo-hokkien` 系列 | **已實測，確認不能直接用（見下方細節）** | MIT | SpeechT5微調（0.1B），體積小 | 命名用「tailo」明確針對台灣台語，授權最寬鬆 |
| `chen778560489/coqui-vits-suisiann-minnan-hokkien` | 略過 | 同neurlang | - | 看起來是 neurlang 模型的 fork/鏡像，非獨立模型，跳過 |

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

### 對本專案的影響

我們目前整個pipeline設計是以**台語漢字（`nan_han`）為主要表示法**（見`data/schema.md`），
`tailo`欄位目前全專案沒有任何一筆資料填過。要用這個模型，必須先有一個可信賴的
「台語漢字 → Tâi-lo」轉換層——這正好會撞回我們已經證實過的老問題（純辭典查表轉換
不可靠，見PLAN.md「今天的實測教訓」第4點），只是方向反過來、換了一個要解決的子問題。

**先不投入做這層轉換**，除非之後有更明確的理由需要多一個TTS選項比較。

## 建議下一步優先順序（更新）

1. ~~`speecht5_tailo-hokkien`~~ — 已測完，卡在漢字輸入無法使用，擱置
2. **MERaLiON-OmniVoice-Hokkien-TTS**：模型較大（2.7GB）、授權條款需要先讀清楚，且是新加坡腔——測試目的主要是「即使腔調有落差，聽起來是否比逐字亂讀好」，用來當作極端對照組，不是候選部署對象
3. BreezyVoice-Taigi 目前無法測（沒有公開權重），只能繼續追蹤 MediaTek 之後會不會釋出

## 對本研究的意義

即使不實測，MediaTek論文的「59.2%台語發音準確率」這個數字本身就很有參考價值：
這代表就算用CosyVoice2這種較強的LLM-based TTS架構、餵進上萬小時合成資料，
台語發音準確率還是卡在六成左右。相較之下，我們目前用的 neurlang VITS
雖然架構簡單很多，但因為用 pygoruut 做規則式音標轉換（不是端到端學習發音），
在小規模主觀測試中反而没出現明顯的錯誤讀音問題。這提示一件事：**對台語這種
書寫系統不統一、聲調規則明確的語言，「規則式音標轉換+成熟TTS」可能比
「端到端LLM學發音」更穩定，這點會在正式跑完三個模型的100句比較後才能下定論。**
