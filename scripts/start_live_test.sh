#!/bin/bash
# 一鍵啟動開發者即時測試平台的所有元件：兩個TTS後端(各自獨立venv) +
# gateway + 對外cloudflared tunnel(斷線自動重啟)。Ollama要自己另外先開
# （因為它是常駐服務，不是這個平台專屬的）。
#
# 啟動：bash scripts/start_live_test.sh
# 關閉：bash scripts/stop_live_test.sh
# 細節說明見 README.md「開發者即時測試工具」章節。

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! curl -s --max-time 3 http://localhost:11434/api/tags > /dev/null; then
    echo "錯誤：Ollama沒有在跑，請先另開一個終端機執行：ollama serve"
    exit 1
fi

echo "啟動 neurlang TTS 後端..."
source venv/bin/activate
TTS_BACKEND=neurlang nohup python3 live_test/tts_backend.py > live_test_neurlang.log 2>&1 &
echo $! > /tmp/taigi_live_test_neurlang.pid

echo "啟動 MERaLiON TTS 後端（比較慢，第一次載入模型要等一下）..."
source venv_meralion/bin/activate
TTS_BACKEND=meralion nohup python3 live_test/tts_backend.py > live_test_meralion.log 2>&1 &
echo $! > /tmp/taigi_live_test_meralion.pid

echo "等待兩個TTS後端準備好..."
for i in $(seq 1 60); do
    n_ok=$(curl -s --max-time 2 http://127.0.0.1:5010/health 2>/dev/null | grep -c '"ok"' || true)
    m_ok=$(curl -s --max-time 2 http://127.0.0.1:5011/health 2>/dev/null | grep -c '"ok"' || true)
    if [ "$n_ok" -ge 1 ] && [ "$m_ok" -ge 1 ]; then
        break
    fi
    sleep 3
done
if [ "$n_ok" -lt 1 ] || [ "$m_ok" -lt 1 ]; then
    echo "警告：等太久了，TTS後端可能還沒準備好，檢查 live_test_neurlang.log / live_test_meralion.log"
fi

echo "啟動 gateway..."
source venv/bin/activate
nohup python3 live_test/app.py > live_test_gateway.log 2>&1 &
echo $! > /tmp/taigi_live_test_gateway.pid
sleep 2

echo "啟動對外連線用的cloudflared tunnel（含斷線自動重啟監控）..."
nohup bash scripts/tunnel_watchdog.sh > tunnel_watchdog.log 2>&1 &
echo $! > /tmp/taigi_live_test_watchdog.pid
sleep 8

echo ""
echo "======================================"
echo "全部啟動完成"
echo "本機瀏覽器：http://127.0.0.1:5002"
echo "其他裝置（含外部網路）：$(cat CURRENT_TUNNEL_URL.txt 2>/dev/null || echo '（tunnel還在建立，稍後執行: cat CURRENT_TUNNEL_URL.txt）')"
echo "要關閉全部：bash scripts/stop_live_test.sh"
echo "======================================"
