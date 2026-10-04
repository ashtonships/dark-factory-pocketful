#!/bin/sh
# Runs browser-drill.js against devstub.py, or, with UPSTREAM set, against a
# real service through faultproxy.py. Picks a free port and stops what it starts.
#   PW_MODULES=<node_modules containing playwright-core> [UPSTREAM=http://127.0.0.1:18080] ui-core/run-drill.sh [shots-dir]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
if [ -n "${UPSTREAM:-}" ]; then
  python3 "$HERE/faultproxy.py" --port "$PORT" --upstream "$UPSTREAM" >/tmp/pocketful-faultproxy.log 2>&1 &
else
  python3 "$HERE/devstub.py" --port "$PORT" >/tmp/pocketful-devstub.log 2>&1 &
fi
HELPER=$!
trap 'kill $HELPER 2>/dev/null' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/health" && break
  sleep 0.3
done
NODE_PATH="${PW_MODULES:-}" node "$HERE/browser-drill.js" "http://127.0.0.1:$PORT" "${1:-}"
