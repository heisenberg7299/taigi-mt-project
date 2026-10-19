"""
把「發音消歧黃金標準」(ambiguity_gold_benchmark_v1/v2)拿來反向檢查正式
生產環境在用的 pronunciation_overrides.py。

## 這是真正把兩邊研究接起來的地方

`assistant_service`正式輸出台語語音時，唯一真的會影響neurlang發音的機制
是`CHARACTER_IPA_OVERRIDES`這張固定表(見該檔案docstring)——但這張表是
另一套獨立方法產生的(掃描TAT-MOE語料庫、找「單一主流讀音」的字)，
從來沒有跟這學期做的ChhoeTaigi辭典+母語者盲測黃金標準對過。

這支腳本做交叉驗證：黃金標準裡任何`native_verified=true`的字，如果剛好
也在`CHARACTER_IPA_OVERRIDES`表裡，比對兩邊給的讀音是否一致。設計成
可重複執行——之後v2/v3標註持續擴充，重跑這支腳本就能持續抓出新的衝突，
不是一次性腳本。

## 讀法

- AGREE：黃金標準只驗證過一種讀音，跟production override一致，不用動。
- DISAGREE（單一讀音）：黃金標準目前只在一個語境驗證過，但答案跟
  production override不同——標記起來，需要更多語境樣本才能判斷是
  production的表錯了、還是這句是特例，不會自動覆蓋。
- CONTEXT-DEPENDENT CONFLICT：黃金標準在不同語境驗證出**不只一種**
  讀音——這代表這個字本質上是文白異讀/多義字，production表卻假設它
  只有一種正確答案，這違反了production表自己docstring寫的收錄原則
  （「文白異讀...不適合用固定表覆蓋」），是結構性衝突，不是單一樣本
  的問題，需要真的處理（拿掉這個entry，或未來接上真正的上下文判斷）。
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OVERRIDES_PATH = os.path.join(ROOT, "tw_hokkien_tts_pipeline", "pronunciation_overrides.py")
BENCHMARK_PATHS = [
    os.path.join(ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1.jsonl"),
    os.path.join(ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v2_in_corpus.jsonl"),
]

# 解析CHARACTER_IPA_OVERRIDES裡每一行行內註解記錄的台羅讀音(例如
# `"請": "tsʰĩã˥˧",  # tshiann2，...`)——不重算IPA，直接讀開發者自己
# 寫下的意圖值，比對邏輯才不用重新實作一次tailo<->IPA轉換。
_OVERRIDE_LINE_RE = re.compile(r'"([^"]+)":\s*"[^"]+",\s*#\s*([a-zA-Z0-9]+)')


def load_overrides() -> dict[str, str]:
    text = open(OVERRIDES_PATH, encoding="utf-8").read()
    overrides: dict[str, str] = {}
    for m in _OVERRIDE_LINE_RE.finditer(text):
        ch, tailo = m.group(1), m.group(2)
        overrides.setdefault(ch, tailo)
    return overrides


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_verified_gold() -> dict[str, list[tuple[str, str, str]]]:
    """回傳 {surface: [(row_id, sentence, gold_reading), ...]}，只收
    native_verified=true 且 gold_reading 不是null的列。"""
    gold: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path in BENCHMARK_PATHS:
        for row in load_jsonl(path):
            if row.get("native_verified") and row.get("gold_reading"):
                gold[row["surface"]].append((row["id"], row["sentence"], row["gold_reading"]))
    return gold


def crosscheck() -> dict[str, list[dict]]:
    overrides = load_overrides()
    gold = load_verified_gold()

    results: dict[str, list[dict]] = {"agree": [], "disagree_single": [], "context_conflict": []}

    for surface, rows in gold.items():
        if surface not in overrides:
            continue
        override_reading = overrides[surface]
        readings = sorted({r[2] for r in rows})
        entry = {
            "surface": surface,
            "override_reading": override_reading,
            "benchmark_readings": readings,
            "rows": rows,
        }
        if len(readings) > 1:
            results["context_conflict"].append(entry)
        elif readings[0] == override_reading:
            results["agree"].append(entry)
        else:
            results["disagree_single"].append(entry)

    return results


def main() -> None:
    results = crosscheck()

    print(f"AGREE（{len(results['agree'])}）：production override 跟黃金標準一致")
    for e in results["agree"]:
        print(f"  {e['surface']!r}: {e['override_reading']}")

    print()
    print(f"DISAGREE_SINGLE（{len(results['disagree_single'])}）：只有單一語境樣本，跟production不同，"
          "證據還不足以覆蓋production的大規模語料庫掃描結果，先標記不動")
    for e in results["disagree_single"]:
        print(f"  {e['surface']!r}: production={e['override_reading']!r}  benchmark={e['benchmark_readings']}")
        for rid, sent, gr in e["rows"]:
            print(f"      {rid}: {sent!r} -> {gr}")

    print()
    print(f"CONTEXT_CONFLICT（{len(results['context_conflict'])}）：黃金標準證實這個字在不同語境有"
          "不只一種正確讀音，production卻用固定表假設只有一種——結構性衝突，建議從"
          "CHARACTER_IPA_OVERRIDES移除")
    for e in results["context_conflict"]:
        print(f"  {e['surface']!r}: production={e['override_reading']!r}  benchmark={e['benchmark_readings']}")
        for rid, sent, gr in e["rows"]:
            print(f"      {rid}: {sent!r} -> {gr}")


if __name__ == "__main__":
    main()
