"""W-9: stage-3 write side - payment timestamps, revision history, corrections, linked payments, imports."""

from __future__ import annotations

import os

import pytest

from pf import Api, base_fixture, is_error, key, parallel
from s3 import OPENING, T1, T2, T3, TOTAL, at, history_fixture, now_iso, shift, user

pytestmark = pytest.mark.item("W-9")


@pytest.fixture
def h(api):
    fx = history_fixture()
    api.reset(fx)
    return api.sessions(fx)


def correct(s, pid, amount, eff, rev=1, reason="fix", idem=None):
    return s.post(f"/payments/{pid}/corrections",
                  {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": reason},
                  idem=idem or key())


def revisions(s, pid):
    r = s.get(f"/payments/{pid}/revisions")
    assert r.status == 200, r
    return r.json["revisions"]


def bal(s):
    return s.balance()


# ---------------------------------------------------------------- timestamps and seeding

def test_seeded_created_at_and_balances(api, h):
    # ledger: 2001, 2006, 2007, 2009, 2011, 2012, 2041
    feed = {p["payment_id"]: p for p in h["ada"].get("/activity", {"limit": 200}).json["payments"]}
    assert at(feed["p_a"]["created_at"]) == at(T1) and at(feed["p_d"]["created_at"]) == at(T3)
    assert [bal(h[x]) for x in ("ada", "bob", "cy", "dee")] == [10000, 2500, 500, 700]
    order = [p["payment_id"] for p in h["ada"].get("/activity", {"limit": 200}).json["payments"]]
    assert order.index("p_d") < order.index("p_a")  # ledger: 2008, newest first


def test_seeded_without_created_at_precedes_api_payments(api):
    # ledger: 2009, 2002
    fx = history_fixture()
    del fx["payments"][0]["created_at"]
    api.reset(fx)
    ada = api.session("ada@example.com")
    new = ada.pay("bob", 1).json
    seeded = [p for p in ada.get("/activity", {"limit": 200}).json["payments"] if p["payment_id"] == "p_a"][0]
    assert at(seeded["created_at"]) <= at(new["created_at"])


def test_future_seeded_created_at_rejected(api, h):
    # ledger: 2010
    fx = history_fixture()
    fx["payments"][0]["created_at"] = now_iso(3600)
    fx["users"][0]["email"] = "changed@example.com"
    assert is_error(api.req("POST", "/_test/reset", body=fx), 422, "validation_failed")
    assert api.login("ada@example.com").status == 200 and api.login("changed@example.com").status == 401


def test_api_payment_has_created_at_everywhere(api, h):
    # ledger: 2006, 2007
    p = h["ada"].pay("bob", 5).json
    assert at(p["created_at"])
    q = h["bob"].request("ada", 7).json["request_id"]
    pp = h["ada"].pay_request(q).json
    assert at(pp["created_at"]) >= at(p["created_at"])


# ---------------------------------------------------------------- revisions

def test_revision_one(api, h):
    # ledger: 2038, 2039, 2040, 2041, 2067
    r = revisions(h["ada"], "p_a")
    assert len(r) == 1
    assert r[0]["revision"] == 1 and r[0]["amount"] == 1000 and r[0]["reason"] == ""
    assert at(r[0]["effective_at"]) == at(T1) and at(r[0]["recorded_at"]) == at(T1)
    p = h["ada"].pay("bob", 5).json
    r = revisions(h["bob"], p["payment_id"])
    assert at(r[0]["effective_at"]) == at(r[0]["recorded_at"]) == at(p["created_at"])


def test_revisions_access(api, h):
    # ledger: 2068, 2069
    assert revisions(h["bob"], "p_a")  # receiver may read
    assert is_error(h["cy"].get("/payments/p_a/revisions"), 404, "not_found")  # public, third party
    assert is_error(api.req("GET", "/payments/p_a/revisions"), 401, "unauthenticated")
    assert is_error(h["ada"].get("/payments/nope/revisions"), 404, "not_found")


# ---------------------------------------------------------------- corrections

def test_correction_decrease_debits_receiver(api, h):
    # ledger: 2046, 2052, 2053, 2058, 2059, 2054, 2065, 2066
    feed_before = h["cy"].get("/activity", {"limit": 200}).json["payments"]
    r = correct(h["ada"], "p_a", 400, T1, reason="overpaid")
    assert r.status == 201, r
    c = r.json
    assert c["payment_id"] == "p_a" and c["revision"] == 2 and c["amount"] == 400 and c["reason"] == "overpaid"
    assert at(c["effective_at"]) == at(T1) and at(c["recorded_at"]) > at(T1)
    assert bal(h["ada"]) == 10600 and bal(h["bob"]) == 1900
    revs = revisions(h["bob"], "p_a")
    assert [x["revision"] for x in revs] == [1, 2]
    assert at(revs[1]["recorded_at"]) > at(revs[0]["recorded_at"])
    feed = [p for p in h["cy"].get("/activity", {"limit": 200}).json["payments"] if p["payment_id"] == "p_a"]
    assert len(feed) == 1 and feed[0]["amount"] == 1000 and feed[0]["visibility"] == "public"
    assert feed[0]["from_handle"] == "ada" and feed[0]["to_handle"] == "bob"
    assert h["cy"].get("/activity", {"limit": 200}).json["payments"] == feed_before  # no new or changed feed item


def test_correction_increase_debits_sender_and_zero_reverses(api, h):
    # ledger: 2050, 2059
    assert correct(h["ada"], "p_a", 1500, T1).status == 201
    assert bal(h["ada"]) == 9500 and bal(h["bob"]) == 3000
    assert correct(h["ada"], "p_a", 0, T1, rev=2).status == 201
    assert bal(h["ada"]) == 11000 and bal(h["bob"]) == 1500
    assert sum(bal(s) for s in h.values()) == TOTAL


def test_recorded_at_strictly_increases_rapid(api, h):
    # ledger: 2054 (D-18)
    rev = 1
    for amt in (900, 800, 700, 600):
        r = correct(h["ada"], "p_a", amt, T1, rev=rev)
        assert r.status == 201, r
        rev += 1
    times = [at(x["recorded_at"]) for x in revisions(h["ada"], "p_a")]
    assert all(a < b for a, b in zip(times, times[1:])), times


def test_original_idempotent_response_unchanged(api, h):
    # ledger: 2065
    k = key()
    p = h["ada"].pay("bob", 50, idem=k)
    assert correct(h["ada"], p.json["payment_id"], 20, p.json["created_at"]).status == 201
    r = h["ada"].pay("bob", 50, idem=k)
    assert r.status == 200 and r.json == p.json


@pytest.mark.parametrize("body", [
    {"amount": 400, "effective_at": T1, "reason": "x"},
    {"expected_revision": 1, "effective_at": T1, "reason": "x"},
    {"expected_revision": 1, "amount": 400, "reason": "x"},
    {"expected_revision": 1, "amount": 400, "effective_at": T1},
    {"expected_revision": 0, "amount": 400, "effective_at": T1, "reason": "x"},
    {"expected_revision": 1.5, "amount": 400, "effective_at": T1, "reason": "x"},
    {"expected_revision": 1, "amount": -1, "effective_at": T1, "reason": "x"},
    {"expected_revision": 1, "amount": 1000000001, "effective_at": T1, "reason": "x"},
    {"expected_revision": 1, "amount": 4.5, "effective_at": T1, "reason": "x"},
    {"expected_revision": 1, "amount": "400", "effective_at": T1, "reason": "x"},
    {"expected_revision": 1, "amount": 400, "effective_at": T1, "reason": ""},
    {"expected_revision": 1, "amount": 400, "effective_at": T1, "reason": "r" * 201},
    {"expected_revision": 1, "amount": 400, "effective_at": "2026-01-01T10:00:00", "reason": "x"},
    {"expected_revision": 1, "amount": 400, "effective_at": "2026-01-01", "reason": "x"},
    {"expected_revision": 1, "amount": 400, "effective_at": "", "reason": "x"},
    {"expected_revision": 1, "amount": 400, "effective_at": "FUTURE", "reason": "x"},
])
def test_correction_validation(api, h, body):
    # ledger: 2049, 2050, 2051
    if body.get("effective_at") == "FUTURE":
        body = dict(body, effective_at=now_iso(3600))
    r = h["ada"].post("/payments/p_a/corrections", body, idem=key())
    assert is_error(r, 422, "validation_failed"), r
    assert len(revisions(h["ada"], "p_a")) == 1 and bal(h["ada"]) == 10000


def test_correction_auth_and_key(api, h):
    # ledger: 2046, 2047
    body = {"expected_revision": 1, "amount": 400, "effective_at": T1, "reason": "x"}
    assert is_error(api.req("POST", "/payments/p_a/corrections", body=body, headers={"Idempotency-Key": key()}),
                    401, "unauthenticated")
    assert is_error(h["bob"].post("/payments/p_a/corrections", body, idem=key()), 403, "forbidden")
    assert is_error(h["cy"].post("/payments/p_a/corrections", body, idem=key()), 403, "forbidden")
    assert is_error(h["ada"].post("/payments/nope/corrections", body, idem=key()), 404, "not_found")
    assert is_error(h["ada"].post("/payments/p_a/corrections", body), 400, "missing_idempotency_key")


def test_stale_revision_and_replay(api, h):
    # ledger: 2055, 2056, 2057, 2063
    k = key()
    first = correct(h["ada"], "p_a", 400, T1, idem=k)
    assert first.status == 201
    assert is_error(correct(h["ada"], "p_a", 300, T1, rev=1), 409, "stale_revision")
    assert correct(h["ada"], "p_a", 300, T1, rev=2).status == 201
    again = correct(h["ada"], "p_a", 400, T1, idem=k)
    assert again.status == 200 and again.json == first.json
    assert is_error(correct(h["ada"], "p_a", 401, T1, idem=k), 409, "idempotency_key_reuse")
    assert bal(h["ada"]) == 10700 and len(revisions(h["ada"], "p_a")) == 3


def test_insufficient_funds_now_takes_precedence(api, h):
    # ledger: 2060, 2063, 2112
    r = correct(h["cy"], "p_d", 700, T3)  # cy has 500 now; the increase debits cy 600
    assert is_error(r, 409, "insufficient_funds"), r
    assert bal(h["cy"]) == 500 and len(revisions(h["cy"], "p_d")) == 1


def overdraft_fixture():
    # x opens at 0, receives 100 at T1 (from y), pays 100 at T2 (to z), receives 100 at T3 (from z)
    return {
        "currency": "EUR", "minor_units": 2, "settlement_operator_ids": [],
        "users": [user("u_x", "x", 100), user("u_y", "y", 5000), user("u_z", "z", 0)],
        "payments": [
            {"id": "q_1", "from_user_id": "u_y", "to_user_id": "u_x", "amount": 100, "note": "",
             "visibility": "public", "created_at": T1},
            {"id": "q_2", "from_user_id": "u_x", "to_user_id": "u_z", "amount": 100, "note": "",
             "visibility": "public", "created_at": T2},
            {"id": "q_3", "from_user_id": "u_z", "to_user_id": "u_x", "amount": 100, "note": "",
             "visibility": "public", "created_at": T3},
        ],
        "requests": [], "authorizations": [],
    }


def test_historical_overdraft(api):
    # ledger: 2061, 2063, 2064, 2111
    api.reset(overdraft_fixture())
    y, x = api.session("y@example.com"), api.session("x@example.com")
    k = key()
    r = correct(y, "q_1", 50, T1, idem=k)  # x would be -50 after q_2 at T2, though x has 100 now
    assert is_error(r, 409, "historical_overdraft"), r
    assert bal(x) == 100 and bal(y) == 5000 and len(revisions(y, "q_1")) == 1
    # the failed key claimed nothing: same key, different body is a first use
    assert correct(y, "q_1", 100, T1, idem=k).status == 201
    # moving the payment later than the spend also overdraws at T2
    assert is_error(correct(y, "q_1", 100, T3, rev=2), 409, "historical_overdraft")


def test_simultaneous_movements_combine_at_boundary(api):
    # ledger: 2062 (out sorts before in by id at the same instant; the boundary nets them)
    fx = {
        "currency": "EUR", "minor_units": 2, "settlement_operator_ids": [],
        "users": [user("u_w", "w", 0), user("u_v", "v", 1000), user("u_u", "u", 100)],
        "payments": [
            {"id": "a_out", "from_user_id": "u_w", "to_user_id": "u_u", "amount": 100, "note": "",
             "visibility": "public", "created_at": T2},
            {"id": "b_in", "from_user_id": "u_v", "to_user_id": "u_w", "amount": 100, "note": "",
             "visibility": "public", "created_at": T2},
        ],
        "requests": [], "authorizations": [],
    }
    api.reset(fx)
    v = api.session("v@example.com")
    r = correct(v, "b_in", 150, T2)  # increases what w received; must not be judged per-entry by id
    assert r.status == 201, r


def test_concurrent_same_expected_revision_one_wins(api):
    # ledger: 2095, 2064
    for _ in range(3):
        fx = history_fixture()
        api.reset(fx)
        ada = api.session("ada@example.com")
        res = parallel([lambda a=a: correct(ada, "p_a", a, T1) for a in range(500, 520)])
        assert all(r.status < 500 for r in res), [r for r in res if r.status >= 500]
        assert sum(r.status == 201 for r in res) == 1, [r.status for r in res]
        assert all(r.status == 201 or is_error(r, 409, "stale_revision") for r in res)
        won = [r for r in res if r.status == 201][0].json["amount"]
        assert ada.balance() == 10000 + (1000 - won)
        assert len(revisions(ada, "p_a")) == 2


# ---------------------------------------------------------------- linked payments

def test_settlement_members_immutable(api, h):
    # ledger: 2096, 2097, 2098
    s = h["dee"].post("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]},
                      idem=key()).json
    m = s["payments"][0]
    rv = revisions(h["ada"], m["payment_id"])
    assert at(rv[0]["effective_at"]) == at(rv[0]["recorded_at"]) == at(s["committed_at"])
    r = correct(h["ada"], m["payment_id"], 5, s["committed_at"])
    assert is_error(r, 422, "linked_payment_immutable"), r


def test_capture_immutable_and_closed_at(api, h):
    # ledger: 2100, 2101, 2109
    a = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 300}, idem=key()).json
    assert "closed_at" in a and a["closed_at"] is None
    p = h["bob"].post(f"/authorizations/{a['authorization_id']}/capture", {}, idem=key()).json
    r = correct(h["ada"], p["payment_id"], 100, p["created_at"])
    assert is_error(r, 422, "linked_payment_immutable"), r
    got = [x for x in h["ada"].get("/authorizations").json["authorizations"]
           if x["authorization_id"] == a["authorization_id"]][0]
    assert got["closed_at"] is not None and at(got["closed_at"])
    b = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 1}, idem=key()).json
    v = h["ada"].post(f"/authorizations/{b['authorization_id']}/void").json
    assert v["closed_at"] is not None


# ---------------------------------------------------------------- imports from earlier stages

@pytest.mark.parametrize("stage_env", ["PF_STAGE1_URL", "PF_STAGE2_URL"])
def test_import_earlier_stage_export(api, stage_env):
    # ledger: 2099, 2100, 2042, 2044
    url = os.environ.get(stage_env)
    if not url:
        pytest.skip(f"no {stage_env} instance (run_checks starts earlier stages in --repo mode)")
    old = Api(url)
    try:
        fx = base_fixture(settlement_operator_ids=["u_dee"])
        old.reset(fx)
        ss = old.sessions(fx)
        k = key()
        p = ss["ada"].pay("bob", 250, idem=k)
        if stage_env == "PF_STAGE2_URL":
            a = ss["ada"].post("/authorizations", {"to_handle": "bob", "amount": 400}, idem=key()).json
            ss["bob"].post(f"/authorizations/{a['authorization_id']}/capture", {"amount": 100, "final": False},
                           idem=key())
        snap = old.req("GET", "/_test/export").json
    finally:
        old.close()
    api.reset(base_fixture())
    assert api.req("POST", "/_test/import", body=snap).status == 204
    hd = {"Authorization": f"Bearer {ss['ada'].token}"}
    me = api.req("GET", "/me", headers=hd).json
    want_total = 10000 - 250 - (100 if stage_env == "PF_STAGE2_URL" else 0)
    assert me["balance"] == want_total
    if stage_env == "PF_STAGE2_URL":
        assert me["held"] == 300 and me["available"] == want_total - 300
    r = api.req("POST", "/payments", headers={**hd, "Idempotency-Key": k},
                body={"to_handle": "bob", "amount": 250})
    assert r.status == 200 and r.json["payment_id"] == p.json["payment_id"]
    rv = api.req("GET", f"/payments/{p.json['payment_id']}/revisions", headers=hd)
    assert rv.status == 200 and rv.json["revisions"][0]["amount"] == 250
    st = api.req("GET", "/statement", headers=hd).json
    assert st["opening_balance"] + sum(e["delta"] for e in st["entries"]) == st["closing_balance"] == want_total
