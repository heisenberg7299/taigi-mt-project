"""
單獨跑MERaLiON adapter的進入點，因為omnivoice套件要求transformers>=5.3.0，
跟其他adapter用的coqui-tts（要求<5）版本衝突，不能塞進 run_tts_benchmark.py
那個共用的執行流程裡。

執行前：pip install "transformers>=5.3.0"
執行後想測其他adapter：pip install "transformers<5"

輸出會append進同一份 tests/tts_benchmark_results.jsonl/csv
（用runner.run_all，跟其他adapter共用同一套結果格式，方便一起比較）。

執行：python scripts/run_tts_benchmark_meralion.py
"""
from tts_benchmark.runner import run_all
from tts_benchmark.adapters.meralion_omnivoice import MeralionOmnivoiceAdapter

if __name__ == "__main__":
    run_all([MeralionOmnivoiceAdapter()])
