"""用工程手段(程式明確插入靜音)處理斷句/停頓，取代「假設模型自己聽得懂
標點該怎麼停頓」的做法。

## 背景

`reports/moe_corpus_taigi_analysis.md`「發現三」量測到模型詞彙表完全
不支援全形中文標點，96.5%的真實語料庫句子含全形標點被靜默丟棄，句子
裡該有的停頓訊號完全沒有傳給模型。理論上修正這個問題的做法(把標點轉成
模型詞彙表看得懂的符號)已經實測證明沒用甚至更差(見
`phoneme_normalize.py`「全形標點轉半形：實測後撤掉了」)，連讀變調
(`tone_sandhi_ipa.py`)這個更根本的修正嘗試也一樣被使用者實測判定
「沒有變調的版本比較好」。

這兩次都是「假設模型能學會停頓/變調規則」失敗的例子。這個模組換一個
完全不同的角度：**不依賴模型理解任何停頓相關的語言學規則**，而是在
標點符號的位置把句子切成好幾段，每段各自送進TTS模型合成，段落之間
用程式產生的靜音接起來——停頓的長度、位置完全由我們自己控制，模型
只需要負責把每一小段話講清楚，不需要它自己判斷「這裡該不該停」。

**這是實驗性做法，還沒有讓使用者實際聽過確認**——沿用這個session的
一貫做法(斷句/變調兩次教訓都是理論正確不代表聽起來更好)，正式啟用前
應該先產生有無這個處理的對照音檔，讓母語者實際比較過再決定。
"""

from __future__ import annotations

import re

_CLAUSE_BOUNDARY_RE = re.compile(r"[，。？！、；：]+")


def split_into_clauses(text: str) -> list[str]:
    """依全形標點切成段落，去掉標點本身、去掉空字串段落。"""
    parts = _CLAUSE_BOUNDARY_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def synthesize_with_explicit_pauses(synth, text: str, pause_ms: int = 300):
    """把`text`依標點切成段落，每段各自呼叫`synth.tts()`合成，段落間
    插入`pause_ms`毫秒的靜音接起來。回傳跟`synth.tts()`同樣格式的
    waveform(list/array of float)。

    只有一段(沒有標點可切，或整句就是一段)時直接呼叫`synth.tts(text)`，
    不做任何額外處理——避免無謂地改變本來就不需要處理的簡單句子的
    合成路徑。
    """
    clauses = split_into_clauses(text)
    if len(clauses) <= 1:
        return synth.tts(text)

    silence_samples = int(synth.output_sample_rate * pause_ms / 1000)
    silence = [0.0] * silence_samples

    parts = []
    for i, clause in enumerate(clauses):
        wav = synth.tts(clause)
        parts.extend(wav)
        if i < len(clauses) - 1:
            parts.extend(silence)
    return parts
