"""
資源盤點與下載腳本。
每份資料下載後，同時在 data/licenses/ 寫一份授權紀錄，
避免未來忘記某份資料的授權條件就直接拿去用。

執行：python scripts/download_datasets.py
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, timezone, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
LICENSES = os.path.join(ROOT, "data", "licenses")


def record_license(name, license_str, category, url, notes=""):
    os.makedirs(LICENSES, exist_ok=True)
    path = os.path.join(LICENSES, f"{name}.json")
    with open(path, "w") as f:
        json.dump({
            "name": name,
            "license": license_str,
            "category": category,  # internal_ok / nc_only / review_needed
            "source_url": url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }, f, ensure_ascii=False, indent=2)
    print(f"  授權紀錄已寫入: {path}")


def download_moe_dictionary():
    print("[1/3] 教育部臺灣台語常用詞辭典 (g0v/moedict-data-twblg)")
    dest_dir = os.path.join(RAW, "moe_dictionary")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "dict-twblg.json")
    if os.path.exists(dest):
        print(f"  已存在，略過: {dest}")
    else:
        url = "https://raw.githubusercontent.com/g0v/moedict-data-twblg/master/dict-twblg.json"
        urllib.request.urlretrieve(url, dest)
        print(f"  下載完成: {dest}")
    record_license(
        "moe_dictionary",
        "open (g0v moedict-data-twblg，未明確標註單一授權，屬公開資料整理)",
        "internal_ok",
        "https://github.com/g0v/moedict-data-twblg",
        "教育部官方辭典資料，g0v 社群整理成 JSON。適合當辭典約束/術語檢查用，不可直接逐詞替換當翻譯引擎。",
    )


def download_hf_dataset(repo_id, dest_name, license_str, category, notes=""):
    print(f"[hf] {repo_id}")
    dest_dir = os.path.join(RAW, dest_name)
    os.makedirs(dest_dir, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=repo_id, repo_type="dataset", local_dir=dest_dir)
        print(f"  下載完成: {dest_dir}")
    except Exception as e:
        print(f"  下載失敗（可能需要 huggingface_hub 套件，或該資料集需要登入/授權同意）: {e}")
        return
    record_license(
        dest_name,
        license_str,
        category,
        f"https://huggingface.co/datasets/{repo_id}",
        notes,
    )


def main():
    os.makedirs(RAW, exist_ok=True)
    download_moe_dictionary()

    print("\n[2/3] Bohanlu/iCorpus-100")
    download_hf_dataset(
        "Bohanlu/iCorpus-100",
        "icorpus100",
        "cc-by-nc-4.0",
        "nc_only",
        "iCorpus 完整版的 100 句子集，僅供研究測試 pipeline，不可用於商用模型訓練。完整 iCorpus 取得方式待確認。",
    )

    print("\n[3/3] TaigiSpeech/TaigiSpeech")
    download_hf_dataset(
        "TaigiSpeech/TaigiSpeech",
        "taigispeech",
        "cc-by-4.0",
        "internal_ok",
        "3,079筆台語語音、21位語者、8種服務/緊急意圖分類。適合方向1（台語語音->意圖分類），非翻譯語料。",
    )

    print("\n完成。請檢查 data/licenses/ 底下的授權紀錄，並在使用任何 nc_only 資料前確認用途是否為研究/非商業。")


if __name__ == "__main__":
    main()
