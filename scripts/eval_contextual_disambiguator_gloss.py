"""
Controlled experiment: 在跟eval_contextual_disambiguator.py(純羅馬字版本)
完全同一批12筆已驗證gold case、同一個模型(qwen2.5:7b-instruct)、同一個
temperature=0設定下, 額外加入gloss-aware版本(OllamaGlossAwareContextual
Disambiguator), 四種方法(first/majority/contextual_llm_romanization_only/
contextual_llm_gloss_aware)並列比較——這是回答「給LLM候選讀音的中文釋義
之後, 它能不能真的利用語境選對」這個問題的實驗, 不是要取代羅馬字版本,
兩個都留著當獨立baseline。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tw_hokkien_tts_pipeline.contextual_disambiguator import (  # noqa: E402
    OllamaContextualDisambiguator,
    OllamaGlossAwareContextualDisambiguator,
)
from tw_hokkien_tts_pipeline.taihoa_dict_loader import (  # noqa: E402
    DEFAULT_CSV_PATH,
    glosses_for_surface,
)

BENCHMARK_PATH = os.path.join(
    ROOT, "tw_hokkien_tts_pipeline", "tests", "data", "ambiguity_gold_benchmark_v1.jsonl"
)


def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> None:
    rows = load_jsonl(BENCHMARK_PATH)
    eligible = [r for r in rows if not r.get("excluded_from_evaluation")]
    verified = [r for r in eligible if r.get("native_verified") and r.get("gold_reading")]

    plain_backend = OllamaContextualDisambiguator()
    gloss_backend = OllamaGlossAwareContextualDisambiguator()

    results = []
    for row in verified:
        glosses = glosses_for_surface(DEFAULT_CSV_PATH, row["surface"])
        plain_result = plain_backend.disambiguate(row["sentence"], row["surface"], row["candidates"])
        gloss_result = gloss_backend.disambiguate(
            row["sentence"], row["surface"], row["candidates"], glosses=glosses
        )
        results.append(
            {
                "surface": row["surface"],
                "gold": row["gold_reading"],
                "first_choice": row["first_choice"],
                "majority_choice": row["majority_choice"],
                "plain_llm": plain_result.chosen,
                "gloss_llm": gloss_result.chosen,
                "gloss_error": gloss_result.error,
                "glosses_found": bool(glosses),
            }
        )

    n = len(results)
    first_correct = sum(1 for r in results if r["first_choice"] == r["gold"])
    majority_correct = sum(1 for r in results if r["majority_choice"] == r["gold"])
    plain_correct = sum(1 for r in results if r["plain_llm"] == r["gold"])
    gloss_correct = sum(1 for r in results if r["gloss_llm"] == r["gold"])

    print(
        f"{'字':6} {'gold':14} {'first':16} {'majority':16} "
        f"{'llm+羅馬字':16} {'llm+釋義':16}"
    )
    for r in results:
        def mark(choice):
            if choice is None:
                return "(無回應)"
            return f"{choice} {'✓' if choice == r['gold'] else '✗'}"

        print(
            f"{r['surface']:6} {r['gold']:14} {mark(r['first_choice']):16} "
            f"{mark(r['majority_choice']):16} {mark(r['plain_llm']):16} {mark(r['gloss_llm']):16}"
        )

    print()
    print(f"樣本數: {n} (統計上仍然很小, 見下方門檻判斷)")
    print(f"first_accuracy:                    {first_correct}/{n} = {first_correct/n:.3f}")
    print(f"majority_accuracy:                 {majority_correct}/{n} = {majority_correct/n:.3f}")
    print(f"contextual_llm_romanization_only:  {plain_correct}/{n} = {plain_correct/n:.3f}")
    print(f"contextual_llm_gloss_aware:        {gloss_correct}/{n} = {gloss_correct/n:.3f}")
    print()
    threshold = 8
    if gloss_correct >= threshold:
        print(f"gloss_correct({gloss_correct}) >= {threshold}/12 門檻 -> 有明顯訊號, 建議擴充gold benchmark到50-100筆")
    else:
        print(f"gloss_correct({gloss_correct}) < {threshold}/12 門檻 -> 建議停止prompt tuning, 考慮小型supervised classifier")


if __name__ == "__main__":
    main()
