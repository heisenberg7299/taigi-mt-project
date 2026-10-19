"""
修正neurlang VITS(pygoruut phonemizer)音素被靜默丟棄的問題。

背景：`reports/tts_oov_audit.md`(2026-08-01)發現84%(168/200)候選句子有
IPA音標符號本身缺vocab，被`TTSTokenizer.encode()`靜默丟棄——不是漏字，
是送氣(ʰ)、鼻化母音(ã/ĩ/ũ/ẽ/õ)這些在台語裡有辨義作用的音素特徵被拿掉。
當時audit只確認「這些符號被丟棄了」，沒有進一步查為什麼、能不能修。

深入調查(2026-08-04)後發現這**不是模型詞彙表真的不支援這些音素**，是
Unicode正規化形式不匹配：

  - **送氣ʰ(U+02B0 MODIFIER LETTER SMALL H)**：模型詞彙表(見`config.json`
    的`characters`)沒有這個符號，但有純字母`h`——這剛好對應台語羅馬字
    (白話字/台羅)標準寫法本來就是用「子音+h」表示送氣(th/ph/kh/tsh)，
    NFKD正規化剛好把`ʰ`轉成`h`，符合這個既有慣例，不是隨便亂轉。
  - **鼻化母音(ã/ĩ/ũ/ẽ/õ，pygoruut輸出precomposed NFC形式)**：模型詞彙表
    **沒有**precomposed形式，但**有**組合用鼻化符號(combining tilde,
    U+0303)——NFD正規化會把precomposed字元拆成「母音+combining tilde」
    兩個獨立codepoint，兩個部分都在詞彙表裡，拆開後就查得到。

實測(5句真實候選句子)：套用這個正規化後，被丟棄的送氣/鼻化符號從每句
2~6個降到0個。**唯一沒解決的殘留問題**：鼻音聲調符號(ń/ǹ，200句裡只
出現3次)，NFD分解後的組合符號(acute/grave accent)本身也不在詞彙表裡，
這個方法解決不了，需要另外處理或接受這個很小比例的殘留限制。

**這個修正沒有改變模型本身、沒有重新訓練**，只是把phonemizer輸出的IPA
字串轉成模型詞彙表看得懂的Unicode表示法，讓原本因為正規化形式不一致而
被誤丟棄的音素特徵能正確映射到模型已經學過的音素上。**沒有辦法保證發音
一定變得更準**——模型本身有沒有真的學好這些音素的正確發音是另一回事，
這個修正只能確保「音素資訊有傳進模型」，不能保證「模型念得準」，最終
效果需要台語母語者實際聽過確認，見`reports/tts_oov_audit.md`後續更新。

## 全形標點轉半形：實測後撤掉了(2026-08-04)

原本這裡還有一步「全形中文標點(，。？！)轉半形ASCII標點」，理由是模型
詞彙表(`punctuations`欄位)只有半形標點，全形標點原本也是被靜默丟棄，
理論上轉成半形能讓斷句訊號傳進模型。**實際讓使用者聽過後，回報「台語的
斷句更怪了」**——「詞彙表裡有這個符號」不等於「模型有學過怎麼在這個符號
處正確停頓」，這個模型訓練語料(suisiann)裡標點的實際使用方式/停頓長度
沒有查證過，貿然假設半形標點=正確斷句訊號是理論推測，沒有實測基礎，
使用者的耳朵給出的證據(斷句更怪)比理論推測更可信，所以撤掉這一步，只
保留送氣/鼻化母音這個有明確音素學根據、且實測沒有引入新問題的修正。
**這不代表斷句問題已經解決**，只是排除了一個實測後證明沒用甚至有反效果
的假設，斷句本身的根因還沒找到，見下方`patch_neurlang_phonemizer()`
docstring。

## 已知系統性發音錯誤修正(2026-08-06)

拿教育部TAT-MOE語料庫大規模比對後，發現的另一類問題(不是Unicode
正規化，是真的發音選錯)：見`pronunciation_overrides.py`跟
`reports/moe_corpus_taigi_analysis.md`。`patch_neurlang_phonemizer()`
現在也會套用這個修正。
"""

from __future__ import annotations

import unicodedata
from typing import Callable

from .pronunciation_overrides import apply_pronunciation_overrides


def normalize_phonemes(ipa_text: str) -> str:
    """把pygoruut輸出的IPA字串正規化，修正Unicode表示法不匹配造成的送氣/
    鼻化音素被靜默丟棄問題(見模組docstring)。輸入輸出都是IPA字串，不是
    漢字。**不處理標點**——全形轉半形標點實測後證明會讓斷句變更怪，已經
    撤掉，見模組docstring「全形標點轉半形：實測後撤掉了」。"""
    text = unicodedata.normalize("NFD", ipa_text)
    text = text.replace("ʰ", "h")
    return text


def patch_neurlang_phonemizer(
    synthesizer,
    overrides_resolver: Callable[[str], dict[str, str]] | None = None,
) -> None:
    """幫coqui-TTS的`Synthesizer`套用`normalize_phonemes()`修正。只需要在
    `Synthesizer`載入後呼叫一次(`synthesizer.tts_model.tokenizer.phonemizer`
    是同一個物件會被重複使用)，之後每次`synth.tts()`呼叫都會自動套用，
    不需要每次合成前手動呼叫。

    `overrides_resolver`預設為`None`，沿用`pronunciation_overrides.py`的
    固定表(教育部TAT-MOE語料庫統計版本)，向後相容既有行為。傳入一個
    `(hanji_text) -> {字元: IPA}`的callable可以改用其他發音決策來源——
    例如`chhoetaigi_pronunciation_resolver.resolve_overrides_for_text`
    (ChhoeTaigi辭典+這學期母語者黃金標準)，兩套來源可以互相替換，不綁死
    在同一張表上，方便之後A/B比較或交叉驗證(見
    `reports/pronunciation_overrides_crosscheck.md`)。

    **斷句(全形標點)問題還沒解決**：這裡只處理送氣/鼻化音素，不處理標點。
    全形中文標點(，。？！)目前還是會被tokenizer靜默丟棄，等於句子裡完全
    沒有明確的停頓/斷句訊號傳給模型——這可能才是使用者反應「斷句怪」的
    根本原因，但目前還沒有查到「正確」的解法是什麼(轉半形ASCII標點已經
    實測證明不是答案)。可能需要查neurlang訓練語料實際怎麼標記停頓、或
    改用SSML之類的顯式停頓控制(如果這個TTS前端支援的話)，這兩者都還沒
    調查過。"""
    tokenizer = synthesizer.tts_model.tokenizer
    original_phonemize = tokenizer.phonemizer.phonemize

    def patched_phonemize(text, separator="", language=None):
        raw = original_phonemize(text, separator=separator, language=language)
        # 先修正已知系統性發音錯誤，用的是raw輸出裡直接觀察到的IPA形式
        # 做比對，所以要在NFD正規化之前做
        overrides = overrides_resolver(text) if overrides_resolver is not None else None
        raw = apply_pronunciation_overrides(text, raw, overrides)
        return normalize_phonemes(raw)

    tokenizer.phonemizer.phonemize = patched_phonemize
