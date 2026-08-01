# 平行語料資料格式標準

所有中文—台語平行資料統一存成以下 JSON Lines 格式，欄位缺值填 `null`，不要留空字串。

```json
{
  "id": "medical_0001",
  "zh": "請幫我叫護理師",
  "nan_han": "請共我叫護理師",
  "tailo": null,
  "intent": "CALL_NURSE",
  "domain": "hospital",
  "source": "manual",
  "license": "project_internal",
  "verified": false
}
```

## 欄位說明

| 欄位 | 說明 | 必填 |
|---|---|---|
| `id` | 唯一識別碼，格式 `{domain}_{4位數字}` | 是 |
| `zh` | 中文原文（繁體） | 是 |
| `nan_han` | 台語漢字（教育部推薦用字優先） | 是 |
| `tailo` | 台羅拼音，供 TTS 使用，沒有先留 null | 否 |
| `intent` | 意圖標籤（大寫底線分隔，如 `CALL_NURSE`），非意圖類資料留 null | 否 |
| `domain` | 來源領域，如 `hospital` / `daily` / `news` | 是 |
| `source` | 資料來源，如 `manual` / `moe_dictionary` / `icorpus100` / `taigispeech` | 是 |
| `license` | 授權，如 `cc-by-4.0` / `cc-by-nc-4.0` / `project_internal` | 是 |
| `verified` | 是否經母語者核對過 | 是 |

## 內部表示原則

- 主要訓練/比對目標欄位：`nan_han`（教育部推薦台語漢字）
- 不同書寫系統（POJ、漢羅、非推薦用字）匯入時一律先正規化轉換成 `nan_han`，不要讓多種書寫系統混在同一欄位裡
- 資料切分（train/valid/test）依照「影片/說話者/主題/來源」切，不可用隨機打亂整批句子的方式切，避免同一場景高度相似句子同時出現在 train 和 test

## 授權分類（決定資料能不能進最終訓練集）

- `internal_ok`：可用於模型訓練與微調
- `nc_only`：僅供研究/非商業（如 iCorpus-100、NUTN-Whisper），**不可用於將來要商用的正式模型**
- `review_needed`：授權條款不明確，使用前需人工確認（如國教院語料庫各子語料）
