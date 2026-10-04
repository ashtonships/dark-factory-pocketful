"""W-1: runtime contract, reset/seed, conventions, errors, authentication, GET /me."""

from __future__ import annotations

import json
import socket
import time
from urllib.parse import urlparse

import pytest

from pf import PASSWORD, base_fixture, is_error, parallel

pytestmark = pytest.mark.item("W-1")


# ---------------------------------------------------------------- health, reset, seed

def test_health_ok(api):
    # ledger: 37
    r = api.req("GET", "/health")
    assert r.status == 200 and r.json == {"status": "ok"}, r


def test_reset_204_and_seeded_login(api):
    # ledger: 39, 40, 42, 82
    fx = base_fixture()
    r = api.req("POST", "/_test/reset", body=fx)
    assert r.status == 204, r
    for u in fx["users"]:
        lr = api.login(u["email"], u["password"])
        assert lr.status == 200, (u["email"], lr)
        assert lr.json["user_id"] == u["id"] and lr.json["display_name"] == u["display_name"]
        assert isinstance(lr.json["token"], str) and lr.json["token"]


def test_me_shape_and_seeded_balances(api, seeded):
    # ledger: 50, 51, 57, 83, 84, 85
    me = seeded["ada"].me()
    assert me.status == 200, me
    want = {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
            "balance": 10000, "currency": "EUR", "minor_units": 2}
    # later stages add fields beside these (stage 2: total, available, held)
    assert {k: me.json.get(k) for k in want} == want, me.json
    # seeded payments are not replayed against the given balances
    assert seeded["bob"].balance() == 2500
    assert seeded["cy"].balance() == 0


@pytest.mark.parametrize("currency,mu", [("JPY", 0), ("BHD", 3), ("EUR", 2)])
def test_currency_from_fixture(api, currency, mu):
    # ledger: 50, 88, 89
    fx = base_fixture(currency=currency, minor_units=mu)
    api.reset(fx)
    me = api.session("ada@example.com").me()
    assert me.json["currency"] == currency and me.json["minor_units"] == mu


def test_reset_replaces_all_state(api):
    # ledger: 39, 40, 41
    api.reset(base_fixture())
    old = api.session("ada@example.com")
    assert api.signup("zed@example.com").status == 201
    fx = base_fixture(users=[{"id": "u_x", "email": "x@example.com", "password": PASSWORD,
                              "display_name": "X", "handle": "xx", "balance": 42}],
                      payments=[], requests=[])
    api.reset(fx)
    assert api.login("zed@example.com").status == 401
    assert api.login("ada@example.com").status == 401
    assert is_error(old.me(), 401, "unauthenticated"), "token from before reset still works"
    s = api.session("x@example.com")
    assert s.balance() == 42 and s.handle == "xx"
    # and reset again
    api.reset(base_fixture())
    assert api.login("x@example.com").status == 401
    assert api.login("ada@example.com").status == 200


@pytest.mark.parametrize("mutate", [
    lambda fx: fx["users"][1].__setitem__("balance", -1),
    lambda fx: fx.__setitem__("minor_units", 1),
    lambda fx: fx.__setitem__("minor_units", 4),
])
def test_invalid_fixture_422_changes_nothing(api, mutate):
    # ledger: 86, 87, 88
    api.reset(base_fixture())
    api.signup("keep@example.com")
    fx = base_fixture()
    fx["users"][0]["email"] = "other@example.com"
    mutate(fx)
    r = api.req("POST", "/_test/reset", body=fx)
    assert is_error(r, 422, "validation_failed"), r
    assert api.login("keep@example.com").status == 200, "failed reset changed state"
    assert api.login("ada@example.com").status == 200
    assert api.login("other@example.com").status == 401


def test_reset_unparseable_400(api):
    # ledger: 95
    r = api.req("POST", "/_test/reset", raw="{not json")
    assert is_error(r, 400, "malformed_request"), r


def test_reset_needs_no_auth_and_optional_arrays(api):
    # ledger: 42 (D-7: payments/requests optional)
    fx = base_fixture()
    del fx["payments"], fx["requests"]
    r = api.req("POST", "/_test/reset", body=fx, headers={"Authorization": "Bearer nonsense"})
    assert r.status == 204, r


def test_large_balances_exact(api):
    # ledger: 80, 81, 12
    big = 2 ** 53 - 1000
    fx = base_fixture()
    fx["users"][0]["balance"] = big
    api.reset(fx)
    assert api.session("ada@example.com").balance() == big


def test_balance_exactly_2_pow_53(api):
    # ledger: 80, 81, 9011 (the +-2^53 range is inclusive)
    top = 2 ** 53
    fx = base_fixture(payments=[], requests=[])
    fx["users"][0]["balance"] = top
    r = api.req("POST", "/_test/reset", body=fx)
    assert r.status == 204, r
    me = api.session("ada@example.com").me()
    assert me.status == 200 and me.json["balance"] == top and type(me.json["balance"]) is int, me
    assert '"balance":9007199254740992' in me.text.replace(" ", ""), me.text


# ---------------------------------------------------------------- conventions

def test_json_content_type_on_success_and_error(api, seeded):
    # ledger: 43, 91
    for r in (seeded["ada"].me(), api.req("GET", "/me"), api.req("GET", "/health")):
        ct = r.headers.get("content-type", "").replace(" ", "").lower()
        assert ct.startswith("application/json") and "charset=utf-8" in ct, (r, ct)


def test_unknown_fields_and_query_ignored(api, seeded):
    # ledger: 46, 47
    r = api.req("POST", "/auth/login", body={"email": "ada@example.com", "password": PASSWORD,
                                             "extra": {"x": [1]}, "remember": True})
    assert r.status == 200, r
    r = api.req("GET", "/me?foo=bar&limit=zzz", headers=seeded["ada"].h())
    assert r.status == 200, r


def test_ids_opaque_short(api, seeded):
    # ledger: 48
    r = api.signup("idcheck@example.com")
    assert r.status == 201 and isinstance(r.json["user_id"], str) and 0 < len(r.json["user_id"]) <= 64


def test_error_body_shape(api):
    # ledger: 91, 92
    r = api.req("GET", "/me")
    assert is_error(r, 401, "unauthenticated"), r
    assert set(r.json.keys()) == {"error"}


def test_unknown_route_404_and_wrong_method_405(api, seeded):
    # ledger: 99, 125 (D-8)
    r = api.req("GET", "/no/such/thing", headers=seeded["ada"].h())
    assert is_error(r, 404, "not_found"), r
    r = api.req("DELETE", "/me", headers=seeded["ada"].h())
    assert is_error(r, 405, "method_not_allowed"), r


# ---------------------------------------------------------------- authentication

def test_signup_201_and_derived_handle(api, seeded):
    # ledger: 58, 60, 61, 117
    r = api.signup("Grace.Hopper+Navy-1@Example.com", display_name="Grace")
    assert r.status == 201, r
    assert r.json["display_name"] == "Grace" and r.json["token"] and r.json["user_id"]
    me = api.req("GET", "/me", headers={"Authorization": f"Bearer {r.json['token']}"})
    assert me.status == 200, me
    assert me.json["handle"] == "grace_hopper_navy_1"
    assert me.json["balance"] == 0 and me.json["currency"] == "EUR" and me.json["minor_units"] == 2
    assert me.json["user_id"] == r.json["user_id"]


def test_signup_handle_truncated_to_20(api, seeded):
    # ledger: 54, 58
    r = api.signup("abcdefghijklmnopqrstuvwxyz@example.com")
    assert r.status == 201, r
    me = api.req("GET", "/me", headers={"Authorization": f"Bearer {r.json['token']}"})
    assert me.json["handle"] == "abcdefghijklmnopqrst"


def test_signup_then_login_works(api, seeded):
    # ledger: 117, 127, 128
    r = api.signup("newbie@example.com", password="12345678")
    assert r.status == 201, r
    l1 = api.login("newbie@example.com", "12345678")
    l2 = api.login("newbie@example.com", "12345678")
    assert l1.status == 200 and l2.status == 200
    for t in (r.json["token"], l1.json["token"], l2.json["token"]):
        assert api.req("GET", "/me", headers={"Authorization": f"Bearer {t}"}).status == 200


def test_signup_email_taken(api, seeded):
    # ledger: 120
    assert is_error(api.signup("ada@example.com"), 409, "email_taken")
    assert is_error(api.signup("ADA@Example.COM"), 409, "email_taken")  # D-6


def test_signup_handle_taken_creates_nothing(api, seeded):
    # ledger: 59, 124
    r = api.signup("bob@other.example", password="another pass")
    assert is_error(r, 409, "handle_taken"), r
    assert api.login("bob@other.example", "another pass").status == 401


@pytest.mark.parametrize("pw,ok", [("1234567", False), ("", False), ("12345678", True)])
def test_signup_password_length(api, seeded, pw, ok):
    # ledger: 121
    r = api.signup(f"pw{len(pw)}@example.com", password=pw)
    if ok:
        assert r.status == 201, r
    else:
        assert is_error(r, 422, "validation_failed"), r


@pytest.mark.parametrize("email", ["plain", "@example.com", "local@", "a@b@c", ""])
def test_signup_bad_email(api, seeded, email):
    # ledger: 122
    assert is_error(api.signup(email), 422, "validation_failed")


def test_signup_missing_field_422_wrong_type_400(api, seeded):
    # ledger: 101, 111
    r = api.req("POST", "/auth/signup", body={"email": "m@example.com", "display_name": "M"})
    assert is_error(r, 422, "validation_failed"), r
    r = api.req("POST", "/auth/signup", body={"email": 5, "password": PASSWORD, "display_name": "M"})
    assert is_error(r, 400, "malformed_request"), r


def test_login_failures(api, seeded):
    # ledger: 123
    assert is_error(api.login("ada@example.com", "wrong password"), 401, "unauthenticated")
    assert is_error(api.login("nobody@example.com"), 401, "unauthenticated")


@pytest.mark.parametrize("hdr", [None, "Bearer", "Bearer not-a-token", "Basic YWRhOng=", "token"])
def test_bad_bearer_401(api, seeded, hdr):
    # ledger: 97, 126
    r = api.req("GET", "/me", headers={} if hdr is None else {"Authorization": hdr})
    assert is_error(r, 401, "unauthenticated"), r


def test_password_not_stored_plaintext_in_export(api):
    # ledger: 129, 130 (the only observable storage is the export; checked again in W-4)
    api.reset(base_fixture())
    api.signup("plain@example.com", password="sekrit-pass-123")
    r = api.req("GET", "/_test/export")
    if r.status == 404:
        pytest.skip("export arrives in W-4")
    assert "sekrit-pass-123" not in r.text and PASSWORD not in r.text


# ---------------------------------------------------------------- body parsing

@pytest.mark.parametrize("raw", ["{", "[1, 2]", "\"str\"", "42", "null", "",
                                 '{"email": NaN}', '{"email": Infinity}', '{"email": -Infinity}'])
def test_unparseable_or_non_object_400(api, seeded, raw):
    # ledger: 95, 111, 9003, 9006
    r = api.req("POST", "/auth/login", raw=raw)
    assert is_error(r, 400, "malformed_request"), r


def test_invalid_utf8_400(api, seeded):
    # ledger: 9003
    r = api.req("POST", "/auth/login", raw=b'{"email": "\xff\xfe", "password": "x"}')
    assert is_error(r, 400, "malformed_request"), r


def test_utf16_body_400(api, seeded):
    # ledger: 9003
    raw = json.dumps({"email": "ada@example.com", "password": PASSWORD}).encode("utf-16")
    assert is_error(api.req("POST", "/auth/login", raw=raw), 400, "malformed_request")


def test_duplicate_keys_last_wins(api, seeded):
    # ledger: 9003
    raw = '{"email": "ada@example.com", "password": "wrong", "password": "correct horse"}'
    assert api.req("POST", "/auth/login", raw=raw).status == 200


# ---------------------------------------------------------------- raw HTTP: keep-alive and chunked

def _raw(api, payload: bytes, expect: int) -> list[bytes]:
    u = urlparse(api.base)
    with socket.create_connection((u.hostname, u.port), timeout=10) as s:
        s.sendall(payload)
        buf, heads = b"", []
        deadline = time.monotonic() + 10
        while len(heads) < expect and time.monotonic() < deadline:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                end = buf.find(b"\r\n\r\n")
                if end < 0:
                    break
                head = buf[:end].decode("latin-1")
                length = 0
                for line in head.split("\r\n")[1:]:
                    k, _, v = line.partition(":")
                    if k.strip().lower() == "content-length":
                        length = int(v.strip())
                if len(buf) < end + 4 + length:
                    break
                heads.append(head.split("\r\n")[0].encode())
                buf = buf[end + 4 + length:]
        return heads


def test_keepalive_after_rejected_bodies(api, seeded):
    # ledger: 9001
    host = urlparse(api.base).netloc
    bad = b'{"this is": "not parsed"'
    reqs = [
        f"POST /auth/login HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(bad)}\r\n\r\n".encode() + bad,                       # 400
        f"POST /me HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(bad)}\r\n\r\n".encode() + bad,                       # 401/405
        f"POST /nowhere HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(bad)}\r\n\r\n".encode() + bad,                       # 404
        f"GET /health HTTP/1.1\r\nHost: {host}\r\n\r\n".encode(),
    ]
    heads = _raw(api, b"".join(reqs), 4)
    assert len(heads) == 4, heads
    assert b" 400" in heads[0] and b" 404" in heads[2] and b" 200" in heads[3], heads


def test_chunked_body_is_read(api, seeded):
    # ledger: 9002
    host = urlparse(api.base).netloc
    body = json.dumps({"email": "ada@example.com", "password": PASSWORD}).encode()
    a, b = body[:10], body[10:]
    chunked = (f"{len(a):x}\r\n".encode() + a + b"\r\n" + f"{len(b):x}\r\n".encode() + b
               + b"\r\n0\r\n\r\n")
    req = (f"POST /auth/login HTTP/1.1\r\nHost: {host}\r\nContent-Type: application/json\r\n"
           f"Transfer-Encoding: chunked\r\n\r\n").encode() + chunked
    req += f"GET /health HTTP/1.1\r\nHost: {host}\r\n\r\n".encode()
    heads = _raw(api, req, 2)
    assert len(heads) == 2 and b" 200" in heads[0] and b" 200" in heads[1], heads


# ---------------------------------------------------------------- load

def test_fifty_concurrent_logins_no_5xx_under_5s(api, seeded):
    # ledger: 30, 31, 116, 129
    def one():
        t = time.monotonic()
        r = api.login("ada@example.com")
        return r.status, time.monotonic() - t
    for _ in range(2):
        res = parallel([one] * 50)
        assert all(s == 200 for s, _ in res), res
        assert max(t for _, t in res) < 5, max(t for _, t in res)


def test_fifty_concurrent_signups_unique(api, seeded):
    # ledger: 54, 116, 120
    res = parallel([lambda i=i: api.signup(f"load{i % 25}@example.com") for i in range(50)])
    assert all(r.status < 500 for r in res), [r for r in res if r.status >= 500]
    assert sum(r.status == 201 for r in res) == 25
    assert sum(is_error(r, 409, "email_taken") or is_error(r, 409, "handle_taken") for r in res) == 25
