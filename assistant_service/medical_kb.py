"""
醫療知識庫：給`brain_llm.py`的LLM大腦做retrieval-augmented generation用，
補上PLAN.md/brain_llm.py docstring裡明確標記過的「RAG(evidence_ids)還沒做」
缺口。

## 內容來源

資料結構跟預設內容參考自yuava22/Interactive-service-robots套件的範例
(`examples/nursing_robot_demo/medical_kb.py`)——那份是範例腳本，不在
`pip install -e`會裝進來的`voice_io_event_detector`套件本身裡，所以沒辦法
直接import沿用，這裡是重寫成這個專案風格的版本，資料內容(高血壓/糖尿病/
中風/發燒/跌倒等一般公共衛生常識，非病人個人化醫囑)保留大致相同的範圍。

## 刻意保守的整合方式：只當「輔助上下文」，不繞過既有安全機制

那份參考實作的用法是`kb.get_answer(text)`直接把知識庫查到的答案當最終
回覆——這個專案不採用這種做法，因為`response_controller.py`整套風險分級
/安全檢查/candidate A-B-C機制，就是為了不讓任何內容繞過去直接播放語音；
如果知識庫比對到就直接輸出答案，等於在大腦之外開了一條新的、沒有經過
風險升級規則檢查的路徑。

這裡的做法：`search()`查到的內容**只當作LLM prompt的參考資料**，
LLM還是要照原本的JSON schema輸出(intent/risk_level/slots/response_zh)，
一樣要經過`response_controller.py`完整的風險分級跟安全檢查——RAG在這裡
只降低LLM瞎編答案的機率，不取代任何一層既有的安全機制。查到的知識庫
entry id會填進`BrainResponse.evidence_ids`，讓这次回覆用了哪些知識庫
依據有跡可查(可稽核)，也是`evidence_ids`欄位原本設計的用途。

## 用SQL LIKE比對，不是向量嵌入

跟大部分「RAG」文獻預設的向量相似度檢索不同，這裡沿用參考實作的做法，
用SQL `LIKE`關鍵字比對——資料量小(20多筆)，關鍵字比對就足夠，沒有必要
為了20幾筆資料另外建向量索引、載入embedding模型。如果之後知識庫擴充到
上千筆、關鍵字比對開始漏掉語意相近但用詞不同的問題，才需要評估要不要
換成向量檢索，不是現在就要做的事。

## 內容查證(2026-09-10)：逐條對照權威來源，不是照抄範例就當作對的

一開始只是照搬yuava22範例的內容改寫，沒有另外查證每一條數字/建議是否
正確——這是有問題的，醫療內容錯了會真的造成傷害，不能因為「範例repo
裡就是這樣寫」而假設它是對的。逐條對照權威來源(美國心臟協會AHA/ACC、
美國糖尿病協會ADA、美國中風協會、台灣衛生福利部/國健署)後，發現原本
抄來的內容有兩處是**過時的錯誤數字**，不是單純用字問題：

1. **高血壓分期數字錯誤**：原本寫「第一級高血壓140-159/90-99」，這是
   舊版WHO/JNC7標準。AHA/ACC 2017年版(2025年8月重新確認有效)跟台灣
   高血壓學會/中華民國心臟學會(2022年5月起跟進採用)的現行標準是
   **130-139/80-89**才是第一級高血壓，140以上已經算第二級。已修正。
2. **中風治療黃金時間過時**：原本寫「3小時內」，美國中風協會(American
   Stroke Association)現行的tPA治療時間窗是**4.5小時**，寫3小時可能
   誤導有徵兆但超過3小時的人放棄就醫。已修正。

另外兩處數字本身沒錯，但**漏掉重要但書**，已補上：

3. 低血糖15-15法則：沒有說明這只適用於一般低血糖，**嚴重低血糖(血糖
   低於55 mg/dL)需要升糖素治療，不是靠吃糖**，已補充。
4. 發燒退燒藥門檻：衛福部原文是「超過38.5°C**且有不舒服的感覺**」，
   不是體溫一過門檻就該吃藥，已補上這個限定條件。

血糖正常值、忘記吃藥原則、右下腹痛/闌尾炎警訊這三條核對後內容正確，
維持原樣，只補上來源出處。每一條資料後面的註解都附上實際查證用的
來源網址，供之後覆核。**這批查證是2026-09-10做的一次性核對，不是
持續更新的機制**——如果之後這些機構更新了指引(尤其血壓/血糖/中風
這類會隨研究進展調整標準的項目)，這裡的內容需要重新核對，不會自動
跟著更新。
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeEntry:
    id: str
    question: str
    answer: str
    category: str


# (category, question, answer, keywords) —— 一般公共衛生常識，不是任何
# 特定病人的病歷/醫囑資料，跟這個系統本身不儲存病人個人資料的原則一致。
# 每條後面的註解是2026-09-10查證時核對的來源，出處詳細說明見上方
# docstring「內容查證」章節。跌倒/傷口照護/營養/心理支持這幾條是護理
# 常識層級的一般建議、沒有會隨研究更新的具體數字，沒有另外查證特定
# 來源，維持原樣。
_KNOWLEDGE_DATA: list[tuple[str, str, str, str]] = [
    ("高血壓", "高血壓怎麼辦", "高血壓患者應注意：1.定時測量血壓 2.低鹽飲食 3.規律服藥，不可自行停藥 4.保持情緒穩定 5.適度運動", "血壓,高血壓,血壓高"),
    # 第一級高血壓範圍已修正為130-139/80-89（原本抄的140-159/90-99是舊版
    # WHO/JNC7標準）。來源：AHA/ACC 2017指引(2025-08重新確認有效)
    # https://newsroom.heart.org/news/the-lowdown-on-high-blood-pressure-what-you-need-to-know ；
    # 台灣自2022-05起跟進同一套標準，見衛福部
    # https://www.mohw.gov.tw/cp-4626-56056-1.html 、國健署
    # https://www.hpa.gov.tw/Pages/Detail.aspx?nodeid=4990&pid=19259&sid=19258
    ("高血壓", "血壓正常值是多少", "正常血壓：收縮壓小於120，舒張壓小於80。第一級高血壓：130-139/80-89。", "血壓標準,正常值"),
    # 來源：美國糖尿病協會(ADA) Standards of Care 2026
    # https://diabetesjournals.org/care/article/49/Supplement_1/S27/163926/2-Diagnosis-and-Classification-of-Diabetes
    ("糖尿病", "血糖正常值是多少", "空腹血糖：70-99 mg/dL。飯後2小時：小於140 mg/dL。", "血糖,糖尿病,正常值"),
    # 15-15法則來源：ADA
    # https://professional.diabetes.org/sites/dpro/files/2023-12/hypoglycemia_in_diabetes.pdf 、
    # https://www.diabetesdefa.org/assets/document/15-15-rule-treating-low-blood-glucose-hypoglycemia
    # 補充嚴重低血糖(<55 mg/dL)不適用吃糖、需要升糖素治療的但書。
    ("糖尿病", "低血糖怎麼辦", "低血糖處理：1.立即補充15克糖(3顆方糖或半杯果汁) 2.15分鐘後再測血糖 3.若未改善重複一次 4.恢復後盡快進食。若血糖低於55 mg/dL或意識不清，屬嚴重低血糖，吃糖無效，需要立即就醫使用升糖素。", "低血糖,血糖太低,頭暈"),
    # 黃金治療時間已從「3小時」修正為「4.5小時」（美國中風協會現行tPA
    # 治療時間窗，3小時是過時數字，可能誤導超過3小時但仍在4.5小時內的
    # 人放棄就醫）。來源：American Stroke Association
    # https://www.stroke.org/en/help-and-support/resource-library/be-fast-materials/be-fast-infographic
    ("急症", "中風前兆有哪些", "中風徵兆(FAST)：臉部不對稱、單側手臂無力、口齒不清，一有徵兆立即送醫，黃金治療時間4.5小時內。", "中風,腦中風,徵兆"),
    ("急症", "胸痛怎麼辦", "請立即按呼叫鈴，可能是心臟問題，不要自行走動。", "胸痛,心臟"),
    ("急症", "呼吸困難怎麼辦", "保持坐姿，打開窗戶通風，立即通知護理人員。", "呼吸困難,喘不過氣"),
    # 來源：Cleveland Clinic https://my.clevelandclinic.org/health/diseases/8095-appendicitis 、
    # Mayo Clinic（右下腹痛為闌尾炎典型表現）
    ("急症", "右下腹痛是什麼原因", "右下腹持續疼痛（尤其合併發燒、噁心、疼痛逐漸惡化）是闌尾炎(盲腸炎)常見警訊之一，應盡快告知醫護人員評估，不要自行服用止痛藥掩蓋症狀，也不要延誤就醫。", "右下腹痛,闌尾炎,盲腸炎,腹痛,肚子痛"),
    # 補上衛福部原文的限定條件「且有不舒服的感覺」，不是體溫一過門檻就該
    # 吃藥。來源：衛生福利部 https://www.mohw.gov.tw/cp-2624-19496-1.html
    ("症狀", "發燒怎麼辦", "發燒處理：1.測量體溫確認 2.多喝溫水 3.減少衣物 4.溫水擦拭 5.超過38.5度且感覺不舒服可服退燒藥 6.持續高燒應就醫", "發燒,體溫高,退燒"),
    ("症狀", "頭暈怎麼辦", "請立即坐下或躺下，避免跌倒，通知護理人員測量血壓和血糖。", "頭暈"),
    ("症狀", "便秘怎麼辦", "改善便秘：1.每日飲水2000cc以上 2.增加膳食纖維 3.適度活動 4.定時排便，必要時告知護理人員。", "便秘,排便困難"),
    ("安全", "預防跌倒注意事項", "預防跌倒：下床先坐起無頭暈再站立、穿防滑拖鞋、保持走道暢通、需要協助按呼叫鈴。", "跌倒,摔倒,預防"),
    ("安全", "跌倒後怎麼辦", "跌倒後不要急著起身，確認有無劇烈疼痛，若有頭暈或疼痛立即按鈴。", "跌倒處理,摔倒"),
    ("睡眠", "失眠怎麼辦", "改善睡眠：固定作息、睡前避免咖啡茶、放鬆練習、保持臥室安靜昏暗，必要時告知醫師。", "失眠,睡不著"),
    ("照護", "傷口照護方法", "傷口照護：換藥前洗手、觀察有無紅腫化膿、用生理食鹽水清洗、覆蓋無菌紗布，並記錄變化。", "傷口,換藥"),
    ("營養", "長者營養建議", "長者每日營養：蛋白質(魚蛋豆腐)、鈣質(牛奶小魚乾)、膳食纖維(蔬菜水果)、水分1500-2000cc。", "營養,飲食,吃什麼"),
    # 「不要吃雙倍劑量」是藥物安全的通用共識，各大權威來源(Mayo Clinic
    # 藥物說明、FDA/MedlinePlus消費者用藥指引)對忘記服藥的處理原則一致，
    # 沒有單一canonical網址，是普遍藥理學安全常識，非特定機構獨有主張。
    # 參考範例：https://www.mayoclinic.org/drugs-supplements/acetaminophen-oral-route-rectal-route/description/drg-20068480
    ("用藥", "忘記吃藥怎麼辦", "忘記吃藥：想起時立即補吃；若接近下次服藥時間就跳過這次，不要吃雙倍劑量，經常忘記可設鬧鐘提醒。", "藥物,吃藥,忘記吃藥"),
]

_FAQ_DATA: list[tuple[str, str, str]] = [
    ("皮膚癢怎麼辦", "不要抓，可冰敷止癢，告知護理人員評估。", "症狀"),
    ("吃不下飯怎麼辦", "可嘗試少量多餐，選擇喜歡的食物，告知護理人員。", "營養"),
    ("心情不好怎麼辦", "可以找護理人員聊聊，或打電話給家人。", "心理"),
    ("可以下床嗎", "請先告知護理人員，評估後再下床，避免跌倒。", "安全"),
]


class MedicalKnowledgeBase:
    """一次性載入到記憶體SQLite(`:memory:`)，process存活期間重複查詢，
    不寫回磁碟——這裡的資料是固定的公共衛生常識參考資料，不是需要持久化
    的病人個人資料，用記憶體資料庫就夠，也避免多個worker process共用同一個
    檔案資料庫的併發問題。

    ## 修正記錄(2026-09-10)：跨執行緒使用同一個connection會crash

    這個物件是`brain_llm.py`裡的process級singleton(見`get_default_kb()`)，
    但Flask開發伺服器會用不同的執行緒處理不同request——實測時就真的撞到
    `sqlite3.ProgrammingError: SQLite objects created in a thread can only
    be used in that same thread`(第一個request在thread A建立connection，
    後續某個request被排到thread B處理，直接整個request 500)。這不是
    「查資料庫很慢」的問題，是「查詢當下直接丟例外」的問題，兩者症狀都會
    讓使用者覺得「問了沒反應/要等很久」，但根因跟修法完全不同。

    修正：`sqlite3.connect`加`check_same_thread=False`(允許跨執行緒使用
    同一個connection)，並用一個`threading.Lock`包住每次查詢——這個資料庫
    載入後只會被讀取(`search()`)，不會再寫入，理論上多執行緒同時唯讀不會
    真的衝突，但SQLite的Python binding本身不保證單一connection物件在沒有
    序列化存取時的行為，用Lock是最保守、不需要驗證SQLite底層細節就能保證
    正確的做法。"""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()
        self._load_default_data()

    def _init_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                keywords TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE faq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def _load_default_data(self) -> None:
        cursor = self._conn.cursor()
        cursor.executemany(
            "INSERT INTO knowledge (category, question, answer, keywords) VALUES (?, ?, ?, ?)",
            _KNOWLEDGE_DATA,
        )
        cursor.executemany(
            "INSERT INTO faq (question, answer, category) VALUES (?, ?, ?)",
            _FAQ_DATA,
        )
        self._conn.commit()

    def search(self, query: str, limit: int = 3) -> list[KnowledgeEntry]:
        """回傳跟`query`關鍵字比對到的知識庫條目，FAQ優先、其次是一般
        知識庫，依這個順序各自最多取`limit`筆，合併回傳(不做混合排序，
        FAQ通常是更直接的病房日常問句，優先權比一般衛教資訊高)。查無
        結果回傳空list，呼叫端要能正確處理「沒有查到相關資料」的情況，
        不能假設一定有結果。

        雙向比對「question/keyword 是否為 query 的子字串」跟「query 是否
        為 question 的子字串」——只做單一方向(只判斷question/keywords是否
        包含query)會漏掉一種真實情境：`brain_llm.py`實際呼叫時傳進來的
        `query`是`multimodal_brain.py`組好的完整句子(例如「使用者說的話：
        血壓正常值是多少」，前面多包了一層前綴)，這種情況下「question
        整個字串是不是query的子字串」才會成立，「question是否包含query」
        則永遠不成立(query比question長且多了前綴，不可能被包含在
        question裡)——這個雙向比對是2026-09-10實測發現只做單向比對時
        RAG完全不會觸發後修正的，見reports/或brain_llm.py整合記錄。

        ## 補充：字元集合重疊當備援比對(2026-09-10)

        真人實測發現連雙向子字串比對都不夠：使用者問「我腹部右下方陣痛
        會跑很久正常嗎」，知識庫裡對應的關鍵字是「右下腹痛」——兩者用字
        順序不同(「腹部右下方」vs「右下腹」)，任何一種子字串比對都不會
        觸發，等於知識庫裡明明已經收錄這個主題，實際問法稍微換個順序就
        完全查不到，RAG防幻覺的效果因此大打折扣。

        修正：關鍵字(不含question本身跟FAQ，那兩者維持子字串比對，避免
        誤觸發不相關結果)額外加一個備援規則——如果關鍵字字數不多(≤6字，
        避免長詞在長query裡巧合湊齊所有字元)，且關鍵字的**每一個字元都
        出現在query裡**(不要求順序/相鄰)，也算比對成功。這只是字元集合
        重疊，仍然不是真正的語意理解，對這個具體的用字順序問題足夠，但
        沒辦法處理真正的同義詞(例如「肚子」vs「腹部」用字完全不同)——
        資料量一旦擴充到需要處理大量同義詞變化，才值得評估換成向量檢索，
        不是現在就要做的事。

        資料量小(20多筆)，撈全部再用Python判斷即可，不需要更複雜的SQL
        寫法。"""
        if not query or not query.strip():
            return []

        def _matches(*candidates: str) -> bool:
            return any(c and (c in query or query in c) for c in candidates)

        def _keyword_matches(keyword: str) -> bool:
            if _matches(keyword):
                return True
            # 備援：短關鍵字的每個字元都出現在query裡就算命中，處理
            # 使用者用字順序跟關鍵字不同的情況(見上方docstring說明)
            if keyword and len(keyword) <= 6:
                return all(ch in query for ch in keyword)
            return False

        results: list[KnowledgeEntry] = []

        # 見class docstring的修正記錄：多個Flask請求執行緒可能同時呼叫這個
        # process共用的singleton，用Lock序列化存取這個唯一的connection。
        with self._lock:
            cursor = self._conn.cursor()

            cursor.execute("SELECT id, question, answer, category FROM faq")
            faq_matches = [
                KnowledgeEntry(id=f"faq:{row[0]}", question=row[1], answer=row[2], category=row[3])
                for row in cursor.fetchall()
                if _matches(row[1])
            ]
            results.extend(faq_matches[:limit])

            cursor.execute("SELECT id, question, answer, category, keywords FROM knowledge")
            kb_matches = []
            for row in cursor.fetchall():
                kb_id, question, answer, category, keywords = row
                keyword_terms = [k for k in keywords.split(",") if k]
                if _matches(question) or any(_keyword_matches(k) for k in keyword_terms):
                    kb_matches.append(KnowledgeEntry(id=f"kb:{kb_id}", question=question, answer=answer, category=category))
            results.extend(kb_matches[:limit])

        return results


_kb_singleton: MedicalKnowledgeBase | None = None


def get_default_kb() -> MedicalKnowledgeBase:
    global _kb_singleton
    if _kb_singleton is None:
        _kb_singleton = MedicalKnowledgeBase()
    return _kb_singleton
