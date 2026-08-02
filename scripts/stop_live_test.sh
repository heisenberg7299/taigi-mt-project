#!/bin/bash
# 關閉 start_live_test.sh 啟動的所有元件。watchdog要先關，不然它偵測到
# tunnel斷線會自動重啟。Ollama不歸這裡管，不會被關掉。
#
# 執行：bash scripts/stop_live_test.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

for name in watchdog gateway meralion neurlang; do
    pidfile="/tmp/taigi_live_test_${name}.pid"
    if [ -f "$pidfile" ]; then
        kill "$(cat "$pidfile")" 2>/dev/null
        rm -f "$pidfile"
    fi
done

sleep 1
pkill -f "cloudflared tunnel --url http://localhost:5002" 2>/dev/null
rm -f CURRENT_TUNNEL_URL.txt

echo "已關閉 live_test 平台（neurlang後端、MERaLiON後端、gateway、tunnel）"
