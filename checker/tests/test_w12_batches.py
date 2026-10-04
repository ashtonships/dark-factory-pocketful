"""W-12: stage-4 correction batches - operator auth, validation, settlements, precedence, atomicity, snapshots."""

from __future__ import annotations

import datetime as dt

import pytest

from pf import is_error, key, parallel
from s3 import T1, T2, T3, TOTAL, at, history_fixture, now_iso, user

pytestmark = pytest.mark.item("W-12")


@pytest.fixture
def h(api):
    fx = history_fixture()
    api.reset(fx)
    return api.sessions(fx)


def item(pid, amount, eff, rev=1, reason="fix", **extra):
    return {"payment_id": pid, "expected_revision": rev, "amount": amount, "effective_at": eff,
            "reason": reason, **extra}


def batch(s, items, idem=None, **extra):
    return s.post("/correction-batches", {"corrections": items, **extra}, idem=idem or key())


def revisions(s, pid):
    r = s.get(f"/payments/{pid}/revisions")
    assert r.status == 200, r
    return r.json["revisions"]


def bal(s):
    return s.balance()


def balances(h):
    return {k: bal(s) for k, s in h.items()}


def settle(h, transfers=None, idem=None):
    transfers = transfers or [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                              {"from_handle": "bob", "to_handle": "cy", "amount": 50}]
    r = h["dee"].post("/settlements", {"transfers": transfers}, idem=idem or key())
    assert r.status == 201, r
    return r.json


def respell(ts, hours=2):
    """The same instant in another UTC offset."""
    d = at(ts).astimezone(dt.timezone(dt.timedelta(hours=hours)))
    return d.isoformat()


def unchanged(h, before, pids):
    assert balances(h) == before
    for pid in pids:
        assert len(revisions(h["ada"], pid)) == 1, pid


# ---------------------------------------------------------------- auth and shape of the request

def test_batch_auth(api, h):
    # ledger: 3021, D-23
    body = {"corrections": [item("p_a", 400, T1)]}
    assert is_error(api.req("POST", "/correction-batches", body=body, headers={"Idempotency-Key": key()}),
                    401, "unauthenticated")
    assert is_error(h["ada"].post("/correction-batches", body, idem=key()), 403, "forbidden")
    assert is_error(h["ada"].post("/correction-batches", raw="{bad", idem=key()), 403, "forbidden")  # 403 first
    assert is_error(h["dee"].post("/correction-batches", raw="{bad", idem=key()), 400, "malformed_request")
    assert is_error(h["dee"].post("/correction-batches", body), 400, "missing_idempotency_key")
    assert is_error(h["dee"].post("/correction-batches", body, idem=""), 400, "missing_idempotency_key")
    assert bal(h["ada"]) == 10000 and len(revisions(h["ada"], "p_a")) == 1


@pytest.mark.parametrize("corrections", [
    "MISSING", None, {}, "x", [], ["p_a"], [None], [[]],
    [item("p_a", 400, T1), item("p_a", 300, T1)],
])
def test_batch_list_validation(api, h, corrections):
    # ledger: 3023, D-23
    body = {} if corrections == "MISSING" else {"corrections": corrections}
    assert is_error(h["dee"].post("/correction-batches", body, idem=key()), 422, "validation_failed")
    assert bal(h["ada"]) == 10000


def test_batch_size_limit_before_unknown(api, h):
    # ledger: 3023, 3025, D-23 (list validation precedes per-item 404)
    many = [item(f"nope_{i}", 1, T1) for i in range(33)]
    assert is_error(batch(h["dee"], many), 422, "validation_failed")
    assert is_error(batch(h["dee"], many[:32]), 404, "not_found")


BAD_ITEMS = [
    {"expected_revision": 1, "amount": 400, "effective_at": T1, "reason": "x"},          # no payment_id
    {"payment_id": "p_a", "amount": 400, "effective_at": T1, "reason": "x"},
    {"payment_id": "p_a", "expected_revision": 1, "effective_at": T1, "reason": "x"},
    {"payment_id": "p_a", "expected_revision": 1, "amount": 400, "reason": "x"},
    {"payment_id": "p_a", "expected_revision": 1, "amount": 400, "effective_at": T1},
    {"payment_id": "p_a", "expected_revision": 0, "amount": 400, "effective_at": T1, "reason": "x"},
    {"payment_id": "p_a", "expected_revision": 1, "amount": -1, "effective_at": T1, "reason": "x"},
    {"payment_id": "p_a", "expected_revision": 1, "amount": 1000000001, "effective_at": T1, "reason": "x"},
    {"payment_id": "p_a", "expected_revision": 1, "amount": 4.5, "effective_at": T1, "reason": "x"},
    {"payment_id": "p_a", "expected_revision": 1, "amount": 400, "effective_at": T1, "reason": ""},
    {"payment_id": "p_a", "expected_revision": 1, "amount": 400, "effective_at": T1, "reason": "r" * 201},
    {"payment_id": "p_a", "expected_revision": 1, "amount": 400, "effective_at": "2026-01-01T10:00:00",
     "reason": "x"},
    {"payment_id": "p_a", "expected_revision": 1, "amount": 400, "effective_at": "FUTURE", "reason": "x"},
]


@pytest.mark.parametrize("bad", BAD_ITEMS)
def test_batch_item_validation(api, h, bad):
    # ledger: 3024, 3037
    if bad.get("effective_at") == "FUTURE":
        bad = dict(bad, effective_at=now_iso(3600))
    before = balances(h)
    r = batch(h["dee"], [item("p_c", 0, T2), bad])
    assert is_error(r, 422, "validation_failed"), r
    unchanged(h, before, ["p_a", "p_c"])


def test_batch_unknown_fields_ignored(api, h):
    # ledger: 3030
    r = batch(h["dee"], [item("p_a", 400, T1, colour="blue")], extra={"x": 1})
    assert r.status == 201, r


# ---------------------------------------------------------------- success

def test_batch_success_shape(api, h):
    # ledger: 3002, 3035, 3036, 3026, 3038
    prev = max(at(revisions(h["ada"], p)[-1]["recorded_at"]) for p in ("p_c", "p_a"))
    k = key()
    r = batch(h["dee"], [item("p_c", 0, T2, reason="reversal"), item("p_a", 400, T1, reason="overpaid")], idem=k)
    assert r.status == 201, r
    b = r.json
    assert isinstance(b["correction_batch_id"], str) and b["correction_batch_id"]
    assert at(b["recorded_at"]) > prev
    assert [x["payment_id"] for x in b["revisions"]] == ["p_c", "p_a"]  # input order
    for x, (amt, rsn) in zip(b["revisions"], [(0, "reversal"), (400, "overpaid")]):
        assert x["revision"] == 2 and x["amount"] == amt and x["reason"] == rsn
        assert x["recorded_at"] == b["recorded_at"] or at(x["recorded_at"]) == at(b["recorded_at"])
        assert x["correction_batch_id"] == b["correction_batch_id"]
    assert at(b["revisions"][0]["effective_at"]) == at(T2) and at(b["revisions"][1]["effective_at"]) == at(T1)
    assert balances(h) == {"ada": 10800, "bob": 1900, "cy": 300, "dee": 700}
    assert sum(balances(h).values()) == TOTAL
    rv = revisions(h["bob"], "p_a")
    assert [x["revision"] for x in rv] == [1, 2] and rv[1]["correction_batch_id"] == b["correction_batch_id"]
    # replay and key reuse (3041)
    again = batch(h["dee"], [item("p_c", 0, T2, reason="reversal"), item("p_a", 400, T1, reason="overpaid")], idem=k)
    assert again.status == 200 and again.json == b
    assert is_error(batch(h["dee"], [item("p_a", 300, T1, rev=2)], idem=k), 409, "idempotency_key_reuse")
    assert balances(h)["ada"] == 10800
    # feed keeps original amounts
    feed = {p["payment_id"]: p for p in h["ada"].get("/activity", {"limit": 200}).json["payments"]}
    assert feed["p_a"]["amount"] == 1000 and feed["p_c"]["amount"] == 200


def test_batch_recorded_after_every_member(api, h):
    # ledger: 3036, D-18
    for amt, rev in ((900, 1), (800, 2), (700, 3)):
        assert h["ada"].post("/payments/p_a/corrections",
                             {"expected_revision": rev, "amount": amt, "effective_at": T1, "reason": "x"},
                             idem=key()).status == 201
    last = at(revisions(h["ada"], "p_a")[-1]["recorded_at"])
    b = batch(h["dee"], [item("p_a", 600, T1, rev=4), item("p_c", 100, T2)]).json
    assert at(b["recorded_at"]) > last
    assert len({x["recorded_at"] for x in b["revisions"]}) == 1


# ---------------------------------------------------------------- settlements

def test_settlement_batch_complete_and_same_instant(api, h):
    # ledger: 3002, 3026, 3027, 3028, 3039
    sk = key()
    transfers = [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
                 {"from_handle": "bob", "to_handle": "cy", "amount": 50}]
    s = settle(h, transfers, idem=sk)
    m1, m2 = (p["payment_id"] for p in s["payments"])
    c = s["committed_at"]
    before = balances(h)
    assert is_error(batch(h["dee"], [item(m1, 0, c)]), 422, "incomplete_settlement")
    assert is_error(batch(h["dee"], [item(m1, 0, c), item(m2, 0, T3)]), 422, "validation_failed")
    assert balances(h) == before
    r = batch(h["dee"], [item(m1, 0, c), item(m2, 0, respell(c))])  # offset spellings may differ
    assert r.status == 201, r
    assert balances(h) == {"ada": before["ada"] + 100, "bob": before["bob"] - 50, "cy": before["cy"] - 50,
                           "dee": before["dee"]}
    again = h["dee"].post("/settlements", {"transfers": transfers}, idem=sk)
    assert again.status == 200 and again.json == s
    # single corrections of members stay immutable; nonmembers stay correctable
    assert is_error(h["ada"].post(f"/payments/{m1}/corrections",
                                  {"expected_revision": 2, "amount": 5, "effective_at": c, "reason": "x"},
                                  idem=key()), 422, "linked_payment_immutable")
    assert h["ada"].post("/payments/p_a/corrections",
                         {"expected_revision": 1, "amount": 900, "effective_at": T1, "reason": "x"},
                         idem=key()).status == 201  # ledger: 3029


def test_settlement_members_can_move_together(api, h):
    # ledger: 3028 (one shared instant, not necessarily committed_at)
    s = settle(h)
    m1, m2 = (p["payment_id"] for p in s["payments"])
    r = batch(h["dee"], [item(m2, 50, T3), item(m1, 100, T3)])
    assert r.status == 201, r
    assert [x["payment_id"] for x in r.json["revisions"]] == [m2, m1]


def test_two_settlements_each_complete(api, h):
    # ledger: 3027
    s1, s2 = settle(h), settle(h)
    a1, b1 = (p["payment_id"] for p in s1["payments"])
    a2, b2 = (p["payment_id"] for p in s2["payments"])
    c1, c2 = s1["committed_at"], s2["committed_at"]
    assert is_error(batch(h["dee"], [item(a1, 0, c1), item(b1, 0, c1), item(a2, 0, c2)]),
                    422, "incomplete_settlement")
    assert batch(h["dee"], [item(a1, 0, c1), item(b1, 0, c1), item(a2, 0, c2), item(b2, 0, c2)]).status == 201


def test_refund_not_a_settlement_member(api, h):
    # ledger: 3043, 3026
    s = settle(h)
    m1, m2 = (p["payment_id"] for p in s["payments"])
    rf = h["bob"].post(f"/payments/{m1}/refunds", {"amount": 30}, idem=key())
    assert rf.status == 201, rf
    rid = rf.json["payment_id"]
    c = s["committed_at"]
    assert is_error(batch(h["dee"], [item(m1, 50, c), item(m2, 50, c), item(rid, 0, rf.json["created_at"])]),
                    422, "linked_payment_immutable")
    assert is_error(batch(h["dee"], [item(m1, 29, c), item(m2, 50, c)]), 422, "refund_exceeds_payment")
    assert batch(h["dee"], [item(m1, 30, c), item(m2, 50, c)]).status == 201


# ---------------------------------------------------------------- immutables and precedence

def test_capture_immutable_in_batch(api, h):
    # ledger: 3026, 3032
    a = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 300}, idem=key()).json
    cap = h["bob"].post(f"/authorizations/{a['authorization_id']}/capture", {}, idem=key()).json
    r = batch(h["dee"], [item("p_a", 400, T1), item(cap["payment_id"], 100, cap["created_at"])])
    assert is_error(r, 422, "linked_payment_immutable"), r
    assert bal(h["ada"]) == 9700 and len(revisions(h["ada"], "p_a")) == 1


def test_item_errors_in_input_order(api, h):
    # ledger: 3025, 3031, D-23
    assert is_error(batch(h["dee"], [item("nope", 1, T1), item("p_a", 1, T1, rev=5)]), 404, "not_found")
    assert is_error(batch(h["dee"], [item("p_a", 1, T1, rev=5), item("nope", 1, T1)]), 409, "stale_revision")
    assert is_error(batch(h["dee"], [item("nope", 1, T1), item("p_a", -1, T1)]), 404, "not_found")
    assert is_error(batch(h["dee"], [item("p_a", -1, T1), item("nope", 1, T1)]), 422, "validation_failed")
    rf = h["bob"].post("/payments/p_a/refunds", {"amount": 500}, idem=key()).json
    assert is_error(batch(h["dee"], [item(rf["payment_id"], 0, rf["created_at"]), item("p_c", 1, T2, rev=9)]),
                    422, "linked_payment_immutable")
    assert is_error(batch(h["dee"], [item("p_a", 600, T1), item(rf["payment_id"], 0, rf["created_at"])]),
                    422, "linked_payment_immutable")
    assert is_error(batch(h["dee"], [item("p_a", 499, T1), item("p_c", 1, T2, rev=9)]),
                    422, "refund_exceeds_payment")


def test_item_errors_before_completeness(api, h):
    # ledger: 3031, D-23
    s = settle(h)
    m1 = s["payments"][0]["payment_id"]
    assert is_error(batch(h["dee"], [item(m1, 0, s["committed_at"]), item("nope", 1, T1)]), 404, "not_found")


def test_completeness_before_funds(api, h):
    # ledger: 3031, D-23
    s = settle(h)
    m1 = s["payments"][0]["payment_id"]
    r = batch(h["dee"], [item("p_d", 5000, T3), item(m1, 0, s["committed_at"])])  # cy cannot afford p_d
    assert is_error(r, 422, "incomplete_settlement"), r


def test_combined_affordability(api, h):
    # ledger: 3033, 3032, 3034
    before = balances(h)
    k = key()
    r = batch(h["dee"], [item("p_d", 700, T3)], idem=k)  # cy (500) would pay 600 more
    assert is_error(r, 409, "insufficient_funds"), r
    unchanged(h, before, ["p_d"])
    # with p_b raised by 100 in the same batch, cy nets -500: affordable (and the key was never claimed)
    r = batch(h["dee"], [item("p_d", 700, T3), item("p_b", 400, T2)], idem=k)
    assert r.status == 201, r
    assert balances(h) == {"ada": 10600, "bob": 2400, "cy": 0, "dee": 700}


def test_batch_funds_use_available(api, h):
    # ledger: 3020, 3033
    assert h["cy"].post("/authorizations", {"to_handle": "ada", "amount": 450}, idem=key()).status == 201
    assert is_error(batch(h["dee"], [item("p_d", 151, T3)]), 409, "insufficient_funds")  # available 50
    assert batch(h["dee"], [item("p_d", 150, T3)]).status == 201


def overdraft_fixture():
    return {
        "currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_op"],
        "users": [user("u_x", "x", 100), user("u_y", "y", 5000), user("u_z", "z", 0), user("u_op", "op", 0)],
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


def test_batch_historical_overdraft(api):
    # ledger: 3031, 3032, 3033, 3034
    api.reset(overdraft_fixture())
    op, x = api.session("op@example.com"), api.session("x@example.com")
    k = key()
    r = batch(op, [item("q_1", 50, T1)], idem=k)  # x has 100 now but would be -50 after q_2
    assert r.status == 409 and r.code == "historical_overdraft", r
    assert bal(x) == 100 and len(revisions(x, "q_1")) == 1
    # combined: halving q_2 and q_3 too keeps x and z non-negative at every boundary; z (0 now) only
    # affords its q_2 debit because q_3 credits it back in the same batch
    r = batch(op, [item("q_1", 50, T1), item("q_2", 50, T2), item("q_3", 50, T3)], idem=k)
    assert r.status == 201, r
    assert bal(x) == 50 and bal(api.session("z@example.com")) == 0


def test_funds_before_historical(api):
    # ledger: 3031, D-23
    fx = overdraft_fixture()
    fx["users"][0]["balance"] = 0
    fx["users"][2]["balance"] = 100
    fx["payments"] = fx["payments"][:2]  # x: +100 at T1, -100 at T2; holds 0 now
    api.reset(fx)
    op = api.session("op@example.com")
    r = batch(op, [item("q_1", 0, T1)])  # debits x 100 now (insufficient) and overdraws at T2
    assert r.status == 409 and r.code == "insufficient_funds", r


# ---------------------------------------------------------------- snapshots and concurrency

def test_snapshot_frozen_new_statement_reflects(api, h):
    # ledger: 3040, 3003
    first = h["ada"].get("/statement").json
    assert batch(h["dee"], [item("p_a", 400, T1)]).status == 201
    old = h["ada"].get("/statement", params={"snapshot": first["snapshot"]}).json
    assert old["entries"] == first["entries"] and old["closing_balance"] == 10000
    new = h["ada"].get("/statement").json
    e = [x for x in new["entries"] if x["payment"]["payment_id"] == "p_a"][0]
    assert e["delta"] == -400 and e["revision"] == 2 and new["closing_balance"] == 10600


def test_concurrent_batch_and_single_share_revision(api):
    # ledger: 3044, D-25
    for _ in range(3):
        fx = history_fixture()
        api.reset(fx)
        ada, dee = api.session("ada@example.com"), api.session("dee@example.com")
        singles = [lambda a=a: ada.post("/payments/p_a/corrections",
                                        {"expected_revision": 1, "amount": a, "effective_at": T1, "reason": "s"},
                                        idem=key()) for a in range(500, 510)]
        batches = [lambda a=a: batch(dee, [item("p_c", 150, T2), item("p_a", a, T1)]) for a in range(600, 610)]
        res = parallel(singles + batches)
        assert all(r.status < 500 for r in res), [r for r in res if r.status >= 500]
        assert sum(r.status == 201 for r in res) == 1, [r.status for r in res]
        assert all(r.status == 201 or is_error(r, 409, "stale_revision") for r in res)
        assert len(revisions(ada, "p_a")) == 2
        assert sum(api.session(f"{u}@example.com").balance() for u in ("ada", "bob", "cy", "dee")) == TOTAL
