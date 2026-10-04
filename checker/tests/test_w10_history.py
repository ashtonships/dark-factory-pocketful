"""W-10: stage-3 read side - GET /me as_of/known_at, GET /statement, snapshots, historical holds."""

from __future__ import annotations

import time

import pytest

from pf import is_error, key, parallel
from s3 import OPENING, T1, T2, T3, TOTAL, at, history_fixture, now_iso, shift

pytestmark = pytest.mark.item("W-10")


@pytest.fixture
def h(api):
    fx = history_fixture()
    api.reset(fx)
    return api.sessions(fx)


def me(s, **q):
    r = s.get("/me", params=q)
    assert r.status == 200, r
    return r.json


def stmt(s, **q):
    r = s.get("/statement", params=q)
    assert r.status == 200, r
    return r.json


def correct(s, pid, amount, eff, rev=1):
    r = s.post(f"/payments/{pid}/corrections",
               {"expected_revision": rev, "amount": amount, "effective_at": eff, "reason": "fix"}, idem=key())
    assert r.status == 201, r
    return r.json


def ids(st):
    return [e["payment"]["payment_id"] for e in st["entries"]]


# ---------------------------------------------------------------- GET /me as_of

@pytest.mark.parametrize("as_of,ada", [
    (shift(T1, -1), 11100),            # before the earliest: opening
    (T1, 10100),                       # exactly at a payment: counts
    ("2026-01-01T12:00:00+02:00", 10100),  # same instant as T1 in another offset
    (shift(T1, 1), 10100),
    (T2, 9900),
    (shift(T3, -0.5), 9900),
    (T3, 10000),
    ("2030-01-01T00:00:00+00:00", 10000),  # after the latest, even in the future
])
def test_me_as_of(api, h, as_of, ada):
    # ledger: 2013, 2016, 2017, 2018, 2019, 2020, 2021, 2075, 2102
    m = me(h["ada"], as_of=as_of)
    assert m["balance"] == ada and m["total"] == ada, (as_of, m)
    assert m["available"] == m["total"] - m["held"]
    assert m["as_of"] == as_of


@pytest.mark.parametrize("bad", ["2026-01-01T10:00:00", "2026-01-01", "", "yesterday", "2026-13-01T00:00:00+00:00"])
def test_me_bad_instants(api, h, bad):
    # ledger: 2014, 2076
    assert is_error(h["ada"].get("/me", params={"as_of": bad}), 422, "validation_failed")
    assert is_error(h["ada"].get("/me", params={"known_at": bad}), 422, "validation_failed")


def test_me_without_params_unchanged(api, h):
    # ledger: 2015
    m = me(h["ada"])
    assert m["balance"] == m["total"] == m["available"] == 10000 and m["held"] == 0
    assert "as_of" not in m or m["as_of"] is None


def test_sum_invariant_in_historical_views(api, h):
    # ledger: 2064, 2042
    for t in [shift(T1, -1), T1, T2, T3, now_iso()]:
        assert sum(me(s, as_of=t)["balance"] for s in h.values()) == TOTAL, t
    assert {k: me(s, as_of=shift(T1, -1))["balance"] for k, s in h.items()} == OPENING


# ---------------------------------------------------------------- GET /statement

def test_statement_full_default_window(api, h):
    # ledger: 2022, 2024, 2027, 2028, 2030, 2031, 2032, 2079
    st = stmt(h["ada"])
    assert st["opening_balance"] == 11100 and st["closing_balance"] == 10000
    assert ids(st) == ["p_a", "p_c", "p_d"]
    assert [e["delta"] for e in st["entries"]] == [-1000, -200, 100]
    assert [e["balance_after"] for e in st["entries"]] == [10100, 9900, 10000]
    assert st["has_more"] is False and isinstance(st["snapshot"], str) and st["snapshot"]
    for e in st["entries"]:
        assert {"payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"} <= set(e)


def test_statement_ties_by_id(api, h):
    # ledger: 2027, 2078 (D-17)
    st = stmt(h["cy"])
    assert ids(st) == ["p_b", "p_c", "p_d"]
    assert [e["balance_after"] for e in st["entries"]] == [400, 600, 500]


def test_statement_half_open_window(api, h):
    # ledger: 2024, 2028, 2029, 2030, 2074
    st = stmt(h["ada"], **{"from": T2, "to": T3})
    assert ids(st) == ["p_c"] and st["opening_balance"] == 10100 and st["closing_balance"] == 9900
    st = stmt(h["ada"], **{"from": T1, "to": T1})
    assert ids(st) == [] and st["opening_balance"] == st["closing_balance"] == 11100
    st = stmt(h["ada"], **{"from": shift(T1, 1), "to": "2030-01-01T00:00:00+00:00"})
    assert ids(st) == ["p_c", "p_d"] and st["opening_balance"] == 10100 and st["closing_balance"] == 10000


def test_statement_only_own_payments(api, h):
    # ledger: 2036, 2037
    assert ids(stmt(h["bob"])) == ["p_a", "p_b"]
    assert ids(stmt(h["dee"])) == [] and stmt(h["dee"])["opening_balance"] == 700


def test_statement_pagination_keeps_full_window_values(api, h):
    # ledger: 2023, 2033, 2034, 2035, 2091
    full = stmt(h["ada"])
    pages = [stmt(h["ada"], limit=1, offset=i) for i in range(3)]
    for i, p in enumerate(pages):
        assert p["opening_balance"] == 11100 and p["closing_balance"] == 10000
        assert p["entries"][0]["balance_after"] == full["entries"][i]["balance_after"]
        assert p["has_more"] is (i < 2)
    beyond = stmt(h["ada"], limit=2, offset=10)
    assert beyond["entries"] == [] and beyond["has_more"] is False
    for q in [{"limit": "0"}, {"limit": "201"}, {"offset": "-1"}, {"limit": "+2"}]:
        assert is_error(h["ada"].get("/statement", params=q), 422, "validation_failed"), q
    for q in [{"from": "2026-01-01"}, {"to": ""}, {"known_at": "x"}]:
        assert is_error(h["ada"].get("/statement", params=q), 422, "validation_failed"), q


def test_statement_needs_auth(api, h):
    # ledger: 2024
    assert is_error(api.req("GET", "/statement"), 401, "unauthenticated")


# ---------------------------------------------------------------- corrections in history (known_at)

def test_known_at_selects_revisions(api, h):
    # ledger: 2070, 2071, 2072, 2073, 2077, 2080, 2082, 2083
    before = now_iso()
    time.sleep(0.05)
    c = correct(h["ada"], "p_a", 400, T1)  # effective T1, recorded now
    after = now_iso(1)
    assert me(h["ada"], as_of=T1)["balance"] == 10700          # latest known
    old = me(h["ada"], as_of=T1, known_at=before)
    assert old["balance"] == 10100 and old["known_at"] == before
    assert me(h["ada"], as_of=T1, known_at=after)["balance"] == 10700
    assert me(h["ada"], known_at=before)["balance"] == 10000
    assert me(h["ada"], known_at=shift(T1, -1))["balance"] == 11100  # nothing recorded yet
    st_old = stmt(h["ada"], known_at=before)
    assert [e["payment"]["amount"] for e in st_old["entries"]] == [1000, 200, 100]
    st_new = stmt(h["ada"])
    e = st_new["entries"][0]
    assert e["payment"]["payment_id"] == "p_a" and e["payment"]["amount"] == 400 and e["delta"] == -400
    assert e["revision"] == 2 and at(e["recorded_at"]) == at(c["recorded_at"])
    assert len([x for x in st_new["entries"] if x["payment"]["payment_id"] == "p_a"]) == 1
    assert st_new["opening_balance"] == 11100 and st_new["closing_balance"] == 10600


def test_zero_revision_still_listed(api, h):
    # ledger: 2081
    correct(h["ada"], "p_c", 0, T2)
    st = stmt(h["ada"])
    e = [x for x in st["entries"] if x["payment"]["payment_id"] == "p_c"][0]
    assert e["delta"] == 0 and e["payment"]["amount"] == 0


def test_correction_moves_payment_across_window(api, h):
    # ledger: 2093, 2078
    correct(h["cy"], "p_d", 100, shift(T1, 3600))  # effective time moves from T3 to T1+1h
    st = stmt(h["ada"], **{"from": T1, "to": T2})
    assert ids(st) == ["p_a", "p_d"] and st["closing_balance"] == 10200
    assert "p_d" not in ids(stmt(h["ada"], **{"from": T3}))
    assert ids(stmt(h["ada"]))[:2] == ["p_a", "p_d"]


def test_opening_balances_unchanged_by_corrections(api, h):
    # ledger: 2043
    correct(h["ada"], "p_a", 10, T1)
    assert stmt(h["ada"])["opening_balance"] == 11100 and stmt(h["bob"])["opening_balance"] == 1800


# ---------------------------------------------------------------- snapshots

def test_snapshot_freezes_result(api, h):
    # ledger: 2084, 2085, 2086, 2094, 2116
    first = stmt(h["ada"], limit=2)
    tok = first["snapshot"]
    h["ada"].pay("bob", 7)
    correct(h["ada"], "p_a", 400, T1)
    page2 = stmt(h["ada"], snapshot=tok, limit=2, offset=2)
    assert ids(page2) == ["p_d"] and page2["entries"][0]["balance_after"] == 10000
    assert page2["opening_balance"] == 11100 and page2["closing_balance"] == 10000 and page2["has_more"] is False
    page1 = stmt(h["ada"], snapshot=tok, limit=2, offset=0)
    assert page1["entries"] == first["entries"] and page1["has_more"] is True
    live = stmt(h["ada"])
    assert live["closing_balance"] == 10600 - 7


def test_snapshot_rules(api, h):
    # ledger: 2087, 2088, 2089, 2092
    tok = stmt(h["ada"])["snapshot"]
    for extra in ({"from": T1}, {"to": T3}, {"known_at": T3}):
        assert is_error(h["ada"].get("/statement", params={"snapshot": tok, **extra}), 422, "validation_failed")
    assert h["ada"].get("/statement", params={"snapshot": tok, "unknown": "1"}).status == 200
    assert is_error(h["ada"].get("/statement", params={"snapshot": "nope"}), 404, "not_found")
    assert is_error(h["bob"].get("/statement", params={"snapshot": tok}), 404, "not_found")
    api.reset(history_fixture())
    ada = api.session("ada@example.com")
    assert is_error(ada.get("/statement", params={"snapshot": tok}), 404, "not_found")


def test_snapshot_stable_under_concurrent_writes(api, h):
    # ledger: 2094, 2116
    first = stmt(h["ada"], limit=1)
    tok = first["snapshot"]
    writes = [lambda: h["ada"].pay("cy", 1)] * 10 + [lambda: h["bob"].pay("ada", 1)] * 10
    reads = [lambda i=i: stmt(h["ada"], snapshot=tok, limit=1, offset=i % 3) for i in range(20)]
    res = parallel(writes + reads)
    for i, r in enumerate(res[20:]):
        assert r["opening_balance"] == 11100 and r["closing_balance"] == 10000
        assert r["entries"][0]["balance_after"] == [10100, 9900, 10000][i % 3]


# ---------------------------------------------------------------- historical holds

def test_historical_holds(api, h):
    # ledger: 2102, 2103, 2104, 2105, 2106, 2107, 2108, 2110
    a = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 3000}, idem=key()).json
    created, expires = a["created_at"], a["expires_at"]
    m = me(h["ada"], as_of=shift(created, -1))
    assert (m["total"], m["held"], m["available"]) == (10000, 0, 10000)
    m = me(h["ada"], as_of=created)
    assert (m["total"], m["held"], m["available"]) == (10000, 3000, 7000)
    m = me(h["ada"], as_of=expires)  # expiry takes effect at expires_at (in the future)
    assert m["held"] == 0 and m["available"] == 10000
    m = me(h["ada"], as_of=shift(expires, -1))
    assert m["held"] == 3000
    cap = h["bob"].post(f"/authorizations/{a['authorization_id']}/capture", {"amount": 1000, "final": False},
                        idem=key()).json
    m = me(h["ada"], as_of=cap["created_at"])
    assert (m["total"], m["held"], m["available"]) == (9000, 2000, 7000)
    m = me(h["ada"], as_of=shift(cap["created_at"], -0.000001))
    assert m["held"] == 3000 and m["total"] == 10000
    v = h["ada"].post(f"/authorizations/{a['authorization_id']}/void").json
    m = me(h["ada"], as_of=v["closed_at"])
    assert m["held"] == 0 and m["total"] == 9000
    m = me(h["ada"], known_at=shift(created, -1))  # creation not yet known
    assert m["held"] == 0


def test_statement_money_movements_only(api, h):
    # ledger: 2114, 2115
    a = h["ada"].post("/authorizations", {"to_handle": "bob", "amount": 500}, idem=key()).json
    assert ids(stmt(h["ada"])) == ["p_a", "p_c", "p_d"]
    cap = h["bob"].post(f"/authorizations/{a['authorization_id']}/capture", {}, idem=key()).json
    st = stmt(h["ada"])
    caps = [e for e in st["entries"] if e["payment"]["payment_id"] == cap["payment_id"]]
    assert len(caps) == 1 and caps[0]["payment"]["authorization_id"] == a["authorization_id"]
    assert caps[0]["delta"] == -500 and st["closing_balance"] == 9500


def test_statement_window_order(api, h):
    # ledger: 2074, D-16, D-20
    assert is_error(h["ada"].get("/statement", params={"from": T3, "to": T2}), 422, "validation_failed")
    assert is_error(h["ada"].get("/statement", params={"from": shift(T2, 0.000001), "to": T2}),
                    422, "validation_failed")
    fut = now_iso(3600)
    st = stmt(h["ada"], **{"from": fut})  # to omitted, from in the future: valid, empty (D-20 amended)
    assert st["entries"] == [] and st["has_more"] is False
    assert st["opening_balance"] == st["closing_balance"] == 10000
    st = stmt(h["ada"], **{"from": fut, "to": now_iso(7200)})
    assert st["entries"] == [] and st["opening_balance"] == st["closing_balance"] == 10000
    st = stmt(h["ada"], to=shift(T1, -1))  # from omitted: the window starts at the earliest
    assert st["entries"] == [] and st["opening_balance"] == st["closing_balance"] == 11100
