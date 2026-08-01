"""
階段4 TTS候選統一測試集。固定輸入，讓所有候選模型都跑同一批，
結果才能互相比較（不同模型測不同句子沒有比較意義）。

每個 item 只有一種格式（漢字/Tâi-lô/華語/英文/中英台混合），
跑的時候只挑跟該候選 adapter.input_format 相容的item。

注意：tailo欄位的羅馬字是專案內部土法拼音，未經母語者校對，
只用來測試「模型有沒有正常發出語音」，不代表正確的台羅拼音。
"""

BENCHMARK_ITEMS = [
    # ---- 台語漢字 ----
    {"id": "han_01", "category": "台語漢字", "format": "han",
     "text": "我需要啉水。"},
    {"id": "han_02", "category": "台語漢字", "format": "han",
     "text": "請共我叫護理師。"},

    # ---- Tâi-lô 羅馬字（未經校對，僅供技術煙霧測試） ----
    {"id": "tailo_01", "category": "Tâi-lô", "format": "tailo",
     "text": "Gua2 su1-iau3 lim1 tsui2."},
    {"id": "tailo_02", "category": "Tâi-lô", "format": "tailo",
     "text": "Chhiann2 ka7 gua2 kio3 ho7-li2-su1."},

    # ---- 繁體華語 ----
    {"id": "zh_01", "category": "繁體華語", "format": "zh",
     "text": "我需要喝水。"},
    {"id": "zh_02", "category": "繁體華語", "format": "zh",
     "text": "現在幾點了？"},

    # ---- 英文 ----
    {"id": "en_01", "category": "英文", "format": "en",
     "text": "I need to drink some water, please."},
    {"id": "en_02", "category": "英文", "format": "en",
     "text": "Could you please call the nurse for me?"},

    # ---- 中英台混合 ----
    {"id": "mixed_01", "category": "中英台混合", "format": "mixed",
     "text": "幫我叫 nurse 過來。"},
    {"id": "mixed_02", "category": "中英台混合", "format": "mixed",
     "text": "我欲去 restroom 一下。"},

    # ---- 數字/病房號/醫療詞彙 ----
    {"id": "num_01", "category": "數字病房號醫療詞彙", "format": "han",
     "text": "請共我叫三號病房的護理師。"},
    {"id": "num_02", "category": "數字病房號醫療詞彙", "format": "han",
     "text": "我這馬血壓一二零，體溫三十六度五。"},

    # ---- 否定句與較長句 ----
    {"id": "neg_01", "category": "否定與較長句", "format": "han",
     "text": "我無胸疼，煩勞你共我確認一下這禮拜愛食的藥仔有偌濟種。"},
    {"id": "neg_02", "category": "否定與較長句", "format": "han",
     "text": "我猶未做檢查，毋過我這幾工攏無食藥仔，會使先毋通叫醫生無？"},
]


def items_for_format(fmt: str):
    """回傳跟某個input_format相容的測試項目。
    fmt="multi" 的候選（原生支援多種格式）會拿到全部item。"""
    if fmt == "multi":
        return list(BENCHMARK_ITEMS)
    return [it for it in BENCHMARK_ITEMS if it["format"] == fmt]
