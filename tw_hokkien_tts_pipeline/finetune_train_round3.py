"""第三輪微調實驗：用40位跟TH_THF1001同條件(女聲/混合腔/錄音室)的發音人
混合資料(9,610句/16.9小時，比單一發音人的30分鐘多33倍)，同樣套用
500-1,000 steps小規模微調+每250 steps checkpoint的協定，測試「增加
發音人多樣性/資料量」對round2發現的prosody問題(F0 std/pause overshoot)
有沒有幫助。

跟round2的差別只有資料來源(`PILOT_DATA_DIR`指向40人混合資料集)跟
`config.epochs`：40人資料集一個epoch有9,610/4≈2,402個step，遠超過
1,000，**這裡故意設`epochs=1`只是當作安全上限，實際跑到checkpoint_1000
存好之後就要手動中止**，不會讓它跑完整個epoch(跑完不符合「500-1,000
steps小規模」的實驗設計初衷)。

**混合40位不同發音人的已知風險**：這個模型是單一speaker模型(沒有
speaker embedding)，混合多人聲音資料，理論上有可能讓合成出來的音色
不再是單一乾淨的聲音、而是漂移/混雜——這是實驗性做法，需要實際聽過
才能判斷是不是真的發生。

環境相容性修正、MPS加速monkeypatch跟round1/round2完全一樣，不重複
說明，見`finetune_train.py`docstring。
"""

from __future__ import annotations

import torch
import torchaudio

if not hasattr(torchaudio, "info"):
    import soundfile as _sf
    from types import SimpleNamespace

    def _torchaudio_info_shim(path):
        info = _sf.info(str(path))
        return SimpleNamespace(num_frames=info.frames, sample_rate=info.samplerate, num_channels=info.channels)

    torchaudio.info = _torchaudio_info_shim

from TTS.config import load_config
from TTS.config.shared_configs import BaseDatasetConfig
from TTS.tts.datasets import load_tts_samples
from TTS.tts.models.vits import Vits
from trainer import Trainer, TrainerArgs
import trainer.trainer as _trainer_module

BASE_MODEL_DIR = "/Users/heisenberg/taigi-mt-project/models/neurlang-vits-suisiann"
MULTISPEAKER_DATA_DIR = "/Users/heisenberg/taigi-mt-project/data/raw/tat_moe_multispeaker_40"
OUTPUT_PATH = "/Users/heisenberg/taigi-mt-project/models/finetune_runs/tat_moe_multispeaker_40_round3"
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


def _to_device(x):
    if x is None:
        return None
    if torch.is_tensor(x):
        x = x.contiguous()
        x = x.to(DEVICE, non_blocking=True)
    return x


if DEVICE == "mps":
    _trainer_module.to_cuda = _to_device


def build_config():
    config = load_config(f"{BASE_MODEL_DIR}/config.json")
    config.output_path = OUTPUT_PATH
    config.phoneme_cache_path = f"{OUTPUT_PATH}/phoneme_cache"
    config.datasets = [
        BaseDatasetConfig(
            formatter="ljspeech",
            meta_file_train="metadata.csv",
            path=MULTISPEAKER_DATA_DIR,
            language="",
        )
    ]
    config.mixed_precision = False
    config.batch_size = 4
    config.eval_batch_size = 4
    config.num_loader_workers = 0
    config.num_eval_loader_workers = 0
    config.run_eval = True
    config.test_delay_epochs = -1
    config.epochs = 1  # 安全上限(9610句/4=2402 step/epoch)，實際只跑到1000步左右就手動中止
    config.print_step = 10
    config.save_step = 250
    config.save_n_checkpoints = 5
    config.save_best_after = 250
    config.eval_split_size = 0.02  # 40人資料集較大，2%就有約190句eval，不用像單人那樣拉高比例
    return config


def main():
    print("torch:", torch.__version__)
    print(f"training device: {DEVICE}")

    config = build_config()

    model = Vits.init_from_config(config)
    model.load_checkpoint(config, f"{BASE_MODEL_DIR}/best_model.pth", eval=False, strict=False)
    model = model.to(DEVICE)

    train_samples, eval_samples = load_tts_samples(
        config.datasets,
        eval_split=True,
        eval_split_max_size=config.eval_split_max_size,
        eval_split_size=config.eval_split_size,
    )
    print(f"train_samples: {len(train_samples)}, eval_samples: {len(eval_samples)}")

    trainer = Trainer(
        TrainerArgs(),
        config,
        OUTPUT_PATH,
        model=model,
        train_samples=train_samples,
        eval_samples=eval_samples,
    )
    if DEVICE == "mps":
        if isinstance(trainer.criterion, list):
            trainer.criterion = [c.to(DEVICE) if hasattr(c, "to") else c for c in trainer.criterion]
        elif hasattr(trainer.criterion, "to"):
            trainer.criterion = trainer.criterion.to(DEVICE)

    trainer.fit()


if __name__ == "__main__":
    main()
