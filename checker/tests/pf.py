"""HTTP helpers for the checks: plain httpx, no knowledge of the implementation."""

from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx

PASSWORD = "correct horse"
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$")


def base_fixture(**over) -> dict:
    fx = {
        "currency": "EUR",
        "minor_units": 2,
        "users": [
            {"id": "u_ada", "email": "ada@example.com", "password": PASSWORD,
             "display_name": "Ada", "handle": "ada", "balance": 10000},
            {"id": "u_bob", "email": "bob@example.com", "password": PASSWORD,
             "display_name": "Bob", "handle": "bob", "balance": 2500},
            {"id": "u_cy", "email": "cy@example.com", "password": PASSWORD,
             "display_name": "Cy", "handle": "cy", "balance": 0},
            {"id": "u_dee", "email": "dee@example.com", "password": PASSWORD,
             "display_name": "Dee", "handle": "dee", "balance": 700},
        ],
        "payments": [
            {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
             "amount": 500, "note": "coffee", "visibility": "public"},
        ],
        "requests": [
            {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
             "amount": 1200, "note": "taxi", "status": "pending"},
        ],
    }
    fx.update(over)
    return fx


def key() -> str:
    return uuid.uuid4().hex


class R:
    """A response: status, parsed JSON (or None), raw headers."""

    def __init__(self, resp: httpx.Response):
        self.status = resp.status_code
        self.headers = resp.headers
        self.text = resp.text
        try:
            self.json = resp.json()
        except ValueError:
            self.json = None

    @property
    def code(self):
        try:
            return self.json["error"]["code"]
        except (TypeError, KeyError):
            return None

    def __repr__(self):
        return f"<{self.status} {self.text[:300]}>"


class Session:
    def __init__(self, api: "Api", token: str, user_id: str, handle: str):
        self.api, self.token, self.user_id, self.handle = api, token, user_id, handle

    def h(self, idem=None, extra=None):
        hd = {"Authorization": f"Bearer {self.token}"}
        if idem is not None:
            hd["Idempotency-Key"] = idem
        hd.update(extra or {})
        return hd

    def get(self, path, params=None):
        return self.api.req("GET", path, headers=self.h(), params=params)

    def post(self, path, body=None, idem=None, raw=None, headers=None):
        return self.api.req("POST", path, headers=self.h(idem, headers), body=body, raw=raw)

    def me(self):
        return self.get("/me")

    def balance(self) -> int:
        r = self.me()
        assert r.status == 200, r
        return r.json["balance"]

    def pay(self, to, amount, idem=None, **kw):
        body = {"to_handle": to, "amount": amount, **kw}
        return self.post("/payments", body, idem=idem or key())

    def request(self, payer, amount, idem=None, **kw):
        body = {"payer_handle": payer, "amount": amount, **kw}
        return self.post("/requests", body, idem=idem or key())

    def pay_request(self, rid, body=None, idem=None):
        return self.post(f"/requests/{rid}/pay", {} if body is None else body, idem=idem or key())


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.c = httpx.Client(base_url=self.base, timeout=httpx.Timeout(15.0),
                              limits=httpx.Limits(max_connections=100, max_keepalive_connections=60))

    def close(self):
        self.c.close()

    def req(self, method, path, headers=None, body=None, raw=None, params=None) -> R:
        hd = dict(headers or {})
        content = None
        if raw is not None:
            content = raw if isinstance(raw, bytes) else raw.encode()
            hd.setdefault("Content-Type", "application/json")
        elif body is not None:
            content = json.dumps(body).encode()
            hd["Content-Type"] = "application/json"
        return R(self.c.request(method, path, headers=hd, content=content, params=params))

    def reset(self, fx) -> None:
        r = self.req("POST", "/_test/reset", body=fx)
        assert r.status == 204, f"reset failed: {r}"

    def login(self, email, password=PASSWORD) -> R:
        return self.req("POST", "/auth/login", body={"email": email, "password": password})

    def session(self, email, password=PASSWORD) -> Session:
        r = self.login(email, password)
        assert r.status == 200, f"login {email}: {r}"
        me = self.req("GET", "/me", headers={"Authorization": f"Bearer {r.json['token']}"})
        assert me.status == 200, me
        return Session(self, r.json["token"], r.json["user_id"], me.json["handle"])

    def sessions(self, fx) -> dict[str, Session]:
        return {u["handle"]: self.session(u["email"], u["password"]) for u in fx["users"]}

    def signup(self, email, password=PASSWORD, display_name="New") -> R:
        return self.req("POST", "/auth/signup",
                        body={"email": email, "password": password, "display_name": display_name})


def total(sessions) -> int:
    return sum(s.balance() for s in sessions.values())


def parallel(fns, workers=50):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(f) for f in fns]
        return [f.result() for f in futs]


def is_error(r: R, status: int, code: str) -> bool:
    return (r.status == status and isinstance(r.json, dict) and isinstance(r.json.get("error"), dict)
            and r.json["error"].get("code") == code and isinstance(r.json["error"].get("message"), str))
