"""
Baseline 1：辭典最長詞匹配（不做語意消歧，逐詞替換）。
目的不是產出可用翻譯，而是量化證明「純辭典替換」的失敗率，
與 Baseline 2（Taigi-Llama）對照，回答 PLAN.md 階段2要回答的問題。

作法：
1. 從教育部辭典 (dict-twblg.json) 建 反查表：中文釋義詞 -> 台語漢字(title)
   只取「短釋義」（<=4字、不含標點/例句）視為近似同義詞，避免把整句解釋當翻譯。
2. 用 jieba 對中文句子斷詞，逐詞查表替換，查不到就保留原詞。
3. 不做任何語境判斷、不做否定/數字特殊處理 —— 刻意保持「純字典替換」的原始弱點。

執行：python scripts/run_dict_baseline.py
"""
import json
import os
import re
import jieba

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DICT_PATH = os.path.join(ROOT, "data", "raw", "moe_dictionary", "dict-twblg.json")
TEST_SET = os.path.join(ROOT, "tests", "test_set_200.jsonl")
OUT = os.path.join(ROOT, "tests", "baseline_dict_match.jsonl")

PUNCT_RE = re.compile(r"[，；：？！「」『』（）,;:!?()\s]")


def build_reverse_dict():
    entries = json.load(open(DICT_PATH))
    rev = {}  # zh_gloss -> nan_han (title), 保留第一個出現的（短釋義優先）
    for e in entries:
        title = e.get("title", "")
        if not title:
            continue
        for h in e.get("heteronyms", []):
            for d in h.get("definitions", []):
                raw = (d.get("def") or "").strip()
                if not raw:
                    continue
                # 定義常常是「削掉外皮。」或「討厭、嫌惡。」這種近義詞並列，
                # 只取句號前、頓號分隔出的短詞當候選同義詞，長句解釋直接捨棄。
                first_sentence = raw.split("。")[0]
                for gloss in first_sentence.split("、"):
                    gloss = gloss.strip()
                    if not gloss:
                        continue
                    if PUNCT_RE.search(gloss):
                        continue
                    if not (1 <= len(gloss) <= 4):
                        continue
                    if gloss == title:
                        continue
                    rev.setdefault(gloss, title)
    return rev


def main():
    rev = build_reverse_dict()
    print(f"辭典反查表建立完成，共 {len(rev)} 條中文詞->台語漢字對應")

    for zh_word in rev:
        jieba.add_word(zh_word)

    rows = [json.loads(l) for l in open(TEST_SET)]
    print(f"開始跑 {len(rows)} 句 baseline 1（辭典最長詞匹配）...")

    with open(OUT, "w") as fout:
        for r in rows:
            tokens = list(jieba.cut(r["zh"]))
            out_tokens = []
            replaced_any = False
            for tok in tokens:
                if tok in rev:
                    out_tokens.append(rev[tok])
                    replaced_any = True
                else:
                    out_tokens.append(tok)
            result = "".join(out_tokens)
            out_row = {
                "id": r["id"],
                "zh": r["zh"],
                "category": r["category"],
                "check_type": r["check_type"],
                "baseline_dict_match": result,
                "replaced_any_word": replaced_any,
            }
            fout.write(json.dumps(out_row, ensure_ascii=False) + "\n")

    print(f"完成，寫入 {OUT}")


if __name__ == "__main__":
    main()
