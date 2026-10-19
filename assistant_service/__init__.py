"""
Response Controller 架構：大腦(意圖+RAG+LLM) -> 結構化JSON(BrainResponse)
-> Response Controller(風險判斷+安全閘門) -> tw_hokkien_tts_pipeline(安全
翻譯) -> TTS Router(neurlang即時/MERaLiON快取) -> 播放語音。

見 README.md 完整流程圖跟各模組說明。這個套件刻意獨立於
`tw_hokkien_tts_pipeline/`(那是翻譯安全pipeline本身)，因為Response
Controller/TTS Router處理的是「大腦輸出要不要講、怎麼決定用哪個TTS」，
是更上層的服務邏輯，不是翻譯pipeline的一部分。
"""
