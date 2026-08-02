"""
Protected Token Pipeline 原型：在送進翻譯模型之前，把關鍵資訊
（人名/藥名/病房號等）換成佔位符，翻譯完再換回來，避免LLM翻譯模型
自由生成時把這些資訊搞丟或幻覺成別的東西。

背景：實測發現Taigi-Llama-2-Translator在10句自己寫的新句子（不在200句
測試集裡）中，有4句出現safety-critical等級的語意流失，包括完整藥名
「盤尼西林」被直接吃掉、病人名字「小明」被丟掉只剩姓。見
reports/safety_critical_translation_failures.md。

佔位符格式的選擇不是隨便挑的，是實測過的：
- [PERSON1] 這種帶括號+數字的格式：不可靠，有時被丟掉，有時被當成
  語意提示重新生成成別的字（例如[DRUG1]被理解成「藥」的意思後
  自己生成一個「藥」字，不是保留原始佔位符）
- PERSONONE 這種純大寫英文單字（無括號、無數字）：實測穩定通過，
  推測是LLM把它當成「不需要翻譯的外語詞」直接複製過去，跟數字/符號
  的處理方式不同

這只是原型，證明protected token這個方向technically可行，不是正式的
NER系統——實際的實體偵測目前用簡單規則/字典比對，不是訓練過的NER模型，
覆蓋率有限，見下方TODO。

執行：python scripts/protected_token_pipeline.py
"""
import json
import re

import requests

MODEL = "hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/generate"

# 佔位符池：純大寫英文單字，不用數字/括號（見上方說明）
PLACEHOLDER_WORDS = {
    "PERSON": ["PERSONA", "PERSONB", "PERSONC"],
    "DRUG": ["DRUGA", "DRUGB", "DRUGC"],
    "ROOM": ["ROOMA", "ROOMB", "ROOMC"],
}

# 原型用的簡單規則/字典偵測，不是正式NER（見docstring說明）
KNOWN_DRUGS = ["盤尼西林", "普拿疼", "胰島素", "阿斯匹靈", "類固醇"]
SURNAME_TITLE_RE = re.compile(r"([王李陳林張黃吳劉蔡楊許鄭謝洪郭邱曾廖]{1}[一-鿿]{1,2})(先生|小姐|太太|阿嬤|阿公|醫師)")
ROOM_RE = re.compile(r"(\d+)(號病房|號床)")


def detect_and_mask(text):
    """回傳 (被遮蓋後的文字, 還原對照表)。"""
    mapping = {}
    counters = {"PERSON": 0, "DRUG": 0, "ROOM": 0}

    def next_placeholder(kind):
        idx = counters[kind]
        counters[kind] += 1
        return PLACEHOLDER_WORDS[kind][idx % len(PLACEHOLDER_WORDS[kind])]

    masked = text
    for drug in KNOWN_DRUGS:
        if drug in masked:
            ph = next_placeholder("DRUG")
            mapping[ph] = drug
            masked = masked.replace(drug, ph)

    def replace_person(m):
        ph = next_placeholder("PERSON")
        mapping[ph] = m.group(1)
        return ph + m.group(2)
    masked = SURNAME_TITLE_RE.sub(replace_person, masked)

    def replace_room(m):
        ph = next_placeholder("ROOM")
        mapping[ph] = m.group(1)
        return ph + m.group(2)
    masked = ROOM_RE.sub(replace_room, masked)

    return masked, mapping


def unmask(text, mapping):
    for ph, original in mapping.items():
        text = text.replace(ph, original)
    return text


def translate(zh):
    prompt = f"[TRANS]\n{zh}\n[/TRANS]\n[HAN]\n"
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "raw": True, "stream": False,
        "options": {"temperature": 0, "stop": ["[TRANS]", "</s>"]},
    }).encode("utf-8")
    resp = requests.post(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}, timeout=60)
    text = resp.json().get("response", "").strip()
    text = re.sub(r"\[/?(HAN|POJ|HL|ZH|EN)\]\s*$", "", text).strip()
    return text


def translate_with_protection(zh):
    masked, mapping = detect_and_mask(zh)
    raw_translation = translate(zh)
    protected_translation = translate(masked)
    restored = unmask(protected_translation, mapping)
    return {
        "zh": zh,
        "masked": masked,
        "mapping": mapping,
        "raw_translation": raw_translation,
        "protected_translation_masked": protected_translation,
        "protected_translation_restored": restored,
    }


if __name__ == "__main__":
    test_cases = [
        "你對盤尼西林會不會過敏？",
        "王小明先生，你的抽血報告出來了。",
        "阿嬤，你這罐胰島素要放冰箱冷藏。",
        "請共我叫三號病房的護理師。",
    ]
    for zh in test_cases:
        r = translate_with_protection(zh)
        print(f"原句：{r['zh']}")
        print(f"  遮蓋後：{r['masked']}")
        print(f"  沒保護直接翻譯：{r['raw_translation']}")
        print(f"  保護後翻譯(遮蓋狀態)：{r['protected_translation_masked']}")
        print(f"  保護後翻譯(還原)：{r['protected_translation_restored']}")
        print()
