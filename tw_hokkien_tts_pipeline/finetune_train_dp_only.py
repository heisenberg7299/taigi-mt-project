"""第四輪實驗：只訓練duration predictor(DP-only)，凍結其他所有生成器
子模組(text_encoder/posterior_encoder/flow/waveform_decoder)，只留
duration_predictor(1.3M參數，佔全模型83M的1.6%)+discriminator(GAN
判別器，維持正常對抗訓練動態)可訓練。

## 動機

前三輪微調(round1/2/3)都是全模型更新，使用者指出這樣「為了修正一個
時間結構問題(講太快/停頓不足)，卻讓所有聲學模組(音色/發音/音高生成)
一起變動」，沒辦法排除「音質變差」是不是這個全模型更新造成的副作用，
不是資料量或16kHz音質天花板本身的問題。DP-only是最直接對應問題定義
(只改「講多久」不改「聲音怎麼生成」)的實驗設計，理論上應該最大程度
保留原始模型的音色/清晰度/發音能力，同時仍然讓duration predictor有
機會學習這批新資料的語速/停頓特徵。

## 怎麼凍結

VITS的`named_children()`：text_encoder(6.3M)/posterior_encoder(7.2M)/
flow(7.1M)/duration_predictor(1.3M)/waveform_decoder(14.3M)/disc(46.7M)。
`Vits.get_optimizer()`用`self.named_parameters()`(排除`disc.`開頭)建立
generator optimizer，**不會**先過濾`requires_grad`——但AdamW.step()對
`p.grad is None`的參數會直接跳過不更新，所以只要在建立`Trainer`之前
(也就是`get_optimizer()`真正被呼叫之前)把目標子模組的`requires_grad`
設成`False`，backward()就不會幫它們算梯度，效果上等同凍結，不需要
額外處理optimizer的參數列表。

## 跟round2的差異

- 資料：跟round2一樣是TH_THF1001原始334句(不是round3的40人混合)，
  這樣才能乾淨地比較「凍結非duration模組」這個變因，不會跟「換資料」
  混在一起。
- 步數：100/250/500(比round2/3的250/500/750/1000更小)，`save_step=50`
  讓checkpoint間隔更細(50/100/150/.../500都會存)，之後可以挑
  100/250/500這三個對應使用者要求的點來看。

## 第一版實測失敗+根因分析+修正(2026-08-06/07，同一組實驗的第二次嘗試)

第一版只把`lr_gen`調成1/10(0.0002->0.00002)、`lr_disc`維持預設不變，
**使用者實際聽過100/250/500步的結果，回報「卡住/連在一起」，而且100步
就有一點、越來越嚴重**——不是訓練步數太多，是從一開始就不穩定。

**根因分析**：VITS的loss權重設定裡，`mel_loss_alpha`預設高達45(其他
如`disc_loss_alpha`/`gen_loss_alpha`/`feat_loss_alpha`/`kl_loss_alpha`/
`dur_loss_alpha`都只有1.0)。mel重建loss是算在**decoder的輸出**上，
但即使`waveform_decoder`被凍結(參數不更新)，梯度仍然會沿著計算圖正常
往回傳(frozen只代表這個模組自己的參數不會被optimizer更新，不代表
它不參與backward)，經過frozen的decoder/flow一路傳回duration_predictor。
等於duration_predictor同時要承受：(1)沒有調降的discriminator全力
對抗梯度、(2)權重45倍、經過好幕層frozen模組間接傳來的mel reconstruction
梯度——這兩個都是「不是直接針對duration本身」的間接訊號，對一個只有
130萬參數、且是flow-based(StochasticDurationPredictor)的小模組來說，
訊號強度/來源都不成比例，這才是不穩定的根本原因，不是單純learning
rate的量級問題。

**修正(第二版)**：
1. `lr_gen`/`lr_disc`都再降更多(1/50、1/20)，降低整體梯度更新幅度。
2. **把跟frozen模組相關、間接傳導的loss權重大幅調低**(`mel_loss_alpha`
   45->5、`disc_loss_alpha`/`gen_loss_alpha`/`feat_loss_alpha`/
   `kl_loss_alpha`都調到0.1)，**保留`dur_loss_alpha`=1.0不變**。

第二版實測(2026-08-07)：100步時音檔健康(無NaN/爆音)但prosody指標
幾乎沒變化(幾乎沒學到東西)；250步時duration_predictor產生無效輸出，
直接讓合成崩潰(`generate_path`裡`IndexError: Dimension out of range`)。

## 根因分析修正：detach_dp_input本來就是True，第一版的假設是錯的(2026-08-07)

追查`TTS/tts/models/vits.py`原始碼(`forward()`/`forward_mas()`)才發現：
**這個模型的`config.model_args.detach_dp_input`本來就是`True`**，而且
訓練時用來擴展`m_p`/`logs_p`給reconstruction path(mel/GAN loss)用的
`attn`，是MAS(`maximum_path`)在`torch.no_grad()`區塊裡算出來的、
**本來就`.detach()`過**——duration_predictor的輸出根本不會進入
`z_slice`/`waveform_decoder`/`disc`這條路，訓練時duration_predictor
的參數**只會收到`loss_duration`(乘上`dur_loss_alpha`)這一個來源的
梯度**，跟mel/disc/gen/feat/kl loss完全無關。

也就是說：**第一版的根因分析(mel_loss_alpha=45間接污染duration_predictor)
是錯的**，這個間接路徑在VITS的架構設計裡本來就不存在。第二版調低那些
loss alpha，實際上沒有改到任何真正影響duration_predictor訓練的變數——
但依然在250步崩潰，代表：**真正的根因是別的東西**。同理，`lr_disc`
也不影響duration_predictor的穩定性(disc是獨立的判別器，跟duration_predictor
不共用參數、彼此的optimizer完全分開)，不需要特別調低。

## Round6設計(2026-08-07)：Adam bias correction假說+更細緻的診斷

使用者提出更精確的假說：Adam optimizer對全新初始化的optimizer state
(這裡的`best_model.pth`只有模型權重、沒有存optimizer state，每次
`Trainer`重建都是全新的momentum/variance估計)，在訓練初期(t很小)的
bias correction項`1/(1-β₂^t)`會放大有效步長，這個放大效果在小模組上
可能要累積到某個step數才會讓輸出跑出合理範圍，符合實測到的「100步
正常、250步突然崩潰」模式——不是漸進式的變差，是延遲的、突然的失控。

**這一輪的修正**：
1. **loss alpha全部改回預設值**(mel=45等)——第二版的調整基於錯誤的
   根因分析，既然detach_dp_input已經確保梯度隔離，這些alpha值不影響
   duration_predictor的訓練，改回預設值移除一個沒有必要的變數。
2. **`lr_gen`維持第一版的1/10(0.0002->0.00002)**，`lr_disc`維持預設
   (不影響duration_predictor，不需要動)。
3. **新增：generator optimizer套用300 steps的linear warmup**(用
   `torch.optim.lr_scheduler.LinearLR`，從基準LR的1%線性升到100%)，
   直接測試Adam早期偏差修正假說。
4. **`save_step`改成25**(比第二版的50更密)，搭配另外寫的診斷腳本，
   在每個checkpoint直接讀取duration_predictor對固定測試句的原始輸出
   (`logw`/`w`的min/max/mean/是否有NaN/Inf)，不透過完整的
   `generate_path`/decoder流程(避免診斷腳本本身被crash卡住)，才能
   精確定位「數值從哪一步開始跑偏」，不是只看最終合成結果崩不崩潰。
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
OUTPUT_PATH = "/Users/heisenberg/taigi-mt-project/models/finetune_runs/tat_moe_pilot_thf1001_dp_only"
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"

FROZEN_SUBMODULES = ("text_encoder", "posterior_encoder", "flow", "waveform_decoder")


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
    config.epochs = 7  # 7*79=553 steps，安全上限，實際跑到500步左右手動中止
    config.print_step = 10
    config.save_step = 25  # Round6：更密的checkpoint間隔，搭配診斷腳本定位數值跑偏的確切step
    config.save_n_checkpoints = 25
    config.save_best_after = 25
    config.eval_split_size = 0.05

    # Round6：loss alpha改回預設值(mel=45等)——第二版調低這些alpha是基於
    # 錯誤的根因分析(見上方module docstring「根因分析修正」)，
    # detach_dp_input=True已經確保duration_predictor的梯度只來自
    # loss_duration，這些alpha不影響它的訓練穩定性，改回預設值移除一個
    # 沒有必要的變數。lr_disc同理不影響duration_predictor，維持預設。
    config.lr_gen = config.lr_gen / 10  # 沿用第一版的設定(0.0002->0.00002)

    # Round6新增：generator optimizer(duration_predictor所在)套用300步
    # linear warmup，測試Adam bias correction在optimizer state全新初始化
    # 時放大早期有效步長的假說(見上方docstring「Round6設計」)
    config.lr_scheduler_gen = "LinearLR"
    config.lr_scheduler_gen_params = {"start_factor": 0.01, "end_factor": 1.0, "total_iters": 300}
    # 預設scheduler_after_epoch=True(每個epoch才step一次)，這裡300步的
    # warmup是指「訓練step數」不是「epoch數」，一定要改成False讓scheduler
    # 每個batch/step都呼叫一次，不然300 epochs warmup完全不是原本的意思。
    #
    # 這個flag是全域的，disc預設的ExponentialLR(gamma=0.999875)也會跟著
    # 從per-epoch改成per-step，衰減變快約75倍(500步約多衰減6%：
    # 0.999875^500≈0.939)——這不是這輪實驗想測的主要變數，但**曾經**
    # 嘗試用`lr_scheduler_disc=None`關掉它，結果讓checkpoint儲存直接
    # crash(`AttributeError: 'NoneType' object has no attribute
    # 'state_dict'`)：coqui-tts的`trainer/io.py`存checkpoint時對
    # scheduler列表裡每個元素直接呼叫`.state_dict()`，沒有處理None的
    # 情況。修掉這個crash需要額外引入一個no-op scheduler(例如
    # `LambdaLR(lr_lambda=lambda step: 1.0)`)才能繞過，但這是為了一個
    # 已知很小(~6%)的次要影響去多加一個機制，不划算——直接接受這個
    # 有明確量化過的小副作用，維持disc用預設scheduler，比另外引入
    # no-op scheduler更簡單。
    config.scheduler_after_epoch = False
    return config


def freeze_non_duration_modules(model) -> None:
    for name in FROZEN_SUBMODULES:
        submodule = getattr(model, name)
        for p in submodule.parameters():
            p.requires_grad = False

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"可訓練參數: {trainable:,} / {total:,} ({100*trainable/total:.1f}%)")


def main():
    print("torch:", torch.__version__)
    print(f"training device: {DEVICE}")

    config = build_config()
    print(f"lr_gen(已調低): {config.lr_gen}, lr_disc: {config.lr_disc}")

    model = Vits.init_from_config(config)
    model.load_checkpoint(config, f"{BASE_MODEL_DIR}/best_model.pth", eval=False, strict=False)
    freeze_non_duration_modules(model)
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
