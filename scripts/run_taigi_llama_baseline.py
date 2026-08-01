"""
Baseline 2：用 Taigi-Llama-2-Translator-7B（透過本機 Ollama）翻譯 200 句測試集。
輸出台語漢字（[HAN]），供跟辭典最長詞匹配 baseline 及安全檢查層比較。

注意：此模型授權 CC-BY-NC-SA-4.0，僅供研究/非商業比較用，不可直接商用部署。

執行：python scripts/run_taigi_llama_baseline.py
"""
import json
import os
import re
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_SET = os.path.join(ROOT, "tests", "test_set_200.jsonl")
OUT = os.path.join(ROOT, "tests", "baseline_taigi_llama.jsonl")

MODEL = "hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/generate"


def translate(zh, target="HAN"):
    prompt = f"[TRANS]\n{zh}\n[/TRANS]\n[{target}]\n"
    body = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "raw": True,
        "stream": False,
        "options": {"temperature": 0, "stop": ["[TRANS]", "</s>"]},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        d = json.loads(resp.read())
    text = d.get("response", "").strip()
    text = re.sub(r"\[/?(HAN|POJ|HL|ZH|EN)\]\s*$", "", text).strip()
    return text


def main():
    rows = []
    with open(TEST_SET) as f:
        for line in f:
            rows.append(json.loads(line))

    print(f"共 {len(rows)} 句，開始跑 Taigi-Llama baseline...")
    t0 = time.time()
    with open(OUT, "w") as fout:
        for i, r in enumerate(rows, 1):
            try:
                han = translate(r["zh"], "HAN")
            except Exception as e:
                print(f"  [{i}/{len(rows)}] {r['id']} 失敗: {e}")
                han = None
            out_row = {
                "id": r["id"],
                "zh": r["zh"],
                "category": r["category"],
                "check_type": r["check_type"],
                "baseline_taigi_llama_han": han,
            }
            fout.write(json.dumps(out_row, ensure_ascii=False) + "\n")
            fout.flush()
            if i % 20 == 0 or i == len(rows):
                elapsed = time.time() - t0
                print(f"  [{i}/{len(rows)}] 已完成，耗時 {elapsed:.0f}s")

    print(f"完成，寫入 {OUT}")


if __name__ == "__main__":
    main()
