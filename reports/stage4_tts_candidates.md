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
| Curiousfox / wenxinkoh06 的 `speecht5_tailo-hokkien` 系列 | 可下載，未實測 | MIT | SpeechT5微調，體積小 | 命名用「tailo」明確針對台灣台語，授權最寬鬆。但下載數僅個位數、社群熱度低，品質未知，風險是可能訓練資料量不足、發音不穩定。CP值高，值得優先做快速實測（成本低） |
| `chen778560489/coqui-vits-suisiann-minnan-hokkien` | 略過 | 同neurlang | - | 看起來是 neurlang 模型的 fork/鏡像，非獨立模型，跳過 |

## 建議下一步優先順序

1. **`speecht5_tailo-hokkien`**（Curiousfox/wenxinkoh06）：MIT授權、體積小、跟目前架構(VITS)不同種可以互相對照，成本最低，先測
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
