"""從neurlang既有checkpoint繼續微調VITS(不是從零訓練)，用
`finetune_data_prep.py`準備好的單一發音人資料。

## 環境相容性修正(2026-08-05實測發現，缺一個都跑不起來)

1. **`config.phoneme_cache_path`/`output_path`殘留原作者的Linux路徑**
   (`/home/m2/...`)，macOS建不出`/home`底下的目錄
   (`OSError: [Errno 45] Operation not supported`)——這裡明確覆寫成
   本機路徑。
2. **`torchaudio`(這個venv裝的是2.11.0)把`torchaudio.info()`整個拿掉了**
   (改成只剩`load`/`save`)，但coqui-tts 0.27.4的
   `TTS/tts/datasets/dataset.py get_audio_size()`還在呼叫這個已經不存在
   的API——用soundfile補一個回傳`.num_frames`屬性的相容shim，不改
   requirements.txt版本(避免影響MERaLiON等依賴`transformers>=5.3.0`的
   功能)。
3. **`mixed_precision=True`在純CPU上會用bfloat16**(CPU autocast只支援
   bfloat16，不是fp16)，但視覺化log(`plot_results`)的
   `.cpu().numpy()`沒處理bfloat16轉numpy會crash——CPU本來也吃不到混合
   精度的加速好處，直接關掉。

## 這台Mac(M5, MPS, 無CUDA)的實測速度

`trainer`套件(`Trainer.model.cuda()`/`to_cuda()`)只認CUDA，沒有MPS分支，
預設會整個訓練過程都在純CPU上跑。**純CPU實測**：前30幾個step約1.8秒/
step，但持續全速運算觸發筆電散熱降頻後掉到約27秒/step(慢15倍)，一個
epoch(318句、batch_size 4、79個step)實測跑了35.8分鐘。

**改用MPS(這個檔案目前的做法)實測**：monkeypatch
`trainer.trainer.to_cuda`讓batch資料搬去`mps`裝置(不是`cuda`)，並且
手動把model+criterion搬到mps(因為`Trainer.__init__`裡的`.cuda()`呼叫
被`use_cuda=False`跳過，不會自動搬)。結果：同樣一個epoch只要**123秒**
(比純CPU快約17倍)，而且CPU使用率只有35%左右(相對於純CPU版本的
186%)，全程沒有觸發散熱降頻、沒有crash——GPU cluster的算力沒有被
CPU那種持續高負載的散熱問題卡住。VITS模型本身用`self.device`(不是
寫死`.cuda()`)，這也是MPS能直接work、不用改model程式碼本身的原因。

有一個non-fatal的warning：`nn.functional.pad`在超過3維的constant
padding在MPS上沒有原生實作，會fallback成較慢的view-ops版本——不影響
正確性，只是那個op沒有拿到完整加速，實測沒有造成整體變慢或crash。

## 用法

```
python3 finetune_train.py
```

預設路徑指向主要checkout(不是worktree)的`models/`與`data/raw/`——
因為這是會跑好幾個小時的背景程序，資料/checkpoint要放在不會被
worktree生命週期影響的地方，跟現有正式模型`models/neurlang-vits-suisiann/`
同樣的慣例。
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
OUTPUT_PATH = "/Users/heisenberg/taigi-mt-project/models/finetune_runs/tat_moe_pilot_thf1001"
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"


def _to_device(x):
    if x is None:
        return None
    if torch.is_tensor(x):
        x = x.contiguous()
        x = x.to(DEVICE, non_blocking=True)
    return x


if DEVICE == "mps":
    _trainer_module.to_cuda = _to_device  # trainer套件寫死只認cuda，這裡改成mps


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
    config.num_loader_workers = 0  # spawn-based multiprocessing在macOS上會re-import
    config.num_eval_loader_workers = 0  # 這個腳本檔案，worker數保持0比較安全、也是實測過會動的設定
    config.run_eval = True
    config.test_delay_epochs = -1
    config.epochs = 60  # MPS約123秒/epoch(比純CPU快17倍，且不會降頻)，60 epochs約2小時，中途隨時可用已存的checkpoint
    config.print_step = 10
    config.save_step = 79  # 每個epoch存一次(318句/batch_size 4=79 step/epoch)
    config.save_n_checkpoints = 3  # 只留最近3個，避免磁碟塞爆
    config.save_best_after = 79
    config.eval_split_size = 0.05
    return config


def main():
    print("torch:", torch.__version__)
    print("cuda available:", torch.cuda.is_available())
    print("mps available:", torch.backends.mps.is_available())
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
    # Trainer.__init__裡的.cuda()呼叫被use_cuda=False跳過，criterion要手動搬
    if DEVICE == "mps":
        if isinstance(trainer.criterion, list):
            trainer.criterion = [c.to(DEVICE) if hasattr(c, "to") else c for c in trainer.criterion]
        elif hasattr(trainer.criterion, "to"):
            trainer.criterion = trainer.criterion.to(DEVICE)

    trainer.fit()


if __name__ == "__main__":
    main()
