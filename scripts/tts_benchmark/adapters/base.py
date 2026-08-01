"""
所有TTS候選的共同介面。新增候選模型只要寫一個繼承這個類別的adapter，
不用碰 runner.py 或 metrics.py——這是這次要建的「同一條淘汰漏斗」的核心。
"""


class TTSAdapter:
    name: str = "unnamed"
    input_format: str = "han"  # "han" / "tailo" / "zh" / "en" / "mixed" / "multi"
    required_frontend: str = "none"  # "none" / "hanji_to_tailo_g2p" / ...
    license: str = "unknown"

    def load(self):
        """載入模型，開銷大的初始化都放這裡，只呼叫一次。"""
        raise NotImplementedError

    def synthesize(self, text: str):
        """回傳 (samples: np.ndarray, sample_rate: int)。
        失敗時直接raise exception，runner會接住並記錄成 fail_error。"""
        raise NotImplementedError
