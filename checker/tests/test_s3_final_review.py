"""Stage-3 final review: requirements that no earlier check would have caught if broken."""

from __future__ import annotations

import time

import pytest

from pf import is_error, key
from s3 import T1, T2, T3, TOTAL, at, history_fixture, now_iso, shift

w9 = pytest.mark.item("W-9")
w10 = pytest.mark.item("W-10")


@pytest.fixture
def h(api):
    fx = history_fixture()
    api.reset(fx)
    return api.sessions(fx)


def me(s, **q):
    r = s.get("/me", params=q)
    assert r.status == 200, r
    return r.json


def correct(s, pid, amount, eff, rev=1, idem=None):
    return s.post(f"/payments/{pid}/corrections",
                  {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": "fix"},
                  idem=idem or key())


@w9
def test_created_at_on_every_payment_surface(api, h):
    # ledger: 2006, 2007
    for p in h["ada"].get("/activity", {"limit": 200}).json["payments"]:
        assert at(p["created_at"]), p
    for e in h["ada"].get("/statement").json["entries"]:
        assert at(e["payment"]["created_at"]), e
    a = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 50}, idem=key()).json
    cap = h["bob"].post(f"/authorizations/{a['authorization_id']}/capture", {}, idem=key()).json
    assert at(cap["created_at"])


@w9
def test_insufficient_funds_preserves_everything(api, h):
    # ledger: 2060, 2063
    before = h["cy"].get("/statement").json
    k = key()
    assert is_error(correct(h["cy"], "p_d", 700, T3, idem=k), 409, "insufficient_funds")
    after = h["cy"].get("/statement").json
    assert after["entries"] == before["entries"] and after["closing_balance"] == before["closing_balance"]
    assert len(h["cy"].get("/payments/p_d/revisions").json["revisions"]) == 1
    # the key claimed nothing: a different body under it is a first use
    r = correct(h["cy"], "p_d", 50, T3, idem=k)
    assert r.status == 201, r


@w9
def test_sum_invariant_after_corrections_in_every_view(api, h):
    # ledger: 2064
    before = now_iso()
    time.sleep(0.05)
    assert correct(h["ada"], "p_a", 400, T1).status == 201
    assert correct(h["cy"], "p_d", 0, shift(T2, 60)).status == 201
    for as_of in [shift(T1, -1), T1, T2, shift(T2, 60), T3, now_iso()]:
        for known in [None, before, now_iso(1)]:
            q = {"as_of": as_of} if known is None else {"as_of": as_of, "known_at": known}
            assert sum(me(s, **q)["balance"] for s in h.values()) == TOTAL, q


@w10
def test_hold_events_known_at_their_time(api, h):
    # ledger: 2104, 2105, 2106
    a = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 3000}, idem=key()).json
    created, expires = a["created_at"], a["expires_at"]
    time.sleep(0.05)
    v = h["ada"].post(f"/authorizations/{a['authorization_id']}/void").json
    closed = v["closed_at"]
    assert at(closed) > at(created)
    # the void is not yet known just before it was recorded: the hold still stands at the void's instant
    m = me(h["ada"], as_of=closed, known_at=shift(closed, -0.000001))
    assert m["held"] == 3000 and m["available"] == 7000
    assert me(h["ada"], as_of=closed, known_at=closed)["held"] == 0
    # expiry is known together with creation: past the deadline the hold is gone even with nothing later known
    assert me(h["ada"], as_of=expires, known_at=created)["held"] == 0
    assert me(h["ada"], as_of=shift(expires, -1), known_at=created)["held"] == 3000


@w10
def test_seeded_open_hold_creation_time(api):
    # ledger: 2113, 2103
    fx = history_fixture()
    exp = now_iso(7200)
    fx["authorizations"] = [
        {"id": "a_t", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "",
         "visibility": "public", "status": "open", "expires_at": exp, "created_at": T2},
        {"id": "a_r", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 500, "note": "",
         "visibility": "public", "status": "open", "expires_at": exp},
    ]
    reset_before = now_iso(-1)
    api.reset(fx)
    ada, bob = api.session("ada@example.com"), api.session("bob@example.com")
    assert me(ada, as_of=shift(T2, -1))["held"] == 0
    assert me(ada, as_of=T2)["held"] == 2000 and me(ada, as_of=T2)["available"] == 9900 - 2000
    assert me(bob, as_of=reset_before)["held"] == 0           # assumed created at reset
    assert me(bob)["held"] == 500


@w10
def test_snapshot_unchanged_after_lifecycle_actions(api, h):
    # ledger: 2116
    first = h["ada"].get("/statement").json
    tok = first["snapshot"]
    a = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 600}, idem=key()).json
    h["bob"].post(f"/authorizations/{a['authorization_id']}/capture", {"amount": 100, "final": False}, idem=key())
    h["ada"].post(f"/authorizations/{a['authorization_id']}/void")
    old = h["ada"].get("/statement", params={"snapshot": tok}).json
    assert old["entries"] == first["entries"] and old["closing_balance"] == first["closing_balance"] == 10000
    assert h["ada"].get("/statement").json["closing_balance"] == 9900
