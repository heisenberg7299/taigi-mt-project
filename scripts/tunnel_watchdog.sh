#!/bin/bash
# 監控 cloudflared tunnel，斷線自動重啟，目前網址寫進固定檔案 CURRENT_TUNNEL_URL.txt
# 方便隨時查詢，不用等人手動發現斷線才處理。
#
# 對外開放的是 live_test/app.py 這個gateway（本機測試平台，不是docs/驗證平台
# ——那個已經在GitHub Pages上，不需要靠這台Mac開著）。
#
# 執行：nohup bash scripts/tunnel_watchdog.sh > tunnel_watchdog.log 2>&1 &
# （一般不用手動跑這個，scripts/start_live_test.sh 會自動啟動）

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUDFLARED=/opt/homebrew/opt/cloudflared/bin/cloudflared
LOGFILE="$ROOT/cloudflared.log"
URLFILE="$ROOT/CURRENT_TUNNEL_URL.txt"
CHECK_INTERVAL=60

start_tunnel() {
    pkill -f "cloudflared tunnel --url" 2>/dev/null
    sleep 2
    nohup "$CLOUDFLARED" tunnel --url http://localhost:5002 > "$LOGFILE" 2>&1 &
    URL=""
    for i in $(seq 1 10); do
        URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOGFILE" | tail -1)
        [ -n "$URL" ] && break
        sleep 2
    done
    if [ -n "$URL" ]; then
        echo "$URL" > "$URLFILE"
        echo "$(date '+%Y-%m-%d %H:%M:%S') 啟動/重啟tunnel -> $URL"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') 啟動失敗，沒拿到網址，稍後重試"
    fi
}

start_tunnel

while true; do
    sleep "$CHECK_INTERVAL"
    URL=$(cat "$URLFILE" 2>/dev/null)
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "${URL}/" 2>/dev/null)
    if [ -z "$URL" ] || [ "$STATUS" != "200" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 偵測到tunnel失效（狀態碼:$STATUS），重啟中..."
        start_tunnel
    fi
done
