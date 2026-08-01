"""
階段4：TTS候選統一批次測試進入點。

新增候選模型的步驟：
1. 在 scripts/tts_benchmark/adapters/ 寫一個繼承 TTSAdapter 的類別
   （參考 neurlang_vits.py 或 speecht5_tailo.py）
2. 在下面 ADAPTERS 清單註冊
3. 重跑這支script，不用改其他任何檔案

執行：python scripts/run_tts_benchmark.py
結果：tests/tts_benchmark_results.jsonl / .csv，音檔存在 tests/tts_benchmark_audio/{model}/
omission_rate 和 intelligibility_score 兩欄留給人工補（透過驗證平台或直接聽音檔），
其他欄位（是否成功產生、靜音比例、有效語音長度、RTF）全部自動算好。
"""
from tts_benchmark.runner import run_all
from tts_benchmark.adapters.neurlang_vits import NeurlangVitsAdapter
from tts_benchmark.adapters.speecht5_tailo import SpeechT5TailoAdapter

ADAPTERS = [
    NeurlangVitsAdapter(),
    SpeechT5TailoAdapter(),
    # 之後要加新候選（MERaLiON-OmniVoice-Hokkien-TTS等），在這裡加一行就好
]

if __name__ == "__main__":
    run_all(ADAPTERS)
