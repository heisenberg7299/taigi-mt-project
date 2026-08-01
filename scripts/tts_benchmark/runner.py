"""
統一跑分核心。這支不認識任何特定模型，只認識 TTSAdapter 介面，
新增候選不用改這裡（見 reports/stage4_tts_candidates.md 的淘汰漏斗流程）。
"""
import json
import os
import time

from .benchmark_set import items_for_format
from .metrics import compute_audio_metrics, decide

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS_JSONL = os.path.join(ROOT, "tests", "tts_benchmark_results.jsonl")
RESULTS_CSV = os.path.join(ROOT, "tests", "tts_benchmark_results.csv")
AUDIO_DIR = os.path.join(ROOT, "tests", "tts_benchmark_audio")

CSV_FIELDS = [
    "model", "input_format", "required_frontend", "id", "category", "text",
    "frontend_output",
    "generation_success", "error",
    "audio_duration_sec", "silence_ratio", "effective_speech_sec", "rtf",
    "omission_rate", "intelligibility_score", "decision", "audio_path",
]


def run_adapter(adapter):
    print(f"=== 載入 {adapter.name}（input_format={adapter.input_format}, "
          f"required_frontend={adapter.required_frontend}）===")
    adapter.load()

    items = items_for_format(adapter.input_format)
    if not items:
        print(f"  沒有跟 input_format={adapter.input_format} 相容的測試句，略過")
        return []

    model_audio_dir = os.path.join(AUDIO_DIR, adapter.name)
    os.makedirs(model_audio_dir, exist_ok=True)

    results = []
    for item in items:
        row = {
            "model": adapter.name,
            "input_format": adapter.input_format,
            "required_frontend": adapter.required_frontend,
            "id": item["id"],
            "category": item["category"],
            "text": item["text"],
            "omission_rate": None,
            "intelligibility_score": None,
        }
        try:
            adapter.last_frontend_output = None
            t0 = time.time()
            samples, sample_rate = adapter.synthesize(item["text"])
            wall_clock = time.time() - t0
            metrics = compute_audio_metrics(samples, sample_rate, wall_clock)
            audio_path = os.path.join(model_audio_dir, f"{item['id']}.wav")
            _save_wav(samples, sample_rate, audio_path)

            row.update(metrics)
            row["generation_success"] = True
            row["error"] = None
            row["frontend_output"] = getattr(adapter, "last_frontend_output", None)
            row["audio_path"] = os.path.relpath(audio_path, ROOT)
            row["decision"] = decide(True, metrics)
            print(f"  [{item['id']}] OK duration={metrics['audio_duration_sec']}s "
                  f"silence={metrics['silence_ratio']:.0%} decision={row['decision']}")
        except Exception as e:
            row.update({
                "generation_success": False, "error": str(e),
                "frontend_output": getattr(adapter, "last_frontend_output", None),
                "audio_duration_sec": None, "silence_ratio": None,
                "effective_speech_sec": None, "rtf": None,
                "audio_path": None, "decision": "fail_error",
            })
            print(f"  [{item['id']}] 失敗: {e}")
        results.append(row)
    return results


def _save_wav(samples, sample_rate, path):
    import soundfile as sf
    sf.write(path, samples, samplerate=sample_rate)


def run_all(adapters):
    os.makedirs(os.path.dirname(RESULTS_JSONL), exist_ok=True)
    all_results = []
    for adapter in adapters:
        all_results.extend(run_adapter(adapter))

    with open(RESULTS_JSONL, "w") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    import csv
    with open(RESULTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in all_results:
            writer.writerow({k: r.get(k) for k in CSV_FIELDS})

    print(f"\n完成，共 {len(all_results)} 筆結果")
    print(f"  {RESULTS_JSONL}")
    print(f"  {RESULTS_CSV}")
    return all_results
