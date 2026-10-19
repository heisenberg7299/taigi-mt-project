"""第二輪微調實驗：小規模(500-1,000 steps)，搭配`prosody_baseline.py`
量測的before/after對照，回答使用者提出的問題——「聽起來太快/太平板」
是推理參數(`length_scale`)就能解決，還是duration/pitch model真的需要
重新學習。

跟第一輪(`finetune_train.py`, 60 epochs/4740 steps)的差別：
- 這次只跑500-1,000 steps(約13個epoch，79 steps/epoch)，不是60個
  epoch——目的不是產生一個要拿去正式使用的模型，是快速驗證「微調方向
  對不對」，跑太多反而增加過度配適風險(第一輪已經實測過80/60 epochs
  之後eval loss沒有再進步)。
- `save_step=250`：每250 steps存一次checkpoint(250/500/750/1000)，
  搭配固定的80句樣本(跟`prosody_baseline_before.json`同一批)在每個
  checkpoint重新跑`prosody_baseline.py`，畫出F0 std/pause count等指標
  隨訓練進度的變化趨勢，不是只看最終結果。
- 輸出路徑跟第一輪分開(`finetune_runs/tat_moe_pilot_thf1001_round2`)，
  避免覆蓋掉第一輪的checkpoint。

環境相容性修正(phoneme_cache_path路徑/torchaudio.info shim/
mixed_precision關閉)、MPS加速monkeypatch，都跟`finetune_train.py`
完全一樣，見該檔案docstring的完整說明，這裡不重複。
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
PILOT_DATA_DIR = "/Users/heisenberg/taigi-mt-project/data/raw/tat_moe_pilot_thf1001"
OUTPUT_PATH = "/Users/heisenberg/taigi-mt-project/models/finetune_runs/tat_moe_pilot_thf1001_round2"
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
            path=PILOT_DATA_DIR,
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
    config.epochs = 13  # 13 * 79 steps/epoch = 1027 steps，涵蓋250/500/750/1000四個checkpoint
    config.print_step = 10
    config.save_step = 250  # 使用者要求的checkpoint頻率
    config.save_n_checkpoints = 5  # 250/500/750/1000都要留著，不能只留3個
    config.save_best_after = 250
    config.eval_split_size = 0.05
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
