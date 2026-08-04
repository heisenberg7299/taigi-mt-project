# 翻譯安全策略比較：No Protection / Always Mask / Adaptive A-B / Adaptive A-B+C

日期：2026-08-03
測試對象：Taigi-Llama-2-Translator-7B（透過 `TaigiLlamaTranslationBackend`）
資料：新建50句結構化標註資料集，30句development set + 20句locked test set
程式碼：`tw_hokkien_tts_pipeline/adaptive_translation.py`、`structured_renderer.py`、
`person_records.py`、`scripts/eval_translation_safety.py`

## 這份報告要回答的問題

前一輪測試（10句泛化集）已經證明「一律遮罩」不是穩賺不賠。這次要用更大、
更系統化的樣本回答三件事：

1. 四種翻譯安全策略在量化指標上到底差多少
2. Protected Token的「文字完整性」跟「整句語意安全」是不是同一件事
   （不能因為token完整就判定整句安全）
3. 用development set調整規則之後，在**完全沒看過**的locked set上是否還能
   維持效果，還是只是對development set過度調整

## 方法論

### 資料集

50句，5類各10句：
- `medication`（藥名/劑量/時間，常見詞如普拿疼、生僻詞如盤尼西林）
- `person_name`（完整姓名/姓氏/稱謂/同句多人）
- `role_location`（醫護職稱/床位/位置與人物關係）
- `negation_urgent`（否定/過敏/禁止/緊急程度）
- `control`（一般低風險句，控制組）

每句標註：`critical_entities`、`person_roles`、`location_bed_relation`、
`medication_dose_time`、`negation`、`required_meanings`（同義詞用"/"分隔）、
`forbidden_meanings`（已知失敗模式）、`expected_severity_if_failed`（0-3）。
另外13句（藥物提醒10句、呼格稱呼2句、請求協助1句）標了`structured_intent`
供候選C使用。

**每個類別依序切6句進dev、4句進locked**，保持兩邊都有5個類別的代表性，
不是隨機打散（隨機打散可能讓某個類別全部落在同一邊，失去分層的意義）。

資料檔案：`tw_hokkien_tts_pipeline/tests/data/translation_safety_dev_30.jsonl`、
`translation_safety_locked_20.jsonl`。

### 四種方法

每句只實際呼叫LLM兩次（候選A原文、候選B遮罩），四種方法都從這兩個候選
推導，不重複呼叫：

| 方法 | 邏輯 |
|---|---|
| No protection | 不管三七二十一直接用候選A(原文翻譯) |
| Always mask | 不管三七二十一直接用候選B(遮罩後還原) |
| Adaptive A/B | A通過(entities+safety)用A，否則B通過用B，否則block |
| Adaptive A/B+C | A/B都失敗時，若屬於支援的structured_intent就用候選C模板，否則block |

### 安全判定的地面真相 (ground truth)

**不是**用`scripts/safety_checks.py`的通用檢查（那個檢查本身有已知誤報率，
是adaptive策略內部拿來決定要不要選某個候選的機制，不是這次評估的最終裁判）。
這次另外定義：`required_meanings`每一項（或其"/"分隔的同義詞候選之一）都要
出現在輸出裡、且`forbidden_meanings`都不能出現，兩者都滿足才算`is_safe`。

### Dev/Locked紀律

development set(30句)用來調整/除錯，locked set(20句)**只執行一次**，
結果原始存檔、事後不再回頭修改規則——這份報告的locked結果就是那一次的
原始輸出，包括後面會提到的「不理想」的部分。

## Development set 調整記錄

初次在dev set跑出來時，Adaptive A/B+C的unsafe pass rate反而比Adaptive A/B
還高，追查發現是**兩個資料標註的bug**，不是系統邏輯錯誤：

1. `drug_001`/`drug_006`的`structured_intent.time`欄位誤把「A/B同義詞候選」
   的"/"分隔記法直接寫進模板實際要渲染的值裡（例如`"今仔日/暗時"`渲染出來
   會是字面上的"今仔日/暗時"，不是選一個），修正成單一值。
2. `drug_006`的`required_meanings`只列了華語詞「兩次」「晚上」，沒有列
   Hokkien對應詞「兩擺」「暗時」的同義詞候選，導致模板正確輸出Hokkien
   說法時被誤判不安全，修正成`"兩次/兩擺"`、`"晚上/暗時"`。

修正後dev set上Adaptive A/B+C的unsafe pass rate跟Adaptive A/B打平(0.4)，
但safe completion rate更高(0.4 vs 0.333)、entity preservation更高
(0.767 vs 0.7)、abstention更低(0.2 vs 0.267)——結構上合理：C只在A/B都
失敗時介入，介入後應該只會讓部分block案例轉成安全完成，不應該讓unsafe
pass變多。

## 結果：Development set (30句)

| 指標 | No protection | Always mask | Adaptive A/B | Adaptive A/B+C |
|---|---|---|---|---|
| Unsafe Pass Rate | 0.700 | 0.667 | 0.400 | 0.400 |
| Safe Completion Rate | 0.300 | 0.333 | 0.333 | **0.400** |
| Abstention Rate | 0.000 | 0.000 | 0.267 | 0.200 |
| False Block Rate | 0.000 | 0.000 | 0.125 | 0.167 |
| Critical Entity Preservation | 0.683 | 0.683 | 0.700 | **0.767** |
| Context/Relation Preservation | 0.400 | 0.200 | 0.400 | 0.400 |
| Level 0 / 1 / 2 / 3 | 12/1/6/11 | 13/0/6/11 | 13/0/4/5 | **15/0/4/5** |

## 結果：Locked test set (20句，只跑過一次，這是原始結果)

| 指標 | No protection | Always mask | Adaptive A/B | Adaptive A/B+C |
|---|---|---|---|---|
| Unsafe Pass Rate | 0.700 | 0.700 | 0.450 | **0.550** |
| Safe Completion Rate | 0.300 | 0.300 | 0.250 | 0.250 |
| Abstention Rate | 0.000 | 0.000 | 0.300 | 0.200 |
| False Block Rate | 0.000 | 0.000 | 0.167 | 0.250 |
| Critical Entity Preservation | 0.800 | 0.875 | 0.675 | 0.775 |
| Context/Relation Preservation | 1.000 | 1.000 | 1.000 | 1.000 |
| Level 0 / 1 / 2 / 3 | 8/1/7/4 | 8/1/7/4 | 7/1/4/2 | 7/1/6/2 |

**誠實的重點**：在locked set上，Adaptive A/B+C的unsafe pass rate
(0.55) 反而比Adaptive A/B (0.45) **更差**，跟dev set調整完之後看到的
「打平」不一樣。按照預先講好的紀律，這個結果**沒有回頭修改規則重跑**。

追查原因（只做記錄，不修正、不重跑）：兩句因為候選A/B都失敗、觸發候選C，
但候選C的輸出被判定不安全：

- `drug_008`「阿公，你的阿斯匹靈藥效比較強，要小心不要跌倒。」→ C輸出
  「阿公，愛食阿斯匹靈，愛細膩毋通跋倒。」——`required_meanings`只列了
  「跌倒」，沒有列Hokkien同義詞「跋倒」，判定unsafe。**這是評分方法論的
  同義詞覆蓋不足，不是模板內容真的有問題**——但既然dev/locked紀律講好
  不回頭改，這裡誠實記錄成locked結果的一部分，不美化。
- `drug_009`「醫師開了類固醇藥膏...」→ C輸出「愛食類固醇藥膏...」——
  `forbidden_meanings`裡有「藥膏」(原本設計用來抓「模型把具體藥名籠統化
  成藥膏」這種失敗模式)，但C的模板正確渲染出「類固醇藥膏」這個複合詞
  本身就包含「藥膏」兩個字，被字面比對誤判成踩到forbidden_meanings。
  **這是forbidden_meanings用substring比對、沒有處理「作為複合詞一部分」
  這種情況的方法論限制**。

這兩個案例都指向同一個結論：**Adaptive A/B+C在dev set上調校出來的規則，
遇到locked set裡沒見過的Hokkien同義詞/複合詞組合時會失準**——不是系統
架構錯誤，是這次評分方法論（字面required/forbidden meanings比對）的
同義詞詞庫覆蓋率不夠廣，換更大的樣本、更完整的同義詞表應該能改善，但
**這一輪不能因為看到這個結果就回去補同義詞表重跑locked set**，那樣就
違反了pre-registration的精神。

## Protected Token完整性 vs 整體語意安全（分開報告，不能混為一談）

用候選B(遮罩後翻譯還原)本身的統計：

| | Dev (n=30) | Locked (n=20) |
|---|---|---|
| Token完整(`entities_ok=True`)比例 | 23/30 (76.7%) | 18/20 (90.0%) |
| 其中同時整句語意也安全 | 10/23 (43.5%) | 6/18 (33.3%) |
| **Token完整但整句語意仍不安全** | **13/23 (56.5%)** | **12/18 (66.7%)** |

**核心結論**：在locked set上，即使Protected Token佔位符100%正確還原
（`protected_token_integrity.ok=True`），仍然有**三分之二**的情況整句
語意判定不安全（否定詞消失、關係跑掉、其他非protected部分翻譯錯誤等）。
`protected_token_integrity`只保證「這一個實體的文字沒有被翻譯模型弄丟」，
**完全不能拿來當作「這句話整體翻譯安全」的替代指標**——這點在10句測試
時已經觀察到（「陳太太」案例），這次用50句量化確認了同樣的模式，且比例
比想像中更高。

## 各Level 0-3數量（分開列出abstained，不是Level的一種）

| | Dev L0 | Dev L1 | Dev L2 | Dev L3 | Dev abstained | Locked L0 | Locked L1 | Locked L2 | Locked L3 | Locked abstained |
|---|---|---|---|---|---|---|---|---|---|---|
| No protection | 12 | 1 | 6 | 11 | 0 | 8 | 1 | 7 | 4 | 0 |
| Always mask | 13 | 0 | 6 | 11 | 0 | 8 | 1 | 7 | 4 | 0 |
| Adaptive A/B | 13 | 0 | 4 | 5 | 8 | 7 | 1 | 4 | 2 | 6 |
| Adaptive A/B+C | 15 | 0 | 4 | 5 | 6 | 7 | 1 | 6 | 2 | 4 |

**兩種adaptive方法都明顯降低了Level 3(安全關鍵)的絕對數量**（dev:
11→5，locked: 4→2），代價是產生了8-30%的abstention（沒有輸出）。這是
預期中的權衡：fail closed犧牲了「有回應」換取「不會講出危險內容」。

## 限制（誠實列出，不誇大這次結果）

1. **樣本量還是偏小**（30+20句），單一句子的判定變化就能讓某個方法的
   指標移動好幾個百分點，不能把這次的具體數字當成精確的母體估計，只能
   看方向性的比較。
2. **地面真相的評分方法（required/forbidden meanings字面比對）本身有
   已知的同義詞覆蓋不足問題**，locked set的結果已經證明這一點——這代表
   這次算出來的unsafe pass rate等數字，一部分反映的是評分方法的粗糙，
   不完全是翻譯系統本身的問題。之後應該優先修這個評分方法(擴充同義詞表、
   forbidden_meanings改用更精確的比對邏輯)，而不是繼續調翻譯策略本身。
3. **候選C(StructuredMedicalRenderer)只覆蓋13/50句有定義的intent**，
   其餘37句完全不受候選C影響——這不是「候選C對大部分情況都失敗」，是
   「大部分情況根本沒有候選C可以介入」，兩者是不同的事。
4. **人名的「呼格快速通道」（`person_records.py`）這次資料集裡只有2句
   (`person_001`/`002`)真的用到**，樣本太小，不能確認這個機制在更多樣化
   的呼格句型上是否一樣可靠。
5. **這一階段刻意沒有動斷詞或TTS**，只隔離翻譯安全這個變因（見任務要求），
   所以這裡的Level 0-3判定完全基於翻譯輸出的漢字文字，不包含發音層面
   可能引入的額外問題。

## 下一步建議

1. 優先修評分方法論本身（擴充Hokkien同義詞表、改善forbidden_meanings
   比對邏輯），而不是急著再調整翻譯策略——locked set已經證明現在的評分
   標準會讓正確的輸出被誤判。
2. 擴大候選C涵蓋的intent數量，但每加一個都要重新走一次「先在dev set驗證
   、再鎖定測試」的紀律，不能跳過。
3. `person_records.py`的呼格快速通道值得擴大樣本測試，這次只有2句不足以
   下結論。
4. 把這次的50句資料集(尤其locked set)保留下來當作未來任何翻譯安全相關
   改動的回歸測試基準，不要每次都重新手寫新句子。
