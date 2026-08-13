#!/bin/sh
# Restart the app on the current code, and prove which build answered.
set -e
for p in $(pgrep -f "python3 -m webapp.server --port 8079" 2>/dev/null); do kill -9 "$p" 2>/dev/null || true; done
sleep 2
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" setsid nohup python3 -m webapp.server --port 8079 > "$1" 2>&1 < /dev/null &
sleep 11
curl -s -m 5 localhost:8079/api/catalog > /dev/null || { echo "SERVER DID NOT START"; tail -5 "$1"; exit 1; }
echo "serving:"; grep -E "^  build:|Build Assistant app" "$1"
echo "expected: $(git log -1 --format='%h %s')"
