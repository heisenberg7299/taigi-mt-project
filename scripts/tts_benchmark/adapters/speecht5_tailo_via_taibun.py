"""
speecht5_tailo-hokkien 只吃Tâi-lô輸入（見 reports/stage4_tts_candidates.md 的
實測結論）。這個adapter在前面加一層 taibun（Hanji→Tâi-lô轉換套件，MIT授權，
詞典CC-BY-SA-4.0）當frontend，讓它可以吃台語漢字。

刻意只用taibun一個轉換工具，不疊加教育部辭典覆寫或臺灣言語工具正規化——
先確認單一工具夠不夠用，避免多個G2P來源互相打架、結果來源說不清楚。
如果taibun品質不夠，才考慮加辭典覆寫當第二層（見報告的分階段計畫）。

用 TLPA（數字標調，如 "su1-iau3"）而不是 taibun 預設的 Tailo（符號標調，
如 "su-iàu"）：開發者實測比較過符號標調版本「最爛」，早期用手打數字調羅馬字
測試時「除了音調不準，唸得還可以」，研判checkpoint訓練時可能用數字調格式。
但改用TLPA後開發者再聽一次，結論是「不太行」——沒有解決問題，代表標調格式
不是主要瓶頸，真正的瓶頸是checkpoint本身規模小、加上沒有真正的台語語者
embedding（見報告「開發者快聽」章節的完整結論）。
"""
from .base import TTSAdapter
from .speecht5_tailo import SpeechT5TailoAdapter


class TaibunFrontend:
    def __init__(self):
        from taibun import Converter
        self.converter = Converter(system="TLPA")

    def convert(self, text: str) -> str:
        result = self.converter.get(text)
        if not result or not result.strip():
            raise ValueError(f"taibun轉換回傳空字串，原文：{text!r}")
        return result


class SpeechT5TailoViaTaibunAdapter(TTSAdapter):
    name = "speecht5_tailo_via_taibun"
    input_format = "han"
    required_frontend = "taibun_g2p"
    license = "mit（taibun程式碼）+ cc-by-sa-4.0（taibun詞典）+ mit（speecht5_tailo checkpoint）"

    def load(self):
        self.frontend = TaibunFrontend()
        self.backend = SpeechT5TailoAdapter()
        self.backend.load()

    def synthesize(self, text: str):
        tailo_text = self.frontend.convert(text)
        self.last_frontend_output = tailo_text  # runner會把這個記進結果，方便追溯taibun實際轉出什麼
        return self.backend.synthesize(tailo_text)
