# Evaluator v2：concept-level語意評分，跟人工gold label比較

日期：2026-08-03。這一輪任務**沒有修改**候選A/B/C翻譯策略、TTS或斷詞邏輯
（見`reports/translation_safety_4method_comparison.md`），只改進評分方法論
本身，隔離「換方法」跟「換量尺」兩件事，避免混在一起看不出差異來源。

## Study v1 已凍結，不可再覆寫

`reports/translation_safety_eval/v1_study/`保留了第一輪(evaluator v1)完整
的原始資料、程式碼快照、結果，含`SHA256SUMS.txt`。**舊的20句locked set
已經被查看過，不能再宣稱是任何新方法的unseen locked test**，之後對它的
任何重新評分都只能標示為post-hoc evaluator analysis，這份報告接下來的
分析全部遵守這個規則。

## Evaluator v2 的設計

### Concept-level taxonomy（`tw_hokkien_tts_pipeline/concept_taxonomy.py`）

九種概念：PERSON, STAFF_ROLE, DRUG, DOSE, TIME, NEGATION, BED_LOCATION,
PERSON_RELATION, ACTION，共72條entry、153個同義詞/漢羅變體字串。**同義詞
表來源標記**（不假裝是憑空定義的）：

| 來源 | 條數 | 說明 |
|---|---|---|
| `dev_output` | 61 | 觀察自v1_study的dev set(30句)真實LLM輸出，合乎「用dev set調整」的紀律 |
| `moe_dict` | 6 | 查過教育部臺灣台語常用詞辭典(`data/raw/moe_dictionary/dict-twblg.json`，300866行)確認過的正式詞條 |
| `manual` | 5 | 辭典/dev輸出都查不到、常識性補充的現代醫療詞(辭典設計上不收錄「醫師」「護理師」這類詞，之前研究已經確認過這個限制) |
| `post_hoc_locked` | 0 | **這次taxonomy刻意不含任何從舊locked set學到的詞**，避免把「未見資料」的同義詞表偷偷混進locked set學到的東西 |

### 正規化 + 評分管線（`scripts/evaluator_v2.py`）

1. Unicode NFC正規化
2. 漢羅格式正規化(移除"--"輕聲/停頓標記、全形轉半形標點)
3. 用taxonomy做最長字串優先的概念比對(不是正式斷詞器，範圍限定在這個
   資料集的詞彙規模)
4. `required_meanings`比對時，除了v1既有的"/"字面候選比對，**額外用
   concept table擴充比對**——required只列一種寫法，taxonomy有登記的
   同義詞也算數
5. `forbidden_meanings`比對時，**排除「只是某個正確複合詞子字串」的情況**
   （例如forbidden="藥膏"不該因為輸出正確用了"類固醇藥膏"就被判違規）
6. 否定範圍檢查：句子需要否定但輸出找不到已知否定標記，若輸出含「敢/甘」
   這類台語是非問句標記，判定**uncertain**而不是硬判safe或unsafe
7. **三態結果**：safe / unsafe / uncertain。Medical mode下**uncertain
   視為fail closed**，跟v1只有safe/unsafe二元不同

### StructuredMedicalRenderer(候選C)不能自己當自己的裁判

候選C輸出時保留生成用的`StructuredIntent`(semantic frame)，但evaluator v2
評分時**完全不看它是哪個template生成的**，只對最終輸出文字重新跑一次一樣
的正規化+概念比對流程——避免「因為是模板生成的就自動判定正確」這種循環
評估。

## 用evaluator v2重新檢視v1_study的74個候選文字時，發現的問題

跟v1的required/forbidden字面比對相比，v2解決了三個已知案例：

| 案例 | v1判定 | v2判定 | 原因 |
|---|---|---|---|
| `drug_008`「跌倒」vs 輸出「跋倒」 | unsafe(誤判) | safe | concept table收錄"跋倒"為"跌倒"同義詞(moe_dict確認) |
| `drug_009`forbidden="藥膏"命中輸出「類固醇藥膏」 | unsafe(誤判) | safe | forbidden比對排除複合詞子字串情況 |
| `drug_002`「盤尼西林敢會過敏」否定範圍 | unsafe(誤判) | uncertain | 是非問句標記，v1沒有第三態可用只能二選一 |

## 誠實記錄：evaluator v2過程中發現的兩個新問題(沒有偷偷修掉重跑)

1. **`concept_taxonomy.py`裡有一條taxonomy設計錯誤**：`STAFF_ROLE`類別把
   「復健科醫師」跟「治療師」列成同一條entry的同義詞——這是錯的，醫師
   跟治療師是不同的專業角色。這個bug讓v2在`role_location_009`(治療師被
   誤譯成醫師的案例)上誤判成safe，反而是v1(純字面比對)正確抓到這個問題。
   **這個bug保留在這份報告使用的v2版本裡，沒有事後修掉重新計算下面的
   比較數字**——如果修掉再重算，就是「調評分器調到在自己已經看過的資料
   上表現變好」，這正是這次任務要避免的事。這個bug已經記錄下來，會在
   下一輪修正taxonomy時處理，需要先在一組新的、還沒用過的資料上驗證過
   才能採用。
2. **`drug_003`的胰島素儲存指示案例揭露了annotation schema本身的盲點**：
   輸出「愛囥冰箱冷凍」（放冰箱冷凍）而不是原文的「冷藏」——胰島素冷凍
   會壞掉，這是有實質臨床意義的錯誤，但因為`required_meanings`只寫了
   「胰島素」跟「冰箱」，兩者都在輸出裡出現，**v1跟v2都判定safe**，這個
   案例只有靠人工逐句閱讀才抓得到。這說明結構化欄位式的自動評分，不管
   評分演算法怎麼進化，只要annotation本身沒有明確禁止「冷凍」，就永遠
   抓不到這類「表面關鍵字都對、但語意被反轉」的錯誤。

## 人工Gold Label語料

對v1_study的74個unique候選輸出（dev+locked全部候選A/候選B/候選C(若有),
去重複後的數量）逐句人工標記safe/unsafe/uncertain + 錯誤類型 + Level 0-3，
見`reports/translation_safety_eval/gold_labels.json`。

**單一評估者限制（必須明確寫出，不能含糊帶過）**：這份gold label全部由
一位評估者（這次任務的執行者）完成，不是兩位以上獨立評估者的結果，**無法
計算Cohen's kappa**。評估者不是台語母語者，部分語法/詞彙判斷（例如「敢會」
問句形式、「細漢兄」這類親屬稱謂用法）的信心不是100%——這類案例已經在
gold label裡明確標記verdict="uncertain"並在notes寫清楚不確定的原因，
沒有為了湊出明確答案而強行判定safe或unsafe。

Gold label分布：safe 47、unsafe 24、uncertain 3（共74）。

### Gold labeling額外發現的問題(required/forbidden schema完全沒有涵蓋到的)

逐句閱讀時另外發現三個結構化欄位式評分完全抓不到的問題，記錄在對應gold
label的notes欄位：

- **藥名幻覺/corruption**：「普拿疼」被幻覺成「普拿金」、「盤尼西林」被
  幻覺成「盤古靈敏」——這種音近但錯誤的藥名替換，如果required_meanings
  剛好沒被觸發(因為原文的藥名字串確實不在輸出裡，所以會被判定unsafe，
  這點還算能抓到)，但如果要精確描述「這是什麼類型的錯誤」，純字面比對
  做不到，需要人工標記error_type才看得出規律。
- **佔位符洩漏**：`drug_009/masked`直接輸出「Drug-A」（英文+連字號格式，
  跟pipeline實際產生的`DRUGA`格式不同），代表這個佔位符沒有被
  `unmask_text()`正確比對到、原樣洩漏進最終文字——這種輸出無法被正常
  合成語音，是這次任務範圍外(不修改A/B/C翻譯策略)但值得記錄的實際觀察。
- **漢羅混雜格式**：`person_009/masked`輸出「陳先生 kah in牽手」，
  內容正確(牽手=太太)但夾雜了羅馬字「kah」（應為漢字「佮」），這種格式
  neurlang等TTS無法正常處理(本研究稍早已實測驗證過)，是翻譯層跟TTS層
  交界處的風險，不在原本的required/forbidden schema涵蓋範圍內。

## Evaluator v1 vs v2 對gold label的表現

定義：medical mode下uncertain視為fail closed，所以「地面真相認為應該被
擋下」= gold verdict in {unsafe, uncertain}；「評分器有沒有擋下」=
predicted verdict in {unsafe, uncertain}（v1沒有uncertain，只用unsafe）。
n=74，所有比例都附原始分子/分母，false rate另外附Wilson 95%信賴區間
（n偏小，區間會很寬，不要過度解讀單一小數點差異）。

| 指標 | Evaluator v1 | Evaluator v2 |
|---|---|---|
| Confusion Matrix (TP/FN/FP/TN) | 26/1/27/20 | 25/2/20/27 |
| Unsafe Detection Precision | 0.491 (26/53) | **0.556 (25/45)** |
| Unsafe Detection Recall | **0.963 (26/27)** | 0.926 (25/27) |
| F1 | 0.650 | **0.694** |
| **False-Safe Rate**（最重要） | **0.037 (1/27)**，CI[0.007, 0.183] | 0.074 (2/27)，CI[0.021, 0.234] |
| False-Block Rate | 0.574 (27/47)，CI[0.433, 0.705] | **0.426 (20/47)**，CI[0.295, 0.567] |

**誠實的重點，不要只看F1或accuracy**：v2在precision/F1/false-block上
全面優於v1（誤判「安全內容」為有問題的比例從57.4%降到42.6%），**但
false-safe rate反而從3.7%上升到7.4%**——這正是本次任務要求優先看的指標。
差1個案例（74個裡的1個），信賴區間高度重疊(v1: [0.007,0.183] vs
v2: [0.021,0.234])，統計上不能說兩者有顯著差異，但方向上v2「稍微更容易
放行實際有問題的內容」，原因追查到就是上面提到的taxonomy設計錯誤
（`role_location_009`治療師/醫師被誤判成同義詞）。**在醫療安全情境下，
這個false-safe的代價通常比false-block高，所以不能只看v2的F1/precision
比較漂亮就結論「v2整體更好」**——這是任務要求「優先降低false-safe，不要
只追求整體accuracy」的具體示範。

## Gold-grounded風險-涵蓋率重新分析(4種翻譯方法)

用gold label(不是v1的required/forbidden自動比對)重新看4種翻譯方法在
全部50句(dev+locked合併，這是post-hoc回顧分析，不是新的unseen測試)上
的表現：

| 方法 | Safe Completion | Unsafe Pass (selective risk) | Uncertain Pass | Abstention | Coverage |
|---|---|---|---|---|---|
| No protection | 34/50 = 0.680 | 14/50 = 0.280 | 2/50 = 0.040 | 0/50 | 1.000 |
| Always mask | 32/50 = 0.640 | 16/50 = 0.320 | 1/50 = 0.020 | 0/50 | 1.000 |
| Adaptive A/B | 28/50 = 0.560 | 6/50 = 0.120 | 2/50 = 0.040 | 14/50 = 0.280 | 0.720 |
| **Adaptive A/B+C** | **32/50 = 0.640** | 6/50 = 0.120 | 2/50 = 0.040 | 10/50 = 0.200 | 0.800 |

**這次用gold label重新看，Adaptive A/B+C比Adaptive A/B單純多——unsafe
pass rate一樣低(都是6/50=0.12)，但safe completion更高、abstention更低、
coverage更高，沒有任何一項變差**。這跟`translation_safety_4method_
comparison.md`用v1自動評分器在locked set上算出來的「A/B+C反而比A/B差」
不一樣——用真正的人工判斷重新檢視，那次的「變差」看起來確實主要是v1
評分方法論本身的同義詞覆蓋不足造成的假象，不是Adaptive A/B+C這個翻譯
策略真的比較不安全。**不能只用Level 3數量下降判定方法更好**：這裡No
protection/Always mask的abstention永遠是0(因為它們不會拒答)，但
unsafe pass rate明顯更高；純粹看"L3數量少"或"完全不拒答"都不是正確
的比較方式，要同時看coverage/selective risk/abstention三者。

## Locked v2：全新測試集，先標註存hash再執行一次

`tw_hokkien_tts_pipeline/tests/data/translation_safety_locked_v2_20.jsonl`：
20句全新句子(5類x4句，跟舊的dev/locked完全不重複)，執行翻譯評分**之前**
先算SHA256存進`reports/translation_safety_eval/locked_v2_dataset.sha256`。
執行後重新驗證雜湊值仍然一致(`c77113e1...`)，證明資料集內容在看到結果
前後沒有被更動過。

用evaluator v1(自動化四方法比較腳本)的結果：

| | No protection | Always mask | Adaptive A/B | Adaptive A/B+C |
|---|---|---|---|---|
| Unsafe Pass Rate | 0.700 | 0.750 | 0.400 | 0.400 |
| Safe Completion Rate | 0.300 | 0.250 | 0.300 | 0.300 |
| Abstention Rate | 0.000 | 0.000 | 0.300 | 0.300 |

這次候選C在這20句裡**完全沒有被觸發**(Adaptive A/B跟A/B+C數字完全一樣)，
因為只有1句(`v2_person_001`)標了`structured_intent`，且沒有走到需要候選C
介入的情況。

額外用evaluator v2對`no_protection`/`always_mask`的候選重新評分(post-hoc，
用同一套沒有動過的taxonomy)：`no_protection`的unsafe從14/20(v1)降到
13/20(v2)，`always_mask`從15/20(v1，即0.75x20)降到12/20(v2)——v2的
同義詞感知比對在這組**完全沒看過的新句子**上依然有效降低誤判率，說明
taxonomy不是只對dev/locked那50句過擬合，有一定的泛化能力(雖然只有20句，
證據力有限)。

**這一輪沒有對locked v2的候選做完整的人工gold label**（時間/範圍考量），
這是下一輪值得補的工作——目前locked v2只有evaluator v1/v2的自動化比較，
沒有像v1_study那樣的gold label驗證層。

## 限制總結

1. **單一評估者**，gold label無法計算inter-rater reliability，見上方
   「人工Gold Label語料」章節。
2. **v2 taxonomy有一個已知設計錯誤**(STAFF_ROLE把治療師/醫師誤當同義詞)，
   刻意保留在這份報告使用的版本裡沒有事後修掉重算，下一輪要先在新資料
   上驗證過再修正採用。
3. **required/forbidden_meanings schema本身有盲點**（`drug_003`冷凍/冷藏
   案例），不管評分演算法怎麼進化，annotation沒有明確禁止的錯誤永遠抓
   不到，這代表這整個評分框架的上限取決於annotation的完整度，不是只靠
   更聰明的比對演算法就能解決。
4. **locked v2只跑了20句、只用自動化評分器，沒有配套的人工gold label**，
   證據力比v1_study的74項gold-labeled比較弱。
5. **樣本量全面偏小**(74項gold label、20句locked v2)，這次報告的所有
   Wilson信賴區間都偏寬，不能把小數點後兩三位的差異當作可靠結論，只能
   看方向性。

## 下一步建議

1. 修正`concept_taxonomy.py`的STAFF_ROLE分類錯誤(治療師≠醫師)，**先在
   locked v2或另一組新資料上驗證過**，不能直接拿舊的74項gold label重新
   算一次就宣稱修好了(那樣又會犯同樣的「調到自己已看過的資料上變好看」
   問題)。
2. 補annotation schema的臨床邏輯盲點(例如加入「不該出現的錯誤處置」類的
   否定式forbidden欄位，不是只列正面關鍵字)。
3. 對locked v2的候選輸出補一輪完整的人工gold label，讓這組全新資料也有
   跟v1_study同等級的驗證力道。
4. 如果條件允許，找第二位（最好是台語母語者）評估者對至少一部分gold
   label做獨立標記，才能真正算出Cohen's kappa，補上這次唯一評估者的
   限制。
5. 佔位符洩漏(`Drug-A`格式不一致)、漢羅混雜格式(`kah`羅馬字夾雜)這兩個
   gold labeling時額外發現的問題，屬於翻譯/TTS交界處的風險，不在這次
   「只隔離翻譯安全評分方法論」的範圍內，但值得另外開一輪處理。
