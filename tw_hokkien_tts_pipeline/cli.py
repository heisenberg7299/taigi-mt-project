"""簡易 CLI: python -m tw_hokkien_tts_pipeline.cli "請記得在晚餐後服用盤尼西林。" """

from __future__ import annotations

import argparse
import json

from .config import PipelineConfig
from .pipeline import Pipeline


# 範例發音詞庫: 真實讀音需由台語專業人士確認, 這裡僅供 demo
DEMO_DRUG_LEXICON = {
    "盤尼西林": "puân-nî-se-lîm",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="中文 -> 台語 TTS pipeline")
    parser.add_argument("text", help="中文輸入句子")
    parser.add_argument("-o", "--output", default="output.wav", help="輸出 wav 檔名")
    parser.add_argument(
        "--output-dir", default="./pipeline_output", help="輸出資料夾"
    )
    parser.add_argument(
        "--real", action="store_true", help="使用真實後端 (需先完成 API/模型串接)"
    )
    args = parser.parse_args()

    backend_mode = "real" if args.real else "mock"
    config = PipelineConfig(
        translation_backend=backend_mode,
        segmentation_backend=backend_mode,
        tts_backend=backend_mode,
        output_dir=args.output_dir,
    )

    pipeline = Pipeline(config=config, drug_lexicon=DEMO_DRUG_LEXICON)
    result = pipeline.run(args.text, out_filename=args.output)

    print(json.dumps(result.to_debug_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
