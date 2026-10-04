"""W-8: stage-2 server - holds, authorizations, captures, void, expiry, available funds, upgrade import."""

from __future__ import annotations

import datetime as dt
import os
import time

import pytest

from pf import PASSWORD, RFC3339, Api, base_fixture, is_error, key, parallel

pytestmark = pytest.mark.item("W-8")

SEED_TOTAL = 10000 + 2500 + 0 + 700
AUTH_KEYS = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
             "captured_amount", "currency", "note", "visibility", "status", "expires_at", "payment_id",
             "created_at", "remaining_amount", "payment_ids"}


def iso(delta_seconds: float) -> str:
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delta_seconds)
    return t.replace(microsecond=0).isoformat()


def parse(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def auth_fixture(**over):
    fx = base_fixture(settlement_operator_ids=["u_dee"])
    fx["authorizations"] = [
        {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
         "visibility": "public", "status": "open", "expires_at": iso(7200)},
        {"id": "a_old", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 3000, "note": "stale",
         "visibility": "public", "status": "open", "expires_at": iso(-7200)},
        {"id": "a_done", "from_user_id": "u_bob", "to_user_id": "u_ada", "amount": 100, "note": "",
         "visibility": "private", "status": "voided", "expires_at": iso(7200)},
    ]
    fx.update(over)
    return fx


@pytest.fixture
def au(api):
    fx = auth_fixture()
    api.reset(fx)
    return api.sessions(fx)


def me(s):
    r = s.me()
    assert r.status == 200, r
    return r.json


def wallet(s):
    m = me(s)
    assert m["balance"] == m["total"] and m["available"] == m["total"] - m["held"] and m["available"] >= 0, m
    return m["total"], m["available"], m["held"]


def authorize(s, to, amount, idem=None, **kw):
    return s.post("/authorizations", {"to_handle": to, "amount": amount, **kw}, idem=idem or key())


def capture(s, aid, body=None, idem=None):
    return s.post(f"/authorizations/{aid}/capture", {} if body is None else body, idem=idem or key())


def grand_total(sessions):
    return sum(me(s)["total"] for s in sessions.values())


def auths(s, **params):
    r = s.get("/authorizations", params=params or None)
    assert r.status == 200, r
    return r.json


# ---------------------------------------------------------------- /me and seeded holds

def test_me_fields_seeded_hold(api, au):
    # ledger: 1138, 1001, 1103, 1118, 1119, 1120, 1139, 1140, 1141, 1145, 1147, 1151, 1152
    assert wallet(au["ada"]) == (10000, 8000, 2000)  # a_old expired by the clock holds nothing
    assert wallet(au["bob"]) == (2500, 2500, 0)
    m = me(au["ada"])
    assert {"user_id", "display_name", "handle", "balance", "total", "available", "held",
            "currency", "minor_units"} <= set(m)


def test_no_holds_is_stage1_behaviour(api):
    # ledger: 1002, 1121, 1127, 1146
    api.reset(base_fixture())
    s = api.session("ada@example.com")
    assert wallet(s) == (10000, 10000, 0)
    assert s.pay("bob", 10000).status == 201


@pytest.mark.parametrize("mutate", [
    lambda fx: fx["authorizations"].append(
        {"id": "a_big", "from_user_id": "u_dee", "to_user_id": "u_ada", "amount": 701, "note": "",
         "visibility": "public", "status": "open", "expires_at": iso(7200)}),
    lambda fx: fx.__setitem__("authorization_ttl_seconds", 0),
    lambda fx: fx.__setitem__("authorization_ttl_seconds", -5),
    lambda fx: fx.__setitem__("authorization_ttl_seconds", 1.5),
])
def test_reset_hold_errors(api, mutate):
    # ledger: 1137, 1142, 1143
    api.reset(auth_fixture())
    api.signup("keep2@example.com")
    fx = auth_fixture()
    mutate(fx)
    assert is_error(api.req("POST", "/_test/reset", body=fx), 422, "validation_failed")
    assert api.login("keep2@example.com").status == 200


def test_expired_seeded_hold_over_balance_is_fine(api):
    # ledger: 1142, 1144, 1145, 1147, 1150
    fx = auth_fixture()
    fx["authorizations"].append({"id": "a_x", "from_user_id": "u_dee", "to_user_id": "u_ada", "amount": 5000,
                                 "note": "", "visibility": "public", "status": "open", "expires_at": iso(-3600)})
    api.reset(fx)
    assert wallet(api.session("dee@example.com")) == (700, 700, 0)


def test_insufficient_against_available(api, au):
    # ledger: 1109, 1110, 1111, 1125, 1126, 1157
    ada = au["ada"]
    assert is_error(ada.pay("bob", 8001), 409, "insufficient_funds")
    assert ada.pay("cy", 8000).status == 201
    assert wallet(ada) == (2000, 0, 2000)
    q = au["bob"].request("ada", 1).json["request_id"]
    assert is_error(ada.pay_request(q), 409, "insufficient_funds")
    assert is_error(authorize(ada, "bob", 1), 409, "insufficient_funds")
    r = au["dee"].post("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]},
                       idem=key())
    assert is_error(r, 409, "insufficient_funds"), r


# ---------------------------------------------------------------- POST /authorizations

def test_authorize_201_shape(api, au):
    # ledger: 1102, 1103, 1108, 1153, 1154, 1156
    r = authorize(au["ada"], "bob", 1500, note="hotel", visibility="private")
    assert r.status == 201, r
    a = r.json
    assert AUTH_KEYS - {"payment_ids"} <= set(a), set(a)
    assert (a["from_user_id"], a["from_handle"], a["to_user_id"], a["to_handle"]) == ("u_ada", "ada", "u_bob", "bob")
    assert a["amount"] == 1500 and a["captured_amount"] == 0 and a["status"] == "open"
    assert a["note"] == "hotel" and a["visibility"] == "private" and a["payment_id"] is None
    assert a["remaining_amount"] == 1500 and a["currency"] == "EUR"
    assert RFC3339.match(a["expires_at"]) and RFC3339.match(a["created_at"])
    assert (parse(a["expires_at"]) - parse(a["created_at"])).total_seconds() == pytest.approx(600, abs=1)
    assert wallet(au["ada"]) == (10000, 6500, 3500)
    assert wallet(au["bob"]) == (2500, 2500, 0)


def test_authorize_defaults_and_ttl(api):
    # ledger: 1134, 1135, 1136, 1155
    api.reset(auth_fixture(authorization_ttl_seconds=90))
    a = authorize(api.session("ada@example.com"), "bob", 5).json
    assert a["note"] == "" and a["visibility"] == "public"
    assert (parse(a["expires_at"]) - parse(a["created_at"])).total_seconds() == pytest.approx(90, abs=1)


@pytest.mark.parametrize("body,status,code", [
    ({"to_handle": "bob", "amount": 0}, 422, "validation_failed"),
    ({"to_handle": "bob", "amount": 1000000001}, 422, "validation_failed"),
    ({"to_handle": "bob", "amount": "5"}, 422, "validation_failed"),
    ({"to_handle": "bob", "amount": 5.5}, 422, "validation_failed"),
    ({"to_handle": "ada", "amount": 5}, 422, "self_payment"),
    ({"to_handle": "bob", "amount": 5, "note": "x" * 201}, 422, "validation_failed"),
    ({"to_handle": "bob", "amount": 5, "visibility": "friends"}, 422, "validation_failed"),
    ({"to_handle": "ghost", "amount": 5}, 404, "not_found"),
    ({"to_handle": "bob", "amount": 9000}, 409, "insufficient_funds"),
])
def test_authorize_errors(api, au, body, status, code):
    # ledger: 1157, 1158, 1159, 1160, 1161
    assert is_error(au["ada"].post("/authorizations", body, idem=key()), status, code)
    assert wallet(au["ada"]) == (10000, 8000, 2000)


def test_authorize_idempotent_and_needs_key(api, au):
    # ledger: 1131, 1132, 1153
    k = key()
    a, b = authorize(au["ada"], "bob", 100, idem=k), authorize(au["ada"], "bob", 100, idem=k)
    assert a.status == 201 and b.status == 200 and a.json == b.json
    assert is_error(authorize(au["ada"], "bob", 101, idem=k), 409, "idempotency_key_reuse")
    assert is_error(au["ada"].post("/authorizations", {"to_handle": "bob", "amount": 1}), 400, "missing_idempotency_key")
    assert wallet(au["ada"])[2] == 2100


def test_open_authorization_not_in_feed(api, au):
    # ledger: 1162
    before = au["bob"].get("/activity", {"limit": 200}).json
    authorize(au["ada"], "bob", 100)
    assert au["bob"].get("/activity", {"limit": 200}).json == before


def test_payment_is_immediate_with_null_authorization(api, au):
    # ledger: 1122, 1123, 1124, 1128, 1169
    p = au["ada"].pay("bob", 10).json
    assert p["authorization_id"] is None and p["request_id"] is None
    assert wallet(au["ada"]) == (9990, 7990, 2000) and wallet(au["bob"])[0] == 2510
    rp = au["ada"].pay_request("rq_1").json
    assert rp["authorization_id"] is None and rp["request_id"] == "rq_1"


# ---------------------------------------------------------------- capture

def test_capture_default_final_releases_remainder(api, au):
    # ledger: 1104, 1112, 1116, 1164, 1167, 1168, 1170, 1171, 1178, 1179
    r = capture(au["bob"], "a_1", {"amount": 1500})
    assert r.status == 201, r
    p = r.json
    assert p["authorization_id"] == "a_1" and p["request_id"] is None and p["amount"] == 1500
    assert p["note"] == "deposit" and p["visibility"] == "public"
    assert (p["from_user_id"], p["to_user_id"]) == ("u_ada", "u_bob")
    assert wallet(au["ada"]) == (8500, 8500, 0)
    assert wallet(au["bob"]) == (4000, 4000, 0)
    a = [x for x in auths(au["ada"])["authorizations"] if x["authorization_id"] == "a_1"][0]
    assert a["status"] == "captured" and a["captured_amount"] == 1500 and a["payment_id"] == p["payment_id"]
    assert a["remaining_amount"] == 0 and a["payment_ids"] == [p["payment_id"]]
    assert p["payment_id"] in {x["payment_id"] for x in au["cy"].get("/activity").json["payments"]}
    assert is_error(capture(au["bob"], "a_1", {"amount": 1}), 409, "authorization_not_open")
    assert grand_total(au) == SEED_TOTAL


def test_capture_omitted_amount_is_remainder(api, au):
    # ledger: 1165, 1177
    r = capture(au["bob"], "a_1")
    assert r.status == 201 and r.json["amount"] == 2000, r
    assert wallet(au["ada"]) == (8000, 8000, 0)


def test_capture_private_copies_visibility(api, au):
    # ledger: 1168
    a = authorize(au["ada"], "bob", 300, visibility="private", note="secret").json
    p = capture(au["bob"], a["authorization_id"]).json
    assert p["visibility"] == "private" and p["note"] == "secret"
    assert p["payment_id"] not in {x["payment_id"] for x in au["cy"].get("/activity").json["payments"]}
    assert p["payment_id"] in {x["payment_id"] for x in au["ada"].get("/activity").json["payments"]}


def test_extended_capture(api, au):
    # ledger: 1105, 1113, 1172, 1173, 1174, 1175, 1177, 1178, 1179, 1184
    bob = au["bob"]
    p1 = capture(bob, "a_1", {"amount": 700, "final": False})
    assert p1.status == 201, p1
    a = [x for x in auths(bob)["authorizations"] if x["authorization_id"] == "a_1"][0]
    assert a["status"] == "open" and a["captured_amount"] == 700 and a["remaining_amount"] == 1300
    assert wallet(au["ada"]) == (9300, 8000, 1300)
    assert is_error(capture(bob, "a_1", {"amount": 1301, "final": False}), 422, "capture_exceeds_authorization")
    p2 = capture(bob, "a_1", {"amount": 300, "final": False})
    p3 = capture(bob, "a_1", {"amount": 1000, "final": False})  # entire remainder closes it
    assert p2.status == p3.status == 201
    a = [x for x in auths(bob)["authorizations"] if x["authorization_id"] == "a_1"][0]
    assert a["status"] == "captured" and a["captured_amount"] == 2000 and a["remaining_amount"] == 0
    assert a["payment_ids"] == [p1.json["payment_id"], p2.json["payment_id"], p3.json["payment_id"]]
    assert a["payment_id"] == p3.json["payment_id"]
    assert wallet(au["ada"]) == (8000, 8000, 0)
    assert is_error(capture(bob, "a_1"), 409, "authorization_not_open")


def test_extended_then_final_releases(api, au):
    # ledger: 1176
    capture(au["bob"], "a_1", {"amount": 500, "final": False})
    assert capture(au["bob"], "a_1", {"amount": 100}).status == 201
    assert wallet(au["ada"]) == (9400, 9400, 0)


def test_extended_then_void_keeps_captures(api, au):
    # ledger: 1180
    p = capture(au["bob"], "a_1", {"amount": 500, "final": False}).json
    r = au["ada"].post("/authorizations/a_1/void")
    assert r.status == 200 and r.json["status"] == "voided" and r.json["captured_amount"] == 500, r
    assert r.json["remaining_amount"] == 0 and r.json["payment_ids"] == [p["payment_id"]]
    assert wallet(au["ada"]) == (9500, 9500, 0)


@pytest.mark.parametrize("body", [{"amount": 0}, {"amount": -1}, {"amount": "5"}, {"amount": 1.5}, {"amount": True}])
def test_capture_amount_invalid(api, au, body):
    # ledger: 1185
    assert is_error(capture(au["bob"], "a_1", body), 422, "validation_failed")


def test_capture_exceeds(api, au):
    # ledger: 1184
    assert is_error(capture(au["bob"], "a_1", {"amount": 2001}), 422, "capture_exceeds_authorization")
    assert wallet(au["ada"]) == (10000, 8000, 2000)


def test_capture_permissions_and_precedence(api, au):
    # ledger: 1182, 1183, 1186, 1187, 1193 (D-14)
    assert is_error(capture(au["ada"], "a_1"), 403, "forbidden")
    assert is_error(capture(au["cy"], "a_1"), 403, "forbidden")
    assert is_error(capture(au["bob"], "a_nope"), 404, "not_found")
    assert is_error(capture(au["bob"], "a_nope", {"amount": 0}), 422, "validation_failed")
    assert is_error(capture(au["cy"], "a_old"), 409, "authorization_expired")
    assert is_error(capture(au["ada"], "a_done"), 409, "authorization_not_open")
    assert is_error(capture(au["bob"], "a_done"), 403, "forbidden")


def test_capture_replay_rules(api, au):
    # ledger: 1163, 1166, 1181, 1114, 1115
    k = key()
    a = capture(au["bob"], "a_1", {}, idem=k)
    b = capture(au["bob"], "a_1", {}, idem=k)
    assert a.status == 201 and b.status == 200 and a.json == b.json
    assert is_error(capture(au["bob"], "a_1", {"amount": 2000}, idem=k), 409, "idempotency_key_reuse")
    assert wallet(au["bob"])[0] == 4500


def test_concurrent_captures_never_exceed(api):
    # ledger: 1107, 1109, 1113, 1222
    for _ in range(3):
        fx = auth_fixture()
        api.reset(fx)
        s = api.sessions(fx)
        res = parallel([lambda: capture(s["bob"], "a_1", {"amount": 300, "final": False})] * 12
                       + [lambda: s["ada"].pay("cy", 1000)] * 10
                       + [lambda: s["ada"].post("/authorizations/a_1/void")] * 2)
        assert all(r.status < 500 for r in res), [r for r in res if r.status >= 500]
        caps = sum(r.status == 201 for r in res[:12])
        assert caps <= 6
        t, av, h = wallet(s["ada"])
        assert av >= 0 and grand_total(s) == SEED_TOTAL
        a = [x for x in auths(s["ada"])["authorizations"] if x["authorization_id"] == "a_1"][0]
        assert a["captured_amount"] == 300 * caps and a["captured_amount"] <= 2000


def test_concurrent_identical_capture_once(api):
    # ledger: 1114, 1115, 1222
    for _ in range(3):
        fx = auth_fixture()
        api.reset(fx)
        s = api.sessions(fx)
        k = key()
        res = parallel([lambda: capture(s["bob"], "a_1", {"amount": 500, "final": False}, idem=k)] * 20)
        assert sum(r.status == 201 for r in res) == 1 and all(r.status in (200, 201) for r in res)
        assert wallet(s["bob"])[0] == 3000


def test_held_cannot_fund_settlement_net_debit(api, au):
    # ledger: 1110, 1111, 1126
    r = au["dee"].post("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 8001}]},
                       idem=key())
    assert is_error(r, 409, "insufficient_funds"), r
    r = au["dee"].post("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 8000}]},
                       idem=key())
    assert r.status == 201, r


# ---------------------------------------------------------------- void

def test_void(api, au):
    # ledger: 1188, 1189, 1190, 1191, 1192, 1193
    assert is_error(au["bob"].post("/authorizations/a_1/void"), 403, "forbidden")
    assert is_error(au["cy"].post("/authorizations/a_1/void"), 403, "forbidden")
    r = au["ada"].post("/authorizations/a_1/void")
    assert r.status == 200 and r.json["status"] == "voided", r
    assert wallet(au["ada"]) == (10000, 10000, 0)
    assert au["ada"].post("/authorizations/a_1/void").status == 200
    assert is_error(capture(au["bob"], "a_1"), 409, "authorization_not_open")
    assert is_error(au["ada"].post("/authorizations/a_old/void"), 409, "authorization_not_open")
    a = authorize(au["ada"], "bob", 10).json
    capture(au["bob"], a["authorization_id"])
    assert is_error(au["ada"].post(f"/authorizations/{a['authorization_id']}/void"), 409, "authorization_not_open")
    assert is_error(au["ada"].post("/authorizations/a_nope/void"), 404, "not_found")


# ---------------------------------------------------------------- expiry by the clock

def test_expiry_without_any_request_at_deadline(api):
    # ledger: 1106, 1147, 1148, 1149, 1183, 1200, 1201
    api.reset(auth_fixture(authorization_ttl_seconds=2))
    ada, bob = api.session("ada@example.com"), api.session("bob@example.com")
    a = authorize(ada, "bob", 1000).json
    assert wallet(ada) == (10000, 7000, 3000)
    time.sleep(3.2)
    assert wallet(ada) == (10000, 8000, 2000)
    st = [x for x in auths(ada)["authorizations"] if x["authorization_id"] == a["authorization_id"]][0]
    assert st["status"] == "expired" and st["remaining_amount"] == 0
    assert is_error(capture(bob, a["authorization_id"]), 409, "authorization_expired")
    assert [x["authorization_id"] for x in auths(ada, status="open")["authorizations"]] == ["a_1"]
    assert a["authorization_id"] in {x["authorization_id"] for x in auths(ada, status="expired")["authorizations"]}


def test_partial_then_expiry_keeps_captures(api):
    # ledger: 1180
    api.reset(auth_fixture(authorization_ttl_seconds=2))
    ada, bob = api.session("ada@example.com"), api.session("bob@example.com")
    a = authorize(ada, "bob", 1000).json
    p = capture(bob, a["authorization_id"], {"amount": 400, "final": False}).json
    time.sleep(3.2)
    st = [x for x in auths(bob)["authorizations"] if x["authorization_id"] == a["authorization_id"]][0]
    assert st["status"] == "expired" and st["captured_amount"] == 400 and st["payment_ids"] == [p["payment_id"]]
    assert wallet(ada) == (9600, 7600, 2000)


# ---------------------------------------------------------------- GET /authorizations

def test_list_authorizations(api, au):
    # ledger: 1194, 1195, 1196, 1197, 1198, 1199, 1200, 1201, 1202
    new = authorize(au["ada"], "bob", 10).json["authorization_id"]
    ids = [x["authorization_id"] for x in auths(au["ada"])["authorizations"]]
    assert ids[0] == new and set(ids) == {new, "a_1", "a_old", "a_done"}
    assert {x["authorization_id"] for x in auths(au["ada"], direction="outgoing")["authorizations"]} == {new, "a_1", "a_old"}
    assert {x["authorization_id"] for x in auths(au["ada"], direction="incoming")["authorizations"]} == {"a_done"}
    assert {x["authorization_id"] for x in auths(au["cy"])["authorizations"]} == {"a_old"}
    assert auths(au["dee"])["authorizations"] == []
    old = auths(au["cy"])["authorizations"][0]
    assert old["status"] == "expired"
    assert auths(au["cy"], status="open")["authorizations"] == []
    pg = auths(au["ada"], limit=1)
    assert len(pg["authorizations"]) == 1 and pg["has_more"] is True
    for p in [{"limit": "0"}, {"limit": "+1"}, {"offset": "-1"}, {"status": "closed"}, {"direction": "up"}]:
        assert is_error(au["ada"].get("/authorizations", params=p), 422, "validation_failed"), p
    assert is_error(api.req("GET", "/authorizations"), 401, "unauthenticated")


def test_seven_write_paths_need_keys(api, au):
    # ledger: 1131, 1153, 1163
    for path, body in [("/authorizations", {"to_handle": "bob", "amount": 1}),
                       ("/authorizations/a_1/capture", {})]:
        assert is_error(au["bob" if "capture" in path else "ada"].post(path, body), 400, "missing_idempotency_key")


# ---------------------------------------------------------------- content negotiation

@pytest.mark.parametrize("path", ["/requests", "/authorizations"])
def test_shared_routes_negotiate(api, au, path):
    # ledger: 1013, 1014, 1204
    r = api.c.get(path, headers={"Accept": "text/html"})
    assert r.status_code == 200 and "text/html" in r.headers.get("content-type", ""), r
    j = au["ada"].get(path)
    assert j.status == 200 and isinstance(j.json, dict)
    assert is_error(api.req("GET", path), 401, "unauthenticated")


# ---------------------------------------------------------------- export/import with holds, upgrade

def test_export_import_preserves_holds(api, au):
    # ledger: 1095, 1132
    k = key()
    c = capture(au["bob"], "a_1", {"amount": 100, "final": False}, idem=k)
    snap = api.req("GET", "/_test/export").json
    assert snap["format_version"] == 1 and snap["track"] == "pocketful"
    api.reset(base_fixture())
    assert api.req("POST", "/_test/import", body=snap).status == 204
    assert wallet(au["ada"]) == (9900, 8000, 1900)
    r = capture(au["bob"], "a_1", {"amount": 100, "final": False}, idem=k)
    assert r.status == 200 and r.json == c.json


def test_upgrade_from_stage1_export(api):
    # ledger: 1095, 1146 (D-12)
    s1 = os.environ.get("PF_STAGE1_URL")
    if not s1:
        pytest.skip("no stage-1 instance (run_checks starts one in --repo mode)")
    old = Api(s1)
    try:
        fx = base_fixture(settlement_operator_ids=["u_dee"])
        old.reset(fx)
        ss = old.sessions(fx)
        k = key()
        p = ss["ada"].pay("bob", 250, idem=k, note="before upgrade")
        assert p.status == 201
        q = ss["bob"].request("ada", 40).json["request_id"]
        snap = old.req("GET", "/_test/export").json
    finally:
        old.close()
    api.reset(base_fixture(users=[{"id": "u_z", "email": "z@example.com", "password": PASSWORD,
                                   "display_name": "Z", "handle": "zz", "balance": 1}], payments=[], requests=[]))
    r = api.req("POST", "/_test/import", body=snap)
    assert r.status == 204, r
    hd = lambda s, idem=None: {"Authorization": f"Bearer {s.token}", **({"Idempotency-Key": idem} if idem else {})}
    m = api.req("GET", "/me", headers=hd(ss["ada"]))
    assert m.status == 200 and m.json["balance"] == m.json["total"] == m.json["available"] == 9750 and m.json["held"] == 0
    rp = api.req("POST", "/payments", headers=hd(ss["ada"], k),
                 body={"to_handle": "bob", "amount": 250, "note": "before upgrade"})
    assert rp.status == 200 and rp.json["payment_id"] == p.json["payment_id"], rp
    pay = api.req("POST", f"/requests/{q}/pay", headers=hd(ss["ada"], key()), body={})
    assert pay.status == 201 and pay.json["authorization_id"] is None, pay
    assert api.req("GET", "/authorizations", headers=hd(ss["ada"])).json["authorizations"] == []


def test_split_unchanged_with_holds(api, au):
    # ledger: 1130
    r = au["cy"].post("/splits", {"amount": 3000, "participant_handles": ["ada", "bob", "cy"]}, idem=key())
    assert r.status == 201 and [x["amount"] for x in r.json["shares"]] == [1000, 1000, 1000], r
    assert wallet(au["ada"]) == (10000, 8000, 2000)
    q = [x for x in r.json["requests"] if x["payer_handle"] == "ada"][0]["request_id"]
    assert au["ada"].pay_request(q).status == 201
    assert wallet(au["ada"]) == (9000, 7000, 2000)
