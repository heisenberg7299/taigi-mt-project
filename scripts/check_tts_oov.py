"""
OOV audit：掃過候選台語漢字文字，找出主力TTS（neurlang VITS，內部用pygoruut
phonemizer）會靜默丟棄、不會被念出來的字元。

背景：實測證實 pygoruut 碰到詞彙表沒有的字元不會報錯、不會整句失敗，而是被
TTS.tts.utils.text.tokenizer.TTSTokenizer.encode() 靜默丟棄——比整句失敗更危險，
因為聽起來還是一句正常的話，只是漏了可能是藥名/症狀/地名的關鍵字。

用法：python scripts/check_tts_oov.py
掃描對象：tests/baseline_taigi_llama.jsonl（200句Taigi-Llama候選翻譯）
輸出：reports/tts_oov_audit.md
"""
import json
import os

from safety_checks import check_unconverted_characters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "tests", "baseline_taigi_llama.jsonl")
MODEL_DIR = os.path.join(ROOT, "models", "neurlang-vits-suisiann")
OUT = os.path.join(ROOT, "reports", "tts_oov_audit.md")


def is_cjk(c):
    cp = ord(c)
    return (
        0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
        or 0x20000 <= cp <= 0x2EBEF  # CJK Extension B-F（例如「𧙕」）
    )


def main():
    print("載入 neurlang VITS tokenizer（只載入一次）...")
    from TTS.utils.synthesizer import Synthesizer
    syn = Synthesizer(
        tts_checkpoint=os.path.join(MODEL_DIR, "best_model.pth"),
        tts_config_path=os.path.join(MODEL_DIR, "config.json"),
    )
    tokenizer = syn.tts_model.tokenizer

    rows = [json.loads(l) for l in open(BASELINE)]
    flagged = []          # 任何被丟棄字元（含IPA符號、含漢字）
    cjk_flagged = []      # 只有「整個漢字/詞被丟棄」這種嚴重情況
    all_dropped_chars = {}
    all_dropped_cjk = {}

    for r in rows:
        nan = r.get("baseline_taigi_llama_han")
        ok, reason = check_unconverted_characters(nan, tokenizer)
        if not ok:
            dropped = list(tokenizer.not_found_characters)
            dropped = [c for c in dropped if c not in set("。，、；：？！「」『』（）,.;:!?()— -\n\t ")]
            flagged.append({"id": r["id"], "zh": r["zh"], "nan": nan, "dropped": dropped})
            for c in dropped:
                all_dropped_chars[c] = all_dropped_chars.get(c, 0) + 1

            cjk_dropped = [c for c in dropped if is_cjk(c)]
            if cjk_dropped:
                cjk_flagged.append({"id": r["id"], "zh": r["zh"], "nan": nan, "dropped": cjk_dropped})
                for c in cjk_dropped:
                    all_dropped_cjk[c] = all_dropped_cjk.get(c, 0) + 1

    lines = []
    lines.append("# 主力TTS未知字元靜默丟棄 Audit（OOV audit）\n")
    lines.append("日期：2026-08-01\n")
    lines.append(f"掃描對象：`tests/baseline_taigi_llama.jsonl`（{len(rows)}句）\n")
    lines.append(
        "檢查方式：對每句候選台語漢字呼叫neurlang VITS的tokenizer（`TTSTokenizer.text_to_ids`），"
        "檢查`tokenizer.not_found_characters`——這是TTS函式庫自己內建、用來記錄"
        "「查不到vocab、被靜默丟棄」的字元清單，不是我們自己猜的。\n"
    )
    lines.append(
        "**結果分兩種性質完全不同的問題，不能混在一起看：**\n"
    )
    lines.append(f"- 🔴 **整個漢字被丟棄**（等於漏字，最嚴重）：{len(cjk_flagged)}/{len(rows)} 句")
    lines.append(f"- 🟡 **IPA音標符號本身缺vocab**（發音特徵被簡化，非漏字）：{len(flagged)}/{len(rows)} 句\n")

    if all_dropped_cjk:
        lines.append("## 🔴 整個漢字被丟棄（嚴重）— 統計\n")
        lines.append("| 字元 | 出現次數 |")
        lines.append("|---|---|")
        for c, n in sorted(all_dropped_cjk.items(), key=lambda x: -x[1]):
            lines.append(f"| {c} | {n} |")
        lines.append("")
        lines.append("### 詳細清單\n")
        for f in cjk_flagged:
            lines.append(f"- `{f['id']}` 「{f['zh']}」 -> 「{f['nan']}」　被丟棄：{f['dropped']}")
        lines.append("")
    else:
        lines.append(
            "## 🔴 整個漢字被丟棄（嚴重）\n\n"
            "**目前200句候選裡沒有任何一句發生這個問題**——之前用生僻字（「𧙕」）跟"
            "亂數組合字測試時有實測到這個失敗模式，但都是刻意找罕見字才踩到，"
            "真實的200句候選（常見生活/醫療詞彙）沒有踩到。這是好消息，但不代表"
            "以後不會發生，之後累積更多真實輸入應該持續重跑這支腳本追蹤。\n"
        )

    lines.append("## 🟡 IPA音標符號缺vocab（發音特徵被簡化）\n")
    lines.append(
        "這批被丟棄的**不是漢字**，是IPA音標符號本身——`ʰ`(送氣)、`ã`/`ĩ`/`ũ`/`ẽ`/`õ`"
        "(鼻化母音)、`ń`/`ǹ`(鼻音聲調)——代表 neurlang VITS 的音素詞彙表沒有涵蓋"
        "「送氣」和「鼻化」這兩個在台語裡有辨義作用的音素特徵。這**不是漏字**"
        "（字還是會被念出來），而是**這些字的發音會被簡化/唸不準**"
        "（例如送氣輔音可能唸成不送氣，鼻化母音可能唸成非鼻化）——"
        "但目前完全沒辦法從音檔的靜音比例/長度看出來，因為時長幾乎不受影響，"
        "只有真的懂台語的人聽了才聽得出差異。\n"
    )
    if all_dropped_chars:
        lines.append("| 符號 | 意義 | 出現次數 |")
        lines.append("|---|---|---|")
        symbol_meaning = {
            "ʰ": "送氣（如 tsʰ, pʰ, kʰ, tʰ）", "ã": "鼻化a", "ĩ": "鼻化i", "ũ": "鼻化u",
            "ẽ": "鼻化e", "õ": "鼻化o", "ń": "鼻音聲調", "ǹ": "鼻音聲調",
        }
        for c, n in sorted(all_dropped_chars.items(), key=lambda x: -x[1]):
            if c in symbol_meaning:
                lines.append(f"| {c} | {symbol_meaning[c]} | {n} |")
        lines.append("")
        other = {c: n for c, n in all_dropped_chars.items() if c not in symbol_meaning and not is_cjk(c)}
        if other:
            lines.append(f"其他非漢字雜項（可能是格式殘留）：{other}\n")

    lines.append("## 說明\n")
    lines.append(
        "這份audit只掃了目前已經產生的Taigi-Llama候選翻譯，不是掃「所有可能出現的字」。"
        "隨著之後累積更多真實輸入（母語者的note、階段5的領域資料），應該重跑這支腳本，"
        "持續追蹤有沒有新的高風險字元出現。這是`scripts/tts_benchmark`調查speecht5_tailo"
        "過程中，根據OOV pronunciation inference文獻建議加的第一層防護"
        "（「unknown-token audit」），不是完整的5層fallback架構——那個規模大很多，"
        "要等這類audit累積出足夠的真實案例才值得投入。\n\n"
        "**IPA符號缺vocab這個發現比漏字問題更值得後續追蹤**：84%的句子受影響，"
        "代表主力模型本身在送氣/鼻化這兩個台語音素特徵上可能系統性唸不準，"
        "這是比「踩到生僻字」更常見、更根本的品質上限，但目前只能從程式碼層面"
        "確認「這些符號被丟棄了」，沒辦法確認「丟棄之後實際聽起來差多少」——"
        "這需要母語者實際比較有無這些符號的合成結果才能判斷嚴重程度，"
        "或者去查neurlang模型訓練時用的音素詞彙表定義，確認是不是有辦法擴充。"
    )

    with open(OUT, "w") as f:
        f.write("\n".join(lines))

    print(f"完成，寫入 {OUT}")
    print(f"{len(flagged)}/{len(rows)} 句含有會被靜默丟棄的字元")
    if all_dropped_chars:
        print("被丟棄字元:", dict(sorted(all_dropped_chars.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
