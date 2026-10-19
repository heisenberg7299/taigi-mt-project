# ChhoeTaigi 台華線頂對照典

這個目錄故意是空的（只有這份README）。實際的CSV（91,339筆詞條）沒有隨repo
提供，因為這個沙盒開發環境的Bash工具沒有對外網路存取權限，需要在有網路的
環境下手動下載一次：

```bash
curl -L -o data/raw/chhoetaigi_taihoa_dict/ChhoeTaigi_TaihoaSoanntengTuichiautian.csv \
  https://raw.githubusercontent.com/ChhoeTaigi/ChhoeTaigiDatabase/master/ChhoeTaigiDatabase/ChhoeTaigi_TaihoaSoanntengTuichiautian.csv
```

下載完成後：
- `tw_hokkien_tts_pipeline/taihoa_dict_loader.py` 的 `DEFAULT_CSV_PATH` 就會指向這個檔案，`load_taihoa_dict()` 可以直接載入。
- `tw_hokkien_tts_pipeline/segment.py` 的 `RealSegmentationBackend`（`config.segmentation_backend = "real"`）會在建構時載入這份詞庫。

授權、來源、已知限制見 `data/licenses/chhoetaigi_taihoa_dict.json`（CC BY-SA 4.0，基礎資料由鄭良偉教授提供）。

下載後建議先跑一次全量健檢，確認欄位格式跟這次整合時查證的樣本資料一致、
沒有因為版本更新而變動：

```bash
python3 -c "
from tw_hokkien_tts_pipeline.taihoa_dict_loader import load_taihoa_dict_with_stats
lexicon, stats = load_taihoa_dict_with_stats()
print(stats)
print('sample:', list(lexicon.items())[:5])
"
```
