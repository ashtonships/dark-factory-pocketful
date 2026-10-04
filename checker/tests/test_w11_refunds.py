"""W-11: stage-4 refunds, refund limits on corrections, unchanged receipts, imports from stages 1-3."""

from __future__ import annotations

import os

import pytest

from pf import Api, base_fixture, is_error, key, parallel
from s3 import T1, T2, T3, TOTAL, at, history_fixture, user

pytestmark = pytest.mark.item("W-11")


@pytest.fixture
def h(api):
    fx = history_fixture()
    api.reset(fx)
    return api.sessions(fx)


def refund(s, pid, amount, idem=None):
    return s.post(f"/payments/{pid}/refunds", {"amount": amount}, idem=idem or key())


def correct(s, pid, amount, eff, rev=1, idem=None):
    return s.post(f"/payments/{pid}/corrections",
                  {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": "fix"},
                  idem=idem or key())


def bal(s):
    return s.balance()


def feed(s):
    r = s.get("/activity", {"limit": 200})
    assert r.status == 200, r
    return {p["payment_id"]: p for p in r.json["payments"]}


def capture_payment(h, held=300, **cap):
    a = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": held}, idem=key())
    assert a.status == 201, a
    c = h["bob"].post(f"/authorizations/{a.json['authorization_id']}/capture", cap, idem=key())
    assert c.status == 201, c
    return a.json, c.json


# ---------------------------------------------------------------- shape and replay

def test_refund_shape_and_money(api, h):
    # ledger: 3001, 3006, 3012, 3013, 3014, D-22
    k = key()
    r = refund(h["bob"], "p_a", 200, idem=k)
    assert r.status == 201, r
    p = r.json
    assert p["payment_id"] not in ("p_a",) and p["refund_of"] == "p_a"
    assert p["from_user_id"] == "u_bob" and p["to_user_id"] == "u_ada"
    assert p["from_handle"] == "bob" and p["to_handle"] == "ada"
    assert p["amount"] == 200 and p["request_id"] is None and p["authorization_id"] is None
    assert p["note"] == "rent" and p["visibility"] == "public" and at(p["created_at"])
    assert bal(h["ada"]) == 10200 and bal(h["bob"]) == 2300
    assert sum(bal(s) for s in h.values()) == TOTAL
    again = refund(h["bob"], "p_a", 200, idem=k)
    assert again.status == 200 and again.json == p
    assert bal(h["bob"]) == 2300
    assert is_error(refund(h["bob"], "p_a", 201, idem=k), 409, "idempotency_key_reuse")
    rv = h["bob"].get(f"/payments/{p['payment_id']}/revisions")
    assert rv.status == 200, rv
    revs = rv.json["revisions"]
    assert len(revs) == 1 and revs[0]["revision"] == 1 and revs[0]["amount"] == 200
    assert at(revs[0]["effective_at"]) == at(revs[0]["recorded_at"]) == at(p["created_at"])


def test_refund_keeps_private_visibility_and_note(api, h):
    # ledger: 3012
    p = refund(h["cy"], "p_b", 100).json
    assert p["visibility"] == "private" and p["note"] == "" and p["refund_of"] == "p_b"
    assert p["payment_id"] in feed(h["bob"]) and p["payment_id"] not in feed(h["ada"])


def test_refund_of_null_on_other_payments(api, h):
    # ledger: 3016
    pay = h["ada"].pay("bob", 5).json
    assert "refund_of" in pay and pay["refund_of"] is None
    rq = h["bob"].request("ada", 7).json["request_id"]
    assert h["ada"].pay_request(rq).json["refund_of"] is None
    _, cap = capture_payment(h)
    assert cap["refund_of"] is None
    s = h["dee"].post("/settlements", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]},
                      idem=key()).json
    assert s["payments"][0]["refund_of"] is None
    rf = refund(h["bob"], "p_a", 1).json
    for pid, p in feed(h["ada"]).items():
        assert "refund_of" in p, p
        assert p["refund_of"] == ("p_a" if pid == rf["payment_id"] else None), p


# ---------------------------------------------------------------- who and what

def test_refund_auth_and_target(api, h):
    # ledger: 3006, 3007, D-21
    body = {"amount": 10}
    assert is_error(api.req("POST", "/payments/p_a/refunds", body=body, headers={"Idempotency-Key": key()}),
                    401, "unauthenticated")
    assert is_error(refund(h["ada"], "p_a", 10), 403, "forbidden")      # payer
    assert is_error(refund(h["cy"], "p_a", 10), 403, "forbidden")       # third party
    assert is_error(refund(h["bob"], "nope", 10), 404, "not_found")
    assert is_error(h["bob"].post("/payments/p_a/refunds", body), 400, "missing_idempotency_key")
    assert is_error(h["bob"].post("/payments/p_a/refunds", body, idem=""), 400, "missing_idempotency_key")
    assert is_error(h["bob"].post("/payments/p_a/refunds", raw="{bad", idem=key()), 400, "malformed_request")
    # validation before 404 before 403 (D-21)
    assert is_error(refund(h["bob"], "nope", 0), 422, "validation_failed")
    assert is_error(refund(h["ada"], "p_a", 0), 422, "validation_failed")
    assert is_error(refund(h["ada"], "nope", 10), 404, "not_found")
    assert bal(h["bob"]) == 2500 and bal(h["ada"]) == 10000


@pytest.mark.parametrize("amount", [0, -5, 10.5, 1000000001, "100", True, None, [1]])
def test_refund_amount_invalid(api, h, amount):
    # ledger: 3009, D-21
    assert is_error(refund(h["bob"], "p_a", amount), 422, "validation_failed")
    assert is_error(h["bob"].post("/payments/p_a/refunds", {}, idem=key()), 422, "validation_failed")
    assert bal(h["bob"]) == 2500


def test_refund_request_payment(api, h):
    # ledger: 3008, 3015
    rq = h["bob"].request("ada", 400, note="taxi").json["request_id"]
    p = h["ada"].pay_request(rq).json
    r = refund(h["bob"], p["payment_id"], 400)
    assert r.status == 201 and r.json["refund_of"] == p["payment_id"] and r.json["request_id"] is None
    assert r.json["note"] == "taxi"
    req = [x for x in h["bob"].get("/requests", {"direction": "outgoing", "limit": 200}).json["requests"]
           if x["request_id"] == rq]
    assert req and req[0]["status"] == "paid"


def test_refund_capture_leaves_authorization(api, h):
    # ledger: 3008, 3015, D-22
    a, cap = capture_payment(h, 300, amount=100, final=False)
    held_before = h["ada"].me().json["held"]
    assert held_before == 200
    r = refund(h["bob"], cap["payment_id"], 100)
    assert r.status == 201 and r.json["refund_of"] == cap["payment_id"] and r.json["authorization_id"] is None
    got = [x for x in h["ada"].get("/authorizations").json["authorizations"]
           if x["authorization_id"] == a["authorization_id"]][0]
    assert got["status"] == "open" and got["captured_amount"] == 100 and got["remaining_amount"] == 200
    m = h["ada"].me().json
    assert m["held"] == 200 and m["total"] == 10000 and m["available"] == 9800
    # a released hold is not restored by a refund
    v = h["ada"].post(f"/authorizations/{a['authorization_id']}/void")
    assert v.status in (200, 201), v
    a2, cap2 = capture_payment(h, 50)  # final capture releases nothing more
    assert refund(h["bob"], cap2["payment_id"], 50).status == 201
    m = h["ada"].me().json
    assert m["held"] == 0 and m["available"] == m["total"]
    got = [x for x in h["ada"].get("/authorizations").json["authorizations"]
           if x["authorization_id"] == a2["authorization_id"]][0]
    assert got["status"] == "captured"


def test_refund_of_refund_rejected(api, h):
    # ledger: 3008, 3011, 3018
    rf = refund(h["bob"], "p_a", 300).json
    assert is_error(refund(h["ada"], rf["payment_id"], 10), 422, "invalid_refund_target")
    assert is_error(refund(h["bob"], rf["payment_id"], 10), 403, "forbidden")  # bob is the refund's payer
    assert is_error(correct(h["bob"], rf["payment_id"], 100, rf["created_at"]), 422, "linked_payment_immutable")
    assert bal(h["ada"]) == 10300 and bal(h["bob"]) == 2200


# ---------------------------------------------------------------- limits

def test_refunds_cumulative_limit(api, h):
    # ledger: 3010
    assert refund(h["bob"], "p_a", 600).status == 201
    assert is_error(refund(h["bob"], "p_a", 401), 422, "refund_exceeds_payment")
    assert refund(h["bob"], "p_a", 400).status == 201
    assert is_error(refund(h["bob"], "p_a", 1), 422, "refund_exceeds_payment")
    assert bal(h["bob"]) == 1500 and bal(h["ada"]) == 11000


def test_refund_limit_follows_corrected_amount(api, h):
    # ledger: 3010, D-22
    assert correct(h["ada"], "p_a", 500, T1).status == 201
    assert is_error(refund(h["bob"], "p_a", 501), 422, "refund_exceeds_payment")
    assert refund(h["bob"], "p_a", 500).status == 201
    assert correct(h["ada"], "p_c", 350, T2).status == 201      # an increase raises the limit
    assert refund(h["cy"], "p_c", 350).status == 201


def test_refund_needs_available_funds(api, h):
    # ledger: 3014
    a = h["bob"].post("/authorizations", {"to_handle": "cy", "amount": 2000}, idem=key())
    assert a.status == 201, a                                       # bob: total 2500, available 500
    assert is_error(refund(h["bob"], "p_a", 501), 409, "insufficient_funds")
    assert bal(h["bob"]) == 2500 and bal(h["ada"]) == 10000
    assert refund(h["bob"], "p_a", 500).status == 201
    m = h["bob"].me().json
    assert (m["total"], m["held"], m["available"]) == (2000, 2000, 0)


def test_refund_exceeds_before_insufficient(api, h):
    # ledger: D-21
    # bob received p_a (1000) and spent it all on p_x: he holds nothing now
    fx = history_fixture(
        users=[user("u_ada", "ada", 10000), user("u_bob", "bob", 0), user("u_dee", "dee", 1700)],
        payments=[{"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1000, "note": "",
                   "visibility": "public", "created_at": T1},
                  {"id": "p_x", "from_user_id": "u_bob", "to_user_id": "u_dee", "amount": 1000, "note": "",
                   "visibility": "public", "created_at": T2}])
    api.reset(fx)
    bob = api.session("bob@example.com")
    assert is_error(refund(bob, "p_a", 1001), 422, "refund_exceeds_payment")
    assert is_error(refund(bob, "p_a", 1000), 409, "insufficient_funds")


def test_correction_cannot_go_below_refunded(api, h):
    # ledger: 3019, 3017, D-22
    assert refund(h["bob"], "p_a", 600).status == 201
    assert is_error(correct(h["ada"], "p_a", 599, T1), 422, "refund_exceeds_payment")
    assert is_error(correct(h["ada"], "p_a", 599, T1, rev=2), 409, "stale_revision")  # stale first
    r = correct(h["ada"], "p_a", 600, T1)
    assert r.status == 201 and r.json["revision"] == 2
    assert bal(h["ada"]) == 10000 + 600 + 400 and bal(h["bob"]) == 2500 - 600 - 400


def test_correction_debit_against_available(api, h):
    # ledger: 3020
    assert h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 9500}, idem=key()).status == 201
    assert is_error(correct(h["ada"], "p_a", 1501, T1), 409, "insufficient_funds")  # debit 501 > available 500
    assert bal(h["ada"]) == 10000
    assert correct(h["ada"], "p_a", 1500, T1).status == 201


def test_concurrent_refunds_never_exceed(api):
    # ledger: 3010, 3014
    for _ in range(3):
        fx = history_fixture()
        api.reset(fx)
        bob, ada = api.session("bob@example.com"), api.session("ada@example.com")
        res = parallel([lambda: refund(bob, "p_a", 100) for _ in range(20)])
        assert all(r.status < 500 for r in res), [r for r in res if r.status >= 500]
        assert sum(r.status == 201 for r in res) == 10, [r.status for r in res]
        assert all(r.status == 201 or is_error(r, 422, "refund_exceeds_payment") for r in res)
        assert bob.balance() == 1500 and ada.balance() == 11000


# ---------------------------------------------------------------- receipts, settlements, statements

def test_original_receipts_unchanged(api, h):
    # ledger: 3003, 3038, 3039
    k = key()
    p = h["ada"].pay("bob", 300, idem=k).json
    assert refund(h["bob"], p["payment_id"], 100).status == 201
    assert correct(h["ada"], p["payment_id"], 250, p["created_at"]).status == 201
    r = h["ada"].pay("bob", 300, idem=k)
    assert r.status == 200 and r.json == p
    assert feed(h["ada"])[p["payment_id"]]["amount"] == 300


def test_settlement_member_refund(api, h):
    # ledger: 3043, 3039
    sk = key()
    body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                          {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}
    s = h["dee"].post("/settlements", body, idem=sk).json
    m = s["payments"][0]
    r = refund(h["bob"], m["payment_id"], 40)
    assert r.status == 201, r
    assert r.json["refund_of"] == m["payment_id"] and r.json.get("settlement_id") is None
    assert is_error(refund(h["bob"], m["payment_id"], 61), 422, "refund_exceeds_payment")
    again = h["dee"].post("/settlements", body, idem=sk)
    assert again.status == 200 and again.json == s
    assert feed(h["ada"])[m["payment_id"]]["settlement_id"] == s["settlement_id"]


def test_refund_in_statement_and_snapshot(api, h):
    # ledger: 3003, 3012
    first = h["ada"].get("/statement").json
    tok = first["snapshot"]
    rf = refund(h["bob"], "p_a", 250).json
    st = h["ada"].get("/statement").json
    e = [x for x in st["entries"] if x["payment"]["payment_id"] == rf["payment_id"]]
    assert len(e) == 1 and e[0]["delta"] == 250 and e[0]["payment"]["refund_of"] == "p_a"
    assert st["closing_balance"] == 10250
    old = h["ada"].get("/statement", params={"snapshot": tok})
    assert old.status == 200 and old.json["entries"] == first["entries"]
    assert old.json["closing_balance"] == first["closing_balance"] == 10000
    bob = h["bob"].get("/statement").json
    assert [x["delta"] for x in bob["entries"] if x["payment"]["payment_id"] == rf["payment_id"]] == [-250]
    m = h["ada"].get("/me", params={"as_of": T3}).json
    assert m["balance"] == 10000  # a refund takes effect now, not in the past


# ---------------------------------------------------------------- imports

def export(base):
    a = Api(base)
    try:
        r = a.req("GET", "/_test/export")
        assert r.status == 200, r
        return r.json
    finally:
        a.close()


@pytest.mark.parametrize("stage_env", ["PF_STAGE1_URL", "PF_STAGE2_URL", "PF_STAGE3_URL"])
def test_import_earlier_stage_export(api, stage_env):
    # ledger: 3045, D-24
    url = os.environ.get(stage_env)
    if not url:
        pytest.skip(f"no {stage_env} instance (run_checks starts earlier stages in --repo mode)")
    old = Api(url)
    try:
        fx = base_fixture(settlement_operator_ids=["u_dee"])
        old.reset(fx)
        ss = old.sessions(fx)
        k = key()
        p = ss["ada"].pay("bob", 250, idem=k).json
        sk = key()
        sbody = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                               {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}
        s = ss["dee"].post("/settlements", sbody, idem=sk).json
        if stage_env == "PF_STAGE3_URL":
            c = ss["ada"].post(f"/payments/{p['payment_id']}/corrections",
                               {"expected_revision": 1, "amount": 200, "effective_at": p["created_at"],
                                "reason": "fix"}, idem=key())
            assert c.status == 201, c
        snap = old.req("GET", "/_test/export").json
    finally:
        old.close()
    api.reset(base_fixture())
    assert api.req("POST", "/_test/import", body=snap).status == 204
    hd = lambda s: {"Authorization": f"Bearer {s.token}"}
    want_ada = 10000 - 100 - (200 if stage_env == "PF_STAGE3_URL" else 250)
    assert api.req("GET", "/me", headers=hd(ss["ada"])).json["balance"] == want_ada
    r = api.req("POST", "/payments", headers={**hd(ss["ada"]), "Idempotency-Key": k},
                body={"to_handle": "bob", "amount": 250})
    assert r.status == 200 and r.json["payment_id"] == p["payment_id"]
    r = api.req("POST", "/settlements", headers={**hd(ss["dee"]), "Idempotency-Key": sk}, body=sbody)
    assert r.status == 200 and r.json["settlement_id"] == s["settlement_id"]
    rv = api.req("GET", f"/payments/{p['payment_id']}/revisions", headers=hd(ss["ada"])).json["revisions"]
    assert [x["amount"] for x in rv] == ([250, 200] if stage_env == "PF_STAGE3_URL" else [250])
    acts = api.req("GET", "/activity", headers=hd(ss["ada"]), params={"limit": 200}).json["payments"]
    assert acts and all("refund_of" in x and x["refund_of"] is None for x in acts)
    # settlement membership survived: a member is still not correctable on its own
    m = s["payments"][0]
    r = api.req("POST", f"/payments/{m['payment_id']}/corrections", headers={**hd(ss["ada"]), "Idempotency-Key": key()},
                body={"expected_revision": 1, "amount": 1, "effective_at": s["committed_at"], "reason": "x"})
    assert is_error(r, 422, "linked_payment_immutable"), r
    # and refunds work on imported payments
    r = api.req("POST", f"/payments/{p['payment_id']}/refunds", headers={**hd(ss["bob"]), "Idempotency-Key": key()},
                body={"amount": 10})
    assert r.status == 201 and r.json["refund_of"] == p["payment_id"]


def test_stage4_export_import_keeps_snapshots_and_refunds(api):
    # ledger: 3045, D-24 (snapshots survive export -> import into another instance)
    url2 = os.environ.get("PF_BASE_URL_2")
    if not url2:
        pytest.skip("no second instance (run_checks starts one in --repo mode)")
    fx = history_fixture()
    api.reset(fx)
    ada, bob = api.session("ada@example.com"), api.session("bob@example.com")
    rf = refund(bob, "p_a", 300).json
    st = ada.get("/statement", params={"limit": 2}).json
    snap = api.req("GET", "/_test/export").json
    other = Api(url2)
    try:
        other.reset(history_fixture())
        assert other.req("POST", "/_test/import", body=snap).status == 204
        hd = {"Authorization": f"Bearer {ada.token}"}
        page = other.req("GET", "/statement", headers=hd, params={"snapshot": st["snapshot"], "limit": 2})
        assert page.status == 200, page
        assert page.json["entries"] == st["entries"] and page.json["closing_balance"] == st["closing_balance"]
        r = other.req("POST", "/payments/p_a/refunds", headers={"Authorization": f"Bearer {bob.token}",
                                                                 "Idempotency-Key": key()}, body={"amount": 701})
        assert is_error(r, 422, "refund_exceeds_payment"), r  # the imported refund still counts
        acts = other.req("GET", "/activity", headers=hd, params={"limit": 200}).json["payments"]
        assert [x["refund_of"] for x in acts if x["payment_id"] == rf["payment_id"]] == ["p_a"]
    finally:
        other.close()
