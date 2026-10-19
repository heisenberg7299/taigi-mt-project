"""
ChhoeTaigi「2002+ 台華線頂對照典」CSV載入器: 把data/licenses/chhoetaigi_taihoa_dict.json
描述的91,339筆詞條CSV, 轉成segment.py斷詞層可以直接查表用的「台語漢字/漢羅
surface -> 台羅讀音」dict。

## 為什麼用HanLoTaibunPoj當surface key, PojInput當讀音來源

CSV欄位裡, HanLoTaibunPoj/HanLoTaibunKip是這個詞的「漢羅寫法」(漢字+
沒有漢字對應部分的羅馬字混寫), HoaBun則是「華語對照翻譯」(意思相近的
華語詞, 不是這個詞本身的另一種寫法)——這點在原始CSV欄位命名裡不是一望
即知, 是實際核對過樣本資料才確認的(例如DictWordID=1跟2, HanLoTaibunPoj
都是"á無", 但HoaBun分別是"不然"/"還是沒有", 顯然HoaBun是語意相近的翻譯
候選, 不是"á無"本身的另一種寫法)。segment.py需要的是「台語文字surface
-> 讀音」, 所以用HanLoTaibunPoj(台語漢羅寫法)當key, 不能誤用HoaBun。

讀音來源選PojInput不選KipInput, 理由見poj_to_tailo.py docstring
(Kip欄位系統未確認)。

## 同一surface多筆資料時的處理: OOV跟多音消歧是兩個分開的問題

同一個漢羅寫法可能對應多筆詞條(例如上面"á無"的例子), 如果讀音相同就
沒差, 但如果讀音不同(真正的多音字/歧義詞), 這裡故意不跟「詞庫查無這個
詞」(OOV) 用同一套fallback處理——OOV是「資料完全沒有」, 多音消歧是
「資料有, 但不只一種答案」, 兩者的解法方向不同(前者要擴充詞庫, 後者要
選擇候選), 混在一起處理容易兩邊都做不好。

多音消歧目前支援兩種`strategy`(見`load_taihoa_dict()`的`strategy`參數),
刻意兩種都留著讓呼叫端能直接比較，而不是直接拿一種取代另一種：

  - `"first"`(預設, 向後相容既有行為): 取CSV裡第一次出現的讀音。純粹
    是資料輸入順序, 沒有語言學根據——實測發現至少有「請」這個常見詞
    (tsheng2文讀/tshiann2白讀各一筆, 1:1平手)因為這樣選到文讀, 但這批
    醫療機器人語境的禮貌用語應該要白讀。
  - `"majority"`: 取CSV裡出現次數最多的讀音, 平手時退回第一次出現的
    (維持determinism)。比"first"更有根據一點(至少反映這份詞庫收錄時
    的相對頻率), 但CSV出現次數不等於真實語料使用頻率, 只能算是
    "dictionary-frequency baseline", 不是真正的語境消歧——真正
    context-dependent的詞(例如統計上兩種讀音頻率很接近, 但實際上該選
    哪個要看上下文), majority一樣解決不了, 需要之後的context selector
    (目前還沒做)。

用load_taihoa_dict_with_stats()可以額外拿到「這份詞庫裡有多少surface
其實有一種以上讀音」的統計, 供整合報告揭露這個已知限制, 不是隱藏掉。

## 假歧義: CSV漏標調號造成的「假多音字」

實測200句baseline_taigi_llama_han比對first跟majority兩種策略的差異時
發現, 有一部分並不是真正的多音字, 而是CSV本身有些列漏標了最後一個音節
的調號(例如"今仔日"有兩筆分別是"kin-a2-jit"跟"kin-a2-jit8", 差別只在
最後一個音節有沒有標調號8)——這個專案全部使用數字調表示法(見
tailo_ipa_converter.py的TONE_MAP, 1-8, 不含6), 一個音節沒有標調號在這個
記法裡本來就是不完整/不合法的, 所以「兩個讀音只差最後一個字元是不是
1-8的數字」不是語言學上真正的兩種讀音, 是資料缺值, 直接視為同一個讀音
是有根據的判斷, 不是憑感覺猜的合併。

`_canonicalize_readings()`在統計/選讀音之前先做這一步正規化(保留有標
調號、資訊較完整的那個當代表), 讓`ambiguous_surfaces`統計、"first"、
"majority"三者都不會被這種資料缺值污染成「看起來有兩種讀音」。**只處理
「差最後一個音節的調號」這一種已知的假歧義成因**, 不是通用的模糊比對
——其他真正的多音字(白讀/文讀差異、聲母韻母不同)還是會被正確視為
ambiguous, 不會被這個正規化誤吃。

## 檔案不隨repo提供

CSV本身(91,339列)不會進版控——見data/raw/chhoetaigi_taihoa_dict/README.md
的下載說明。這裡的load函式在檔案不存在時直接raise清楚的錯誤訊息, 不會
靜默回傳空dict(空詞庫會讓斷詞層誤判成「這個詞真的沒有讀音資料」而不是
「詞庫根本沒載入」, 兩種情況必須分得清楚)。
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .poj_to_tailo import poj_word_to_tailo

DisambiguationStrategy = Literal["first", "majority"]

DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "raw"
    / "chhoetaigi_taihoa_dict"
    / "ChhoeTaigi_TaihoaSoanntengTuichiautian.csv"
)

_DOWNLOAD_HINT = (
    "curl -L -o {path} \\\n"
    "  https://raw.githubusercontent.com/ChhoeTaigi/ChhoeTaigiDatabase/"
    "master/ChhoeTaigiDatabase/ChhoeTaigi_TaihoaSoanntengTuichiautian.csv"
)


@dataclass
class TaihoaDictStats:
    total_rows: int
    unique_surfaces: int
    ambiguous_surfaces: int  # 同一surface的PojInput讀音轉成台羅後不只一種的詞條數
    strategy: DisambiguationStrategy


_TONE_DIGITS = set("12345678")


def _syllables_equal_modulo_missing_tone(syl_a: str, syl_b: str) -> bool:
    """兩個音節是否「完全相同」或「只差一個尾端調號數字(1-8)」。"""
    if syl_a == syl_b:
        return True
    shorter, longer = (syl_a, syl_b) if len(syl_a) < len(syl_b) else (syl_b, syl_a)
    if len(longer) - len(shorter) != 1:
        return False
    return longer[:-1] == shorter and longer[-1] in _TONE_DIGITS


def _readings_equal_modulo_missing_tone(reading_a: str, reading_b: str) -> bool:
    """兩個(可能多音節、用連字號分隔的)讀音是否只差在某個音節漏標調號。"""
    syls_a = reading_a.split("-")
    syls_b = reading_b.split("-")
    if len(syls_a) != len(syls_b):
        return False
    return all(_syllables_equal_modulo_missing_tone(a, b) for a, b in zip(syls_a, syls_b))


def _canonicalize_readings(reading_list: list[str]) -> list[str]:
    """把「只差漏標調號」的讀音合併成同一個代表寫法(見模組docstring「假
    歧義」說明), 保留較長(有標調號、資訊較完整)的當代表。同一個surface的
    讀音種類通常只有個位數, 這裡用簡單的兩兩比對合併, 不需要更複雜的
    union-find。"""
    result = list(reading_list)
    merged = True
    while merged:
        merged = False
        distinct = sorted(set(result), key=len, reverse=True)
        for longer in distinct:
            for shorter in distinct:
                if shorter != longer and _readings_equal_modulo_missing_tone(longer, shorter):
                    result = [longer if r == shorter else r for r in result]
                    merged = True
                    break
            if merged:
                break
    return result


def _resolve_reading(reading_list: list[str], strategy: DisambiguationStrategy) -> str:
    if strategy == "first":
        return reading_list[0]
    if strategy == "majority":
        counts = Counter(reading_list)
        max_count = max(counts.values())
        # 多筆並列最高票時, 退回「CSV裡第一次出現」維持determinism, 不是
        # 隨便選一個——同一份輸入永遠要得到同一個結果
        for reading in reading_list:
            if counts[reading] == max_count:
                return reading
        raise AssertionError("unreachable: reading_list非空時一定會找到符合max_count的項目")
    raise ValueError(f"未知的消歧strategy: {strategy!r}, 只支援 'first' 或 'majority'")


def _require_csv(csv_path: Path) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"找不到台華線頂對照典CSV: {csv_path}\n"
            "這個檔案沒有隨repo一起提供(91,339列, CC BY-SA 4.0授權), 需要"
            "手動下載後放到這個路徑, 例如:\n"
            f"  {_DOWNLOAD_HINT.format(path=csv_path)}\n"
            "詳見 data/licenses/chhoetaigi_taihoa_dict.json"
        )


def _readings_by_surface(csv_path: Path) -> tuple[dict[str, list[str]], int]:
    """回傳 {surface: [依CSV出現順序的台羅讀音, 可能重複]}, 以及有效列數。
    回傳前已經套用_canonicalize_readings()合併掉「漏標調號」造成的假歧義
    (見模組docstring), 所以這裡回傳的讀音清單裡不會出現那種假多音字。"""
    readings: dict[str, list[str]] = defaultdict(list)
    total_rows = 0
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            surface = (row.get("HanLoTaibunPoj") or "").strip()
            poj_input = (row.get("PojInput") or "").strip()
            if not surface or not poj_input:
                continue
            total_rows += 1
            readings[surface].append(poj_word_to_tailo(poj_input))
    for surface in readings:
        readings[surface] = _canonicalize_readings(readings[surface])
    return readings, total_rows


def glosses_for_surface(csv_path: Path, surface: str) -> dict[str, list[str]]:
    """回傳 {台羅讀音: [這個讀音對應的HoaBun中文釋義, 依CSV出現順序, 可能
    重複]}, 給contextual_disambiguator.py的gloss-aware版本用——把候選讀音
    的實際語意(而不是只有羅馬字拼寫本身)提供給LLM判斷, 見該模組docstring
    的動機說明。

    刻意每次呼叫都重新掃過整個CSV(91,339列), 不做快取——這個函式目前
    只給Stage 5評估腳本用(12筆gold case, 一次性呼叫12次), 不是正式
    pipeline的即時查詢路徑, 效能不是這裡的考量, 之後若真的要接進
    segment.py的即時路徑, 需要另外做索引, 不能照搬這個實作。"""
    result: dict[str, list[str]] = defaultdict(list)
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row_surface = (row.get("HanLoTaibunPoj") or "").strip()
            if row_surface != surface:
                continue
            poj_input = (row.get("PojInput") or "").strip()
            hoa_bun = (row.get("HoaBun") or "").strip()
            if not poj_input or not hoa_bun:
                continue
            tailo = poj_word_to_tailo(poj_input)
            result[tailo].append(hoa_bun)
    return dict(result)


def load_taihoa_dict(
    csv_path: Path | str = DEFAULT_CSV_PATH,
    strategy: DisambiguationStrategy = "first",
) -> dict[str, str]:
    """回傳 {漢羅surface: 台羅讀音} 的查表dict, 供segment.py使用。同一
    surface有多種讀音時, 依`strategy`挑一個(見模組docstring的兩種策略
    說明)。預設"first"是為了向後相容既有行為, 不代表"first"比較好。"""
    csv_path = Path(csv_path)
    _require_csv(csv_path)
    readings, _ = _readings_by_surface(csv_path)
    return {surface: _resolve_reading(reading_list, strategy) for surface, reading_list in readings.items()}


def load_taihoa_dict_with_stats(
    csv_path: Path | str = DEFAULT_CSV_PATH,
    strategy: DisambiguationStrategy = "first",
) -> tuple[dict[str, str], TaihoaDictStats]:
    """跟load_taihoa_dict()回傳同一份查表dict(取值邏輯完全一致, 不會有兩個
    函式各自選了不同讀音的不一致問題), 額外回傳統計資訊。"""
    csv_path = Path(csv_path)
    _require_csv(csv_path)
    readings, total_rows = _readings_by_surface(csv_path)

    result = {surface: _resolve_reading(reading_list, strategy) for surface, reading_list in readings.items()}
    ambiguous_count = sum(1 for reading_list in readings.values() if len(set(reading_list)) > 1)

    stats = TaihoaDictStats(
        total_rows=total_rows,
        unique_surfaces=len(readings),
        ambiguous_surfaces=ambiguous_count,
        strategy=strategy,
    )
    return result, stats
