#!/usr/bin/env python3
"""Pocketful development stub for the ui-core screens (W-6).

NOT part of any stage and not the product: an in-memory stand-in for the
stage-1 + stage-2 API, good enough to drive the screens in a real browser,
plus fault injection so lost responses and out-of-order reads can be
exercised. Passwords are kept in plain text here; the real service hashes.

    python3 ui-core/devstub.py [--port 8080]

Routes served like the real service will need to serve them:
    GET /, /requests, /split, /signup, /login, /authorizations   (Accept: text/html)
    GET /ui/<file>                                                (static assets)
Dev-only controls:
    POST /_dev/faults  {"rules": [{"method": "POST", "path": "/payments",
                                   "action": "drop_after_commit" | "drop_before" | "delay" | "replace_body",
                                   "ms": 1500, "body": "null", "times": 1}]}
    POST /_dev/clock   {"advance_seconds": 700}
    GET  /_test/export, POST /_test/import (whole-state copy, for upgrade drills)
"""
import argparse
import copy
import datetime as dt
import json
import os
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = {
    "/": "index.html",
    "/requests": "requests.html",
    "/split": "split.html",
    "/signup": "signup.html",
    "/login": "login.html",
    "/authorizations": "authorizations.html",
}
STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".html": "text/html; charset=utf-8"}

LOCK = threading.RLock()
STATE = {}
FAULTS = []
CLOCK = {"offset": 0.0}


class ApiError(Exception):
    def __init__(self, status, code, message=""):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message or code


def now():
    return time.time() + CLOCK["offset"]


def iso(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).isoformat()


def parse_iso(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def empty_state():
    return {"currency": "EUR", "minor_units": 2, "ttl": 600, "users": {}, "tokens": {},
            "payments": [], "requests": {}, "auths": {}, "idem": {}, "operators": [], "seq": 0}


def next_id(prefix):
    STATE["seq"] += 1
    return "%s_n%d" % (prefix, STATE["seq"])


def is_amount(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return float(v).is_integer()


def check_amount(v, low=1):
    if not is_amount(v) or int(v) < low or int(v) > 1000000000:
        raise ApiError(422, "validation_failed", "invalid amount")
    return int(v)


def check_note_vis(body):
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > 200:
        raise ApiError(422, "validation_failed", "invalid note")
    vis = body.get("visibility", "public")
    if vis not in ("public", "private"):
        raise ApiError(422, "validation_failed", "invalid visibility")
    return note, vis


def by_handle(handle):
    for u in STATE["users"].values():
        if u["handle"] == handle:
            return u
    return None


def held(uid):
    t = now()
    return sum(a["amount"] - a["captured"] for a in STATE["auths"].values()
               if a["from"] == uid and a["status"] == "open" and a["expires"] > t)


def available(uid):
    return STATE["users"][uid]["balance"] - held(uid)


def pay_view(p):
    fu, tu = STATE["users"][p["from"]], STATE["users"][p["to"]]
    return {"payment_id": p["id"], "from_user_id": fu["id"], "from_handle": fu["handle"],
            "to_user_id": tu["id"], "to_handle": tu["handle"], "amount": p["amount"],
            "currency": STATE["currency"], "note": p["note"], "visibility": p["visibility"],
            "request_id": p.get("request_id"), "authorization_id": p.get("authorization_id"),
            "settlement_id": None, "created_at": iso(p["created"])}


def req_view(r):
    ru, pu = STATE["users"][r["requester"]], STATE["users"][r["payer"]]
    return {"request_id": r["id"], "requester_id": ru["id"], "requester_handle": ru["handle"],
            "payer_id": pu["id"], "payer_handle": pu["handle"], "amount": r["amount"],
            "currency": STATE["currency"], "note": r["note"], "status": r["status"],
            "payment_id": r.get("payment_id"), "created_at": iso(r["created"])}


def auth_status(a):
    if a["status"] == "open" and a["expires"] <= now():
        return "expired"
    return a["status"]


def auth_view(a):
    fu, tu = STATE["users"][a["from"]], STATE["users"][a["to"]]
    st = auth_status(a)
    return {"authorization_id": a["id"], "from_user_id": fu["id"], "from_handle": fu["handle"],
            "to_user_id": tu["id"], "to_handle": tu["handle"], "amount": a["amount"],
            "captured_amount": a["captured"], "remaining_amount": (a["amount"] - a["captured"]) if st == "open" else 0,
            "currency": STATE["currency"], "note": a["note"], "visibility": a["visibility"],
            "status": st, "expires_at": iso(a["expires"]),
            "payment_id": a["payment_ids"][-1] if a["payment_ids"] else None,
            "payment_ids": list(a["payment_ids"]), "created_at": iso(a["created"])}


def move(frm, to, amount, note, vis, **link):
    if available(frm) < amount:
        raise ApiError(409, "insufficient_funds", "insufficient funds")
    STATE["users"][frm]["balance"] -= amount
    STATE["users"][to]["balance"] += amount
    p = {"id": next_id("p"), "from": frm, "to": to, "amount": amount, "note": note,
         "visibility": vis, "created": now(), "order": STATE["seq"]}
    p.update(link)
    STATE["payments"].append(p)
    return p


def page(items, query):
    limit, offset = query_int(query, "limit", 50, 1, 200), query_int(query, "offset", 0, 0, None)
    return items[offset:offset + limit], offset + limit < len(items)


def query_int(query, name, default, low, high):
    if name not in query:
        return default
    v = query[name][0]
    if not re.fullmatch(r"\d+", v) or int(v) < low or (high is not None and int(v) > high):
        raise ApiError(422, "validation_failed", "bad " + name)
    return int(v)


# ------------------------------------------------------------------ handlers --

def reset(body):
    st = empty_state()
    st["currency"] = body.get("currency", "EUR")
    st["minor_units"] = body.get("minor_units", 2)
    st["ttl"] = body.get("authorization_ttl_seconds", 600)
    st["operators"] = body.get("settlement_operator_ids", [])
    for u in body.get("users", []):
        if u["balance"] < 0:
            raise ApiError(422, "validation_failed", "negative balance")
        st["users"][u["id"]] = {"id": u["id"], "email": u["email"], "password": u["password"],
                                "display_name": u["display_name"], "handle": u["handle"], "balance": u["balance"]}
    for i, p in enumerate(body.get("payments", [])):
        st["payments"].append({"id": p["id"], "from": p["from_user_id"], "to": p["to_user_id"],
                               "amount": p["amount"], "note": p.get("note", ""),
                               "visibility": p.get("visibility", "public"), "created": now() - 3600 + i, "order": -1000 + i})
    for i, r in enumerate(body.get("requests", [])):
        st["requests"][r["id"]] = {"id": r["id"], "requester": r["requester_id"], "payer": r["payer_id"],
                                   "amount": r["amount"], "note": r.get("note", ""), "status": r["status"],
                                   "created": now() - 3600 + i, "order": -1000 + i}
    for i, a in enumerate(body.get("authorizations", [])):
        st["auths"][a["id"]] = {"id": a["id"], "from": a["from_user_id"], "to": a["to_user_id"],
                                "amount": a["amount"], "captured": a.get("captured_amount", 0),
                                "note": a.get("note", ""), "visibility": a.get("visibility", "public"),
                                "status": a["status"], "expires": parse_iso(a["expires_at"]),
                                "payment_ids": [], "created": now() - 3600 + i, "order": -1000 + i}
    STATE.clear()
    STATE.update(st)


def derive_handle(email):
    return re.sub(r"[^a-z0-9_]", "_", email.split("@", 1)[0].lower())[:20]


def auth_signup(body):
    email, pw, name = body.get("email"), body.get("password"), body.get("display_name")
    if not all(isinstance(x, str) for x in (email, pw, name)):
        raise ApiError(422, "validation_failed", "missing field")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", email) or len(pw) < 8:
        raise ApiError(422, "validation_failed", "invalid email or password")
    if any(u["email"] == email for u in STATE["users"].values()):
        raise ApiError(409, "email_taken", "email taken")
    handle = derive_handle(email)
    if not handle or by_handle(handle):
        raise ApiError(409, "handle_taken", "handle taken")
    uid = next_id("u")
    STATE["users"][uid] = {"id": uid, "email": email, "password": pw, "display_name": name, "handle": handle, "balance": 0}
    return 201, session(uid)


def auth_login(body):
    for u in STATE["users"].values():
        if u["email"] == body.get("email") and u["password"] == body.get("password"):
            return 200, session(u["id"])
    raise ApiError(401, "unauthenticated", "wrong email or password")


def session(uid):
    tok = secrets.token_urlsafe(24)
    STATE["tokens"][tok] = uid
    u = STATE["users"][uid]
    return {"user_id": uid, "display_name": u["display_name"], "token": tok}


def me(uid, _):
    u = STATE["users"][uid]
    h = held(uid)
    return 200, {"user_id": uid, "display_name": u["display_name"], "handle": u["handle"],
                 "balance": u["balance"], "total": u["balance"], "available": u["balance"] - h, "held": h,
                 "currency": STATE["currency"], "minor_units": STATE["minor_units"]}


def create_payment(uid, body):
    amount = check_amount(body.get("amount"))
    note, vis = check_note_vis(body)
    to = body.get("to_handle")
    if not isinstance(to, str):
        raise ApiError(422, "validation_failed", "to_handle required")
    if to == STATE["users"][uid]["handle"]:
        raise ApiError(422, "self_payment", "cannot pay yourself")
    target = by_handle(to)
    if not target:
        raise ApiError(404, "not_found", "no such handle")
    return 201, pay_view(move(uid, target["id"], amount, note, vis))


def create_request(uid, body):
    amount = check_amount(body.get("amount"))
    note, _ = check_note_vis(body)
    h = body.get("payer_handle")
    if not isinstance(h, str):
        raise ApiError(422, "validation_failed", "payer_handle required")
    if h == STATE["users"][uid]["handle"]:
        raise ApiError(422, "self_request", "cannot request from yourself")
    payer = by_handle(h)
    if not payer:
        raise ApiError(404, "not_found", "no such handle")
    return 201, req_view(new_request(uid, payer["id"], amount, note))


def new_request(requester, payer, amount, note):
    r = {"id": next_id("rq"), "requester": requester, "payer": payer, "amount": amount, "note": note,
         "status": "pending", "payment_id": None, "created": now(), "order": STATE["seq"]}
    STATE["requests"][r["id"]] = r
    return r


def get_request(rid):
    r = STATE["requests"].get(rid)
    if not r:
        raise ApiError(404, "not_found", "no such request")
    return r


def pay_request(uid, body, rid):
    _, vis = check_note_vis({"visibility": body.get("visibility", "public")})
    r = get_request(rid)
    if r["payer"] != uid:
        raise ApiError(403, "forbidden", "not the payer")
    if r["status"] != "pending":
        raise ApiError(409, "request_not_pending", "request is " + r["status"])
    p = move(uid, r["requester"], r["amount"], r["note"], vis, request_id=r["id"])
    r["status"], r["payment_id"] = "paid", p["id"]
    return 201, pay_view(p)


def close_request(uid, rid, action):
    r = get_request(rid)
    who, final = ("payer", "declined") if action == "decline" else ("requester", "cancelled")
    if r[who] != uid:
        raise ApiError(403, "forbidden", "not the " + who)
    if r["status"] not in ("pending", final):
        raise ApiError(409, "request_not_pending", "request is " + r["status"])
    r["status"] = final
    return 200, req_view(r)


def list_requests(uid, query):
    direction = query.get("direction", [None])[0]
    status = query.get("status", [None])[0]
    if direction not in (None, "incoming", "outgoing") or status not in (None, "pending", "paid", "declined", "cancelled"):
        raise ApiError(422, "validation_failed", "bad filter")
    items = [r for r in STATE["requests"].values()
             if (r["payer"] == uid and direction in (None, "incoming")) or (r["requester"] == uid and direction in (None, "outgoing"))]
    items = [r for r in items if status in (None, r["status"])]
    items.sort(key=lambda r: (r["created"], r["order"]), reverse=True)
    chunk, more = page(items, query)
    return 200, {"requests": [req_view(r) for r in chunk], "has_more": more}


def create_split(uid, body):
    amount = check_amount(body.get("amount"))
    note, _ = check_note_vis({"note": body.get("note", "")})
    handles = body.get("participant_handles")
    if not isinstance(handles, list) or not handles or len(set(handles)) != len(handles) or not all(isinstance(h, str) for h in handles):
        raise ApiError(422, "validation_failed", "bad participants")
    users = [by_handle(h) for h in handles]
    if not all(users):
        raise ApiError(404, "not_found", "unknown handle")
    base, extra = divmod(amount, len(handles))
    shares = [base + (1 if i < extra else 0) for i in range(len(handles))]
    reqs = [req_view(new_request(uid, u["id"], s, note)) for u, s in zip(users, shares) if u["id"] != uid]
    return 201, {"split_id": next_id("sp"), "amount": amount, "currency": STATE["currency"], "note": note,
                 "shares": [{"handle": h, "amount": s} for h, s in zip(handles, shares)],
                 "requests": reqs, "created_at": iso(now())}


def activity(uid, query):
    items = [p for p in STATE["payments"] if p["visibility"] == "public" or uid in (p["from"], p["to"])]
    items.sort(key=lambda p: (p["created"], p["order"]), reverse=True)
    chunk, more = page(items, query)
    return 200, {"payments": [pay_view(p) for p in chunk], "has_more": more}


def create_auth(uid, body):
    amount = check_amount(body.get("amount"))
    note, vis = check_note_vis(body)
    to = body.get("to_handle")
    if not isinstance(to, str):
        raise ApiError(422, "validation_failed", "to_handle required")
    if to == STATE["users"][uid]["handle"]:
        raise ApiError(422, "self_payment", "cannot authorise yourself")
    target = by_handle(to)
    if not target:
        raise ApiError(404, "not_found", "no such handle")
    if available(uid) < amount:
        raise ApiError(409, "insufficient_funds", "insufficient available funds")
    t = now()
    a = {"id": next_id("a"), "from": uid, "to": target["id"], "amount": amount, "captured": 0, "note": note,
         "visibility": vis, "status": "open", "expires": t + STATE["ttl"], "payment_ids": [], "created": t,
         "order": STATE["seq"]}
    STATE["auths"][a["id"]] = a
    return 201, auth_view(a)


def get_auth(aid):
    a = STATE["auths"].get(aid)
    if not a:
        raise ApiError(404, "not_found", "no such authorisation")
    return a


def capture(uid, body, aid):
    a = get_auth(aid)
    if a["to"] != uid:
        raise ApiError(403, "forbidden", "only the receiver may capture")
    if a["status"] != "open":
        raise ApiError(409, "authorization_not_open", "authorisation is " + a["status"])
    if a["expires"] <= now():
        raise ApiError(409, "authorization_expired", "authorisation expired")
    remaining = a["amount"] - a["captured"]
    amount = body.get("amount", remaining)
    if not is_amount(amount) or int(amount) < 1:
        raise ApiError(422, "validation_failed", "invalid amount")
    amount = int(amount)
    if amount > remaining:
        raise ApiError(422, "capture_exceeds_authorization", "more than remains")
    final = body.get("final", True)
    if not isinstance(final, bool):
        raise ApiError(422, "validation_failed", "final must be boolean")
    # The captured money was reserved by this hold: release it, then move it.
    a["captured"] += amount
    try:
        p = move(a["from"], a["to"], amount, a["note"], a["visibility"], authorization_id=a["id"])
    except ApiError:
        a["captured"] -= amount
        raise
    a["payment_ids"].append(p["id"])
    if final or a["captured"] == a["amount"]:
        a["status"] = "captured"
    return 201, pay_view(p)


def void(uid, aid):
    a = get_auth(aid)
    if a["from"] != uid:
        raise ApiError(403, "forbidden", "only the payer may void")
    st = auth_status(a)
    if st not in ("open", "voided"):
        raise ApiError(409, "authorization_not_open", "authorisation is " + st)
    a["status"] = "voided"
    return 200, auth_view(a)


def list_auths(uid, query):
    direction = query.get("direction", [None])[0]
    status = query.get("status", [None])[0]
    if direction not in (None, "incoming", "outgoing") or status not in (None, "open", "captured", "voided", "expired"):
        raise ApiError(422, "validation_failed", "bad filter")
    items = [a for a in STATE["auths"].values()
             if (a["from"] == uid and direction in (None, "outgoing")) or (a["to"] == uid and direction in (None, "incoming"))]
    items = [a for a in items if status in (None, auth_status(a))]
    items.sort(key=lambda a: (a["created"], a["order"]), reverse=True)
    chunk, more = page(items, query)
    return 200, {"authorizations": [auth_view(a) for a in chunk], "has_more": more}


IDEMPOTENT = [
    ("POST", re.compile(r"^/payments$"), lambda u, b, m: create_payment(u, b)),
    ("POST", re.compile(r"^/requests$"), lambda u, b, m: create_request(u, b)),
    ("POST", re.compile(r"^/requests/([^/]+)/pay$"), lambda u, b, m: pay_request(u, b, m.group(1))),
    ("POST", re.compile(r"^/splits$"), lambda u, b, m: create_split(u, b)),
    ("POST", re.compile(r"^/authorizations$"), lambda u, b, m: create_auth(u, b)),
    ("POST", re.compile(r"^/authorizations/([^/]+)/capture$"), lambda u, b, m: capture(u, b, m.group(1))),
]
PLAIN = [
    ("GET", re.compile(r"^/me$"), lambda u, b, m, q: me(u, q)),
    ("GET", re.compile(r"^/requests$"), lambda u, b, m, q: list_requests(u, q)),
    ("GET", re.compile(r"^/activity$"), lambda u, b, m, q: activity(u, q)),
    ("GET", re.compile(r"^/authorizations$"), lambda u, b, m, q: list_auths(u, q)),
    ("POST", re.compile(r"^/requests/([^/]+)/(decline|cancel)$"), lambda u, b, m, q: close_request(u, m.group(1), m.group(2))),
    ("POST", re.compile(r"^/authorizations/([^/]+)/void$"), lambda u, b, m, q: void(u, m.group(1))),
]


def dispatch(method, path, query, headers, body):
    if method == "POST" and path == "/_test/reset":
        reset(body if isinstance(body, dict) else {})
        return 204, None
    if method == "GET" and path == "/_test/export":
        return 200, {"track": "pocketful", "format_version": 1, "state": copy.deepcopy(STATE)}
    if method == "POST" and path == "/_test/import":
        STATE.clear()
        STATE.update(copy.deepcopy(body["state"]))
        return 204, None
    if method == "POST" and path == "/_dev/faults":
        FAULTS[:] = body.get("rules", [])
        return 200, {"rules": FAULTS}
    if method == "POST" and path == "/_dev/clock":
        CLOCK["offset"] += float(body.get("advance_seconds", 0))
        return 200, {"offset": CLOCK["offset"]}
    if method == "POST" and path == "/auth/signup":
        return auth_signup(body)
    if method == "POST" and path == "/auth/login":
        return auth_login(body)
    auth = headers.get("Authorization", "")
    uid = STATE.get("tokens", {}).get(auth[7:]) if auth.startswith("Bearer ") else None
    if not uid:
        raise ApiError(401, "unauthenticated", "sign in")
    for m_, rx, fn in IDEMPOTENT:
        m = rx.match(path)
        if m and method == m_:
            key = headers.get("Idempotency-Key") or ""
            if not key:
                raise ApiError(400, "missing_idempotency_key", "Idempotency-Key required")
            slot = (uid, key)
            fp = json.dumps([method, path, body], sort_keys=True)
            prior = STATE["idem"].get(repr(slot))
            if prior:
                if prior["fp"] != fp:
                    raise ApiError(409, "idempotency_key_reuse", "key reused with another body")
                return 200, prior["response"]
            status, resp = fn(uid, body if isinstance(body, dict) else {}, m)
            STATE["idem"][repr(slot)] = {"fp": fp, "response": resp}
            return status, resp
    for m_, rx, fn in PLAIN:
        m = rx.match(path)
        if m and method == m_:
            return fn(uid, body if isinstance(body, dict) else {}, m, query)
    raise ApiError(404, "not_found", "no such route")


def take_fault(method, path):
    with LOCK:
        for rule in FAULTS:
            if rule.get("method", method) == method and rule.get("path") == path and rule.get("times", 1) > 0:
                rule["times"] = rule.get("times", 1) - 1
                return rule
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("DEVSTUB_LOG"):
            super().log_message(fmt, *args)

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")

    def handle_any(self, method):
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if method == "GET" and self.serve_ui(path):
            return
        fault = take_fault(method, path)
        if fault and fault.get("action") == "drop_before":
            return self.drop()
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            return self.send_json(400, {"error": {"code": "malformed_request", "message": "bad JSON"}})
        with LOCK:
            try:
                status, payload = dispatch(method, path, query, self.headers, body)
            except ApiError as e:
                status, payload = e.status, {"error": {"code": e.code, "message": e.message}}
        if fault and fault.get("action") == "drop_after_commit":
            # Committed, but the client never gets a whole response: headers
            # promise a body that never arrives (a browser cannot retry this).
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", "4096")
            self.end_headers()
            self.wfile.write(b"{")
            self.wfile.flush()
            return self.drop()
        if fault and fault.get("action") == "replace_body":
            # Committed; the status survives but the body is replaced verbatim.
            data = fault.get("body", "").encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if fault and fault.get("action") == "delay":
            time.sleep(fault.get("ms", 1000) / 1000.0)
        self.send_json(status, payload)

    def drop(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def serve_ui(self, path):
        if path.startswith("/ui/"):
            name = os.path.basename(path[4:])
            full = os.path.join(HERE, name)
            ext = os.path.splitext(name)[1]
            if ext in STATIC_TYPES and os.path.isfile(full):
                return self.send_file(full, STATIC_TYPES[ext])
            return False
        if path in PAGES and "text/html" in self.headers.get("Accept", ""):
            return self.send_file(os.path.join(HERE, PAGES[path]), STATIC_TYPES[".html"])
        return False

    def send_file(self, full, ctype):
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
        return True

    def send_json(self, status, payload):
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = ap.parse_args()
    STATE.update(empty_state())
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("devstub on http://127.0.0.1:%d" % args.port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
