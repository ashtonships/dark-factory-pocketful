#!/usr/bin/env python3
"""Fault-injecting HTTP proxy for driving the screens against the real service.

Dev tooling only, not part of any stage. Forwards every request to the
upstream service unchanged and applies the same faults as devstub.py, so
browser-drill.js can run against a real stage container:

    python3 ui-core/faultproxy.py --port 9000 --upstream http://127.0.0.1:18080

    --ui-upstream URL  serve pages and /ui/ assets from URL while API calls go
                       to --upstream (switchable), for stage-1 -> stage-2 upgrades:
    POST /_dev/upstream {"api": "http://127.0.0.1:18097"}
    POST /_dev/faults  {"rules": [{"method": "POST", "path": "/payments",
                                   "action": "drop_after_commit" | "drop_before" | "delay" | "replace_body",
                                   "ms": 1500, "body": "null", "times": 1}]}
"""
import argparse
import http.client
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

FAULTS = []
LOCK = threading.Lock()
UPSTREAM = {}
UI_UPSTREAM = {}
PAGES = {"/", "/requests", "/split", "/signup", "/login", "/authorizations"}
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-connection", "host", "content-length"}


def take_fault(method, path):
    with LOCK:
        for rule in FAULTS:
            if rule.get("method", method) == method and rule.get("path") == path and rule.get("times", 1) > 0:
                rule["times"] = rule.get("times", 1) - 1
                return dict(rule)
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = urlsplit(self.path).path
        if self.command == "POST" and path == "/_dev/faults":
            with LOCK:
                FAULTS[:] = json.loads(raw or b"{}").get("rules", [])
            return self.reply(200, {"Content-Type": "application/json"}, json.dumps({"rules": FAULTS}).encode())
        if self.command == "POST" and path == "/_dev/upstream":
            u = urlsplit(json.loads(raw or b"{}")["api"])
            with LOCK:
                UPSTREAM.update(host=u.hostname, port=u.port or 80)
            return self.reply(200, {"Content-Type": "application/json"}, json.dumps(UPSTREAM).encode())
        target = UPSTREAM
        if UI_UPSTREAM and self.command == "GET" and (path.startswith("/ui/") or
                                                      (path in PAGES and "text/html" in self.headers.get("Accept", ""))):
            target = UI_UPSTREAM
        fault = take_fault(self.command, path)
        if fault and fault.get("action") == "drop_before":
            return self.drop()
        conn = http.client.HTTPConnection(target["host"], target["port"], timeout=15)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["Content-Length"] = str(len(raw))
        try:
            conn.request(self.command, self.path, body=raw, headers=headers)
            res = conn.getresponse()
            body = res.read()
            status, res_headers = res.status, [(k, v) for k, v in res.getheaders() if k.lower() not in HOP]
        except (OSError, http.client.HTTPException) as e:
            return self.reply(502, {"Content-Type": "application/json"},
                              json.dumps({"error": {"code": "bad_gateway", "message": str(e)}}).encode())
        finally:
            conn.close()
        action = fault.get("action") if fault else None
        if action == "drop_after_commit":
            # Upstream committed; the client gets headers promising a body that never arrives.
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", "4096")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            return self.drop()
        if action == "replace_body":
            return self.reply(status, {"Content-Type": "application/json; charset=utf-8"}, fault.get("body", "").encode())
        if action == "delay":
            time.sleep(fault.get("ms", 1000) / 1000.0)
        self.reply(status, dict(res_headers), body)

    def reply(self, status, headers, body):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def drop(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--ui-upstream")
    args = ap.parse_args()
    u = urlsplit(args.upstream)
    UPSTREAM.update(host=u.hostname, port=u.port or 80)
    if args.ui_upstream:
        v = urlsplit(args.ui_upstream)
        UI_UPSTREAM.update(host=v.hostname, port=v.port or 80)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("faultproxy on http://127.0.0.1:%d -> %s" % (args.port, args.upstream), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
