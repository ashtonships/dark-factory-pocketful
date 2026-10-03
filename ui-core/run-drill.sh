#!/bin/sh
# Starts devstub.py on a free port, runs browser-drill.js against it, stops the stub.
#   PW_MODULES=<node_modules containing playwright-core> ui-core/run-drill.sh [shots-dir]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
python3 "$HERE/devstub.py" --port "$PORT" >/tmp/pocketful-devstub.log 2>&1 &
STUB=$!
trap 'kill $STUB 2>/dev/null' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/_test/export" && break
  sleep 0.3
done
NODE_PATH="${PW_MODULES:-}" node "$HERE/browser-drill.js" "http://127.0.0.1:$PORT" "${1:-}"
