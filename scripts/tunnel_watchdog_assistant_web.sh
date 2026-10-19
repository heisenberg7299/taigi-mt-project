#!/bin/bash
# 監控assistant_service/web/app.py(整合驗證網站, port 5020)的cloudflared
# tunnel，斷線自動重啟，網址寫進固定檔案CURRENT_TUNNEL_URL_ASSISTANT_WEB.txt
# 方便隨時查詢，不用等人手動發現斷線才處理。
#
# 跟scripts/tunnel_watchdog.sh(監控live_test/app.py, port 5002)是同樣的
# 邏輯、分開的檔案，避免兩個tunnel共用同一個URL檔案互相覆蓋。
#
# 執行：nohup bash scripts/tunnel_watchdog_assistant_web.sh > tunnel_watchdog_assistant_web.log 2>&1 &

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOUDFLARED=$(command -v cloudflared || echo /opt/homebrew/bin/cloudflared)
PORT=5020
LOGFILE="$ROOT/cloudflared_assistant_web.log"
URLFILE="$ROOT/CURRENT_TUNNEL_URL_ASSISTANT_WEB.txt"
CHECK_INTERVAL=60

start_tunnel() {
    pkill -f "cloudflared tunnel --url http://localhost:$PORT" 2>/dev/null
    sleep 2
    nohup "$CLOUDFLARED" tunnel --url "http://localhost:$PORT" > "$LOGFILE" 2>&1 &
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
