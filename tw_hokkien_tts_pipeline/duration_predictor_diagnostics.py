"""直接探測VITS duration predictor的原始輸出(不透過完整的
`generate_path`/decoder流程)，用來在訓練不穩定、合成會crash的情況下，
還能拿到診斷數據，定位「數值從哪一步開始跑偏」。

## 背景

`tw_hokkien_tts_pipeline/finetune_train_dp_only.py`(DP-only微調實驗)
第一、二版都在某個訓練step之後讓duration predictor產生無效輸出，
導致完整合成路徑(`Vits.inference()`裡的`generate_path`)直接crash
(`IndexError`)。如果只能透過「完整合成成不成功」來判斷，沒辦法區分
是漸進式跑偏還是某一步突然爆掉，也沒辦法在crash之後繼續往後面的
checkpoint看訓練軌跡。

這個模組複製`Vits.inference()`裡`text_encoder`->`duration_predictor`
->`w = exp(logw) * x_mask * length_scale`這一段(見該檔案`inference()`
方法)，在`torch.ceil(w)`+`generate_path`(真正會crash的地方)**之前**
就回傳統計數據，讓探測本身不會被下游的crash卡住。

**重要：StochasticDurationPredictor的`reverse=True`推論模式本身有
隨機性**(內部從高斯雜訊取樣，`noise_scale`控制取樣的雜訊量)，同一個
checkpoint、同一句話，每次呼叫`probe_duration_predictor()`都可能拿到
不同的`logw`/`w`——開發過程實測發現，對已知會crash的checkpoint單次
探測，抓到的數值完全正常，因為剛好沒抽到會觸發crash的那個雜訊樣本。
所以`probe_duration_predictor_multi()`會重複探測多次、回傳「最壞情況」
統計(而不是只探測一次就下結論)，這樣才能量到「這個checkpoint有多容易
抽到異常輸出」，不是只看運氣。
"""

from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass
class DurationProbeResult:
    text: str
    logw_min: float
    logw_max: float
    logw_mean: float
    w_min: float
    w_max: float
    w_mean: float
    has_nan: bool
    has_inf: bool


@torch.inference_mode()
def probe_duration_predictor(model, text: str) -> DurationProbeResult:
    """對`text`跑`text_encoder`+`duration_predictor`，回傳`logw`/`w`的
    統計數據。`model`是`Synthesizer.tts_model`(`Vits`實例)。
    """
    text_inputs = model.tokenizer.text_to_ids(text)
    x = torch.as_tensor(text_inputs, dtype=torch.long, device=next(model.parameters()).device).unsqueeze(0)
    x_lengths = torch.tensor(x.shape[1:2], device=x.device)

    x_enc, m_p, logs_p, x_mask = model.text_encoder(x, x_lengths, lang_emb=None)

    if model.args.use_sdp:
        logw = model.duration_predictor(
            x_enc,
            x_mask,
            g=None,
            reverse=True,
            noise_scale=model.inference_noise_scale_dp,
            lang_emb=None,
        )
    else:
        logw = model.duration_predictor(x_enc, x_mask, g=None, lang_emb=None)

    w = torch.exp(logw) * x_mask * model.length_scale

    return DurationProbeResult(
        text=text,
        logw_min=float(logw.min()),
        logw_max=float(logw.max()),
        logw_mean=float(logw.mean()),
        w_min=float(w.min()),
        w_max=float(w.max()),
        w_mean=float(w.mean()),
        has_nan=bool(torch.isnan(logw).any() or torch.isnan(w).any()),
        has_inf=bool(torch.isinf(logw).any() or torch.isinf(w).any()),
    )


@dataclass
class DurationProbeWorstCase:
    text: str
    n_samples: int
    w_min_across_samples: float
    w_max_across_samples: float
    any_nan: bool
    any_inf: bool
    n_samples_with_nan_or_inf: int


def probe_duration_predictor_multi(model, text: str, n_samples: int = 10) -> DurationProbeWorstCase:
    """`probe_duration_predictor()`因為stochastic duration predictor的
    隨機性，單次探測可能剛好沒抽到異常樣本(見module docstring)，這裡
    重複探測`n_samples`次、回傳最壞情況統計。
    """
    w_mins, w_maxs = [], []
    bad_count = 0
    for _ in range(n_samples):
        result = probe_duration_predictor(model, text)
        w_mins.append(result.w_min)
        w_maxs.append(result.w_max)
        if result.has_nan or result.has_inf:
            bad_count += 1

    return DurationProbeWorstCase(
        text=text,
        n_samples=n_samples,
        w_min_across_samples=min(w_mins),
        w_max_across_samples=max(w_maxs),
        any_nan=bad_count > 0,
        any_inf=bad_count > 0,
        n_samples_with_nan_or_inf=bad_count,
    )
