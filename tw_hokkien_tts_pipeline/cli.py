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
        "--real", action="store_true",
        help="斷詞也一併切成 real 後端 (尚未實作, 會丟例外; 翻譯/TTS層請分別用"
             "--translation-backend / --tts-backend)",
    )
    parser.add_argument(
        "--translation-backend", choices=["mock", "taigi_llama", "real"], default=None,
        help="只切換翻譯層要用哪個後端: mock(預設,示範詞庫) / taigi_llama(已驗證能實際"
             "翻譯,需要本機Ollama在跑,只當baseline不代表結果安全) / real(HTTP骨架,尚未指向"
             "特定API)。斷詞層不受影響",
    )
    parser.add_argument(
        "--tts-backend", choices=["mock", "neurlang", "real"], default=None,
        help="只切換TTS層要用哪個後端: mock(預設,提示音) / neurlang(已驗證能實際出聲) / "
             "real(speecht5_tailo骨架,尚未驗證)。翻譯/斷詞層不受影響",
    )
    parser.add_argument(
        "--require-safety-checks", action="store_true",
        help="安全檢查(Protected Token完整性+台語語意安全檢查)沒過就直接擋下合成，"
             "不只是記錄警告。預設關閉(這些檢查有已知誤報率，見README)",
    )
    args = parser.parse_args()

    backend_mode = "real" if args.real else "mock"
    translation_mode = args.translation_backend if args.translation_backend else backend_mode
    tts_mode = args.tts_backend if args.tts_backend else backend_mode
    config = PipelineConfig(
        translation_backend=translation_mode,
        segmentation_backend=backend_mode,
        tts_backend=tts_mode,
        output_dir=args.output_dir,
        require_protected_token_integrity=args.require_safety_checks,
        require_safety_checks_pass=args.require_safety_checks,
    )

    pipeline = Pipeline(config=config, drug_lexicon=DEMO_DRUG_LEXICON)
    result = pipeline.run(args.text, out_filename=args.output)

    print(json.dumps(result.to_debug_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
