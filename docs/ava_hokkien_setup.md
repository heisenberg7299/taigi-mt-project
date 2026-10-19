# 台語模型 + 醫療知識庫 Setup 清單（給 ava）

範圍：只涵蓋「台語發音消歧 + 台語語音輸出」跟「醫療RAG知識庫」這兩塊，
不包含語音辨識/鏡頭手勢/多語大腦那些其他功能。

## 0. 前置：取得 repo 存取權限

這是私有 repo，需要 heisenberg7299 先把你加成 GitHub collaborator，
再 clone：

```bash
git clone https://github.com/heisenberg7299/taigi-mt-project.git
cd taigi-mt-project
git checkout feat/hokkien-pipeline-skeleton
```

## 1. Python 環境

```bash
python3 -m venv venv
source venv/bin/activate
pip install coqui-tts[codec] "transformers<5"   # neurlang TTS 要用
pip install requests numpy pytest               # pipeline核心依賴
```

**注意**：MERaLiON（另一個音質較好但慢35倍的TTS引擎）需要 `transformers>=5.3.0`，
跟上面這組版本互斥，必須另外開一個獨立 venv（`venv_meralion`）才能同時用兩個引擎。
只要台語發音/合成這塊的話，上面這組 venv 就夠了，MERaLiON 是選用。

## 2. 下載 neurlang TTS 模型權重（必要，~1GB，沒進 git）

```bash
mkdir -p models/neurlang-vits-suisiann
curl -L -o models/neurlang-vits-suisiann/config.json \
  https://huggingface.co/neurlang/coqui-vits-suisiann-minnan-hokkien/resolve/main/config.json
curl -L -o models/neurlang-vits-suisiann/best_model.pth \
  https://huggingface.co/neurlang/coqui-vits-suisiann-minnan-hokkien/resolve/main/best_model.pth
```

## 3. 下載 ChhoeTaigi 台語辭典（必要，~10MB，發音消歧用）

```bash
curl -L -o data/raw/chhoetaigi_taihoa_dict/ChhoeTaigi_TaihoaSoanntengTuichiautian.csv \
  https://raw.githubusercontent.com/ChhoeTaigi/ChhoeTaigiDatabase/master/ChhoeTaigiDatabase/ChhoeTaigi_TaihoaSoanntengTuichiautian.csv
```

授權/來源說明見 `data/licenses/chhoetaigi_taihoa_dict.json`。

## 4. Ollama（中文→台語翻譯模型）

```bash
# 安裝 ollama（如果還沒裝）：https://ollama.com
ollama serve &
ollama pull hf.co/RichardErkhov/Bohanlu_-_Taigi-Llama-2-Translator-7B-gguf:Q4_K_M
```

授權是 CC-BY-NC-SA-4.0（非商業），詳見 `data/licenses/taigi-llama-2-translator-7b.json`。

如果你還要用到醫療知識庫(RAG)那條路（見第6節），額外再拉一個通用對話模型：

```bash
ollama pull qwen2.5:7b-instruct
```

## 5. 啟動台語語音合成服務

```bash
source venv/bin/activate
TTS_BACKEND=neurlang python3 live_test/tts_backend.py   # 內部port 5010
```

跑起來後可以用這個網站直接測試「中文輸入→台語翻譯→台語語音」：

```bash
python3 live_test/app.py   # 另開一個終端機，port 5002
```

瀏覽器開 http://127.0.0.1:5002。

## 6. 發音消歧機制（這學期的核心研究成果）

台語漢字一字多音的問題，已經接進 `live_test/tts_backend.py` 的合成路徑：

- `tw_hokkien_tts_pipeline/chhoetaigi_pronunciation_resolver.py`：即時查詢
  ChhoeTaigi辭典（第3步下載的那份CSV）+ 這學期做的母語者盲測黃金標準，
  決定每個多音字該念哪個讀音。決策順序：黃金標準已驗證答案 > 辭典多數決 >
  辭典唯一讀音。
- 黃金標準資料在 `tw_hokkien_tts_pipeline/tests/data/ambiguity_gold_benchmark_v1.jsonl`
  跟 `..._v2_in_corpus.jsonl`，已經有40+筆真人驗證過的答案。
- `tw_hokkien_tts_pipeline/pronunciation_overrides.py`：另一張獨立的發音修正表
  （來源是教育部TAT-MOE語料庫統計，118字），這個跟上面的黃金標準是兩條不同
  方法互相交叉驗證過的，詳見 `reports/pronunciation_overrides_crosscheck.md`。

不需要額外設定，第2步下載好模型、第5步啟動服務後這個機制就會自動生效。

## 7. 醫療知識庫（RAG，防止LLM醫療幻覺）

`assistant_service/medical_kb.py`：純Python檔案，**不需要額外下載任何東西**，
已經隨git一起拉下來了。內容是查證過來源的公共衛生常識（血壓/血糖/中風/
發燒/闌尾炎警訊等20幾筆，每條後面都附來源網址：衛福部/國健署/AHA/ADA/
美國中風協會）。

這只是個獨立的查詢模組，本身不需要跑任何服務；要看到它實際影響LLM回覆的
效果，需要連上第4節裝好的 `qwen2.5:7b-instruct`，然後跑完整的
`assistant_service` 整合服務（那是另一塊範圍更大的設定，不在這份清單內，
需要的話另外說一聲）。

單獨測試這個模組本身：

```bash
source venv/bin/activate
python3 -c "
from assistant_service.medical_kb import MedicalKnowledgeBase
kb = MedicalKnowledgeBase()
results = kb.search('血壓正常值是多少')
for r in results:
    print(r.id, r.answer)
"
```

## 驗證安裝成功

```bash
source venv/bin/activate
python3 -m pytest tw_hokkien_tts_pipeline/tests/test_pronunciation_overrides.py \
  assistant_service/tests/test_medical_kb.py -v
```

（`chhoetaigi_pronunciation_resolver.py`本身目前沒有獨立的pytest檔案，是
靠第6節那段手動腳本驗證過；跑TTS真實合成的smoke test需要models/權重跟
coqui-tts都裝好才會真的執行，沒裝好會自動skip，不會fail。）
