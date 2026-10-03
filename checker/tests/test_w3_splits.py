"""W-3: POST /splits and the §9 equal-split rule."""

from __future__ import annotations

import random

import pytest

from pf import RFC3339, base_fixture, is_error, key, parallel, total

pytestmark = pytest.mark.item("W-3")

SEED_TOTAL = 10000 + 2500 + 0 + 700


def expected_shares(amount: int, n: int) -> list[int]:
    q, r = divmod(amount, n)
    return [q + 1 if i < r else q for i in range(n)]


def split(s, amount, handles, idem=None, **kw):
    return s.post("/splits", {"amount": amount, "participant_handles": handles, **kw}, idem=idem or key())


@pytest.mark.parametrize("amount,shares", [(1000, [334, 333, 333]), (1, [1, 0, 0]), (10, [4, 3, 3]),
                                           (999, [333, 333, 333])])
def test_table_cases_three(api, seeded, amount, shares):
    # ledger: 223, 224, 225, 226, 221, 222
    r = split(seeded["ada"], amount, ["ada", "bob", "cy"])
    assert r.status == 201, r
    assert [x["amount"] for x in r.json["shares"]] == shares
    assert [x["handle"] for x in r.json["shares"]] == ["ada", "bob", "cy"]


def test_table_five_by_five(api):
    # ledger: 227
    fx = base_fixture()
    fx["users"].append({"id": "u_eve", "email": "eve@example.com", "password": "correct horse",
                        "display_name": "Eve", "handle": "eve", "balance": 0})
    api.reset(fx)
    ada = api.session("ada@example.com")
    r = split(ada, 5, ["ada", "bob", "cy", "dee", "eve"])
    assert r.status == 201 and [x["amount"] for x in r.json["shares"]] == [1, 1, 1, 1, 1], r
    assert len(r.json["requests"]) == 4


def test_split_shape_and_requests(api, seeded):
    # ledger: 205, 207, 208, 209, 210
    ada = seeded["ada"]
    r = split(ada, 3000, ["bob", "ada", "cy"], note="dinner")
    assert r.status == 201, r
    s = r.json
    assert {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"} <= set(s)
    assert s["amount"] == 3000 and s["currency"] == "EUR" and s["note"] == "dinner"
    assert RFC3339.match(s["created_at"]) and isinstance(s["split_id"], str) and len(s["split_id"]) <= 64
    assert s["shares"] == [{"handle": "bob", "amount": 1000}, {"handle": "ada", "amount": 1000},
                           {"handle": "cy", "amount": 1000}]
    assert [q["payer_handle"] for q in s["requests"]] == ["bob", "cy"]
    for q in s["requests"]:
        assert q["requester_id"] == "u_ada" and q["requester_handle"] == "ada"
        assert q["status"] == "pending" and q["amount"] == 1000 and q["payment_id"] is None
        assert q["note"] == "dinner"
    # the requests are real and visible to their two parties only
    bob_in = {q["request_id"] for q in seeded["bob"].get("/requests", {"direction": "incoming"}).json["requests"]}
    assert s["requests"][0]["request_id"] in bob_in
    dee_all = {q["request_id"] for q in seeded["dee"].get("/requests").json["requests"]}
    assert not dee_all & {q["request_id"] for q in s["requests"]}  # ledger: 77


def test_caller_omitted(api, seeded):
    # ledger: 206, 208
    r = split(seeded["ada"], 1000, ["bob", "cy", "dee"])
    assert r.status == 201
    assert [x["amount"] for x in r.json["shares"]] == [334, 333, 333]
    assert [(q["payer_handle"], q["amount"]) for q in r.json["requests"]] == [("bob", 334), ("cy", 333), ("dee", 333)]


def test_order_moves_extra_unit(api, seeded):
    # ledger: 228, 230
    a = split(seeded["ada"], 10, ["ada", "bob", "cy"]).json["shares"]
    b = split(seeded["ada"], 10, ["cy", "bob", "ada"]).json["shares"]
    assert {x["handle"]: x["amount"] for x in a} == {"ada": 4, "bob": 3, "cy": 3}
    assert {x["handle"]: x["amount"] for x in b} == {"cy": 4, "bob": 3, "ada": 3}


def test_zero_share_creates_request(api, seeded):
    # ledger: 229
    r = split(seeded["ada"], 1, ["ada", "bob", "cy"])
    assert [(q["payer_handle"], q["amount"]) for q in r.json["requests"]] == [("bob", 0), ("cy", 0)]


def test_only_caller(api, seeded):
    # ledger: 215
    r = split(seeded["ada"], 777, ["ada"])
    assert r.status == 201 and r.json["requests"] == [] and r.json["shares"] == [{"handle": "ada", "amount": 777}], r


def test_no_balance_check(api, seeded):
    # ledger: 216
    r = split(seeded["cy"], 1_000_000_000, ["ada", "bob", "cy", "dee"])
    assert r.status == 201, r
    assert seeded["cy"].balance() == 0


@pytest.mark.parametrize("body,status,code", [
    ({"amount": 0, "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": 1000000001, "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": 10.5, "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": "10", "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": 10, "participant_handles": []}, 422, "validation_failed"),
    ({"amount": 10, "participant_handles": ["bob", "cy", "bob"]}, 422, "validation_failed"),
    ({"amount": 10, "participant_handles": ["bob"], "note": "x" * 201}, 422, "validation_failed"),
    ({"amount": 10, "participant_handles": ["bob"], "note": None}, 422, "validation_failed"),
    ({"amount": 10, "participant_handles": ["bob", "ghost"]}, 404, "not_found"),
    ({"amount": 10}, 422, "validation_failed"),
    ({"amount": 10, "participant_handles": "bob"}, 400, "malformed_request"),
])
def test_split_errors(api, seeded, body, status, code):
    # ledger: 211, 212, 213, 214
    r = seeded["ada"].post("/splits", body, idem=key())
    assert is_error(r, status, code), r
    assert seeded["bob"].get("/requests").json["requests"][0]["request_id"] == "rq_1"


def test_split_idempotent(api, seeded):
    # ledger: 131, 139, 140, 145
    k = key()
    a = split(seeded["ada"], 900, ["bob", "cy"], idem=k)
    b = split(seeded["ada"], 900, ["bob", "cy"], idem=k)
    assert a.status == 201 and b.status == 200 and a.json == b.json
    assert is_error(split(seeded["ada"], 900, ["cy", "bob"], idem=k), 409, "idempotency_key_reuse")
    assert len(seeded["bob"].get("/requests", {"direction": "incoming"}).json["requests"]) == 1
    assert is_error(seeded["ada"].post("/splits", {"amount": 5, "participant_handles": ["bob"]}), 400,
                    "missing_idempotency_key")


def test_split_not_in_feed(api, seeded):
    # ledger: 76
    before = seeded["cy"].get("/activity").json["payments"]
    split(seeded["ada"], 900, ["bob", "cy"])
    assert seeded["cy"].get("/activity").json["payments"] == before


def test_random_amounts_rule(api, seeded):
    # ledger: 221, 222, 207
    rnd = random.Random(7)
    pool = ["ada", "bob", "cy", "dee"]
    for _ in range(12):
        n = rnd.randint(1, 4)
        hs = rnd.sample(pool, n)
        amt = rnd.choice([1, 2, 3, 7, 99, 100, 1001, rnd.randint(1, 1_000_000_000)])
        r = split(seeded["ada"], amt, hs)
        assert r.status == 201, r
        got = [x["amount"] for x in r.json["shares"]]
        assert got == expected_shares(amt, n) and sum(got) == amt, (amt, hs, got)


def test_split_then_concurrent_pay_invariant(api):
    # ledger: 231, 9, 10, 11
    for _ in range(3):
        api.reset(base_fixture())
        s = {h: api.session(f"{h}@example.com") for h in ("ada", "bob", "cy", "dee")}
        sp = split(s["dee"], 2000, ["dee", "ada", "bob"]).json
        ids = {q["payer_handle"]: q["request_id"] for q in sp["requests"]}
        jobs = []
        for h, rid in ids.items():
            jobs += [lambda h=h, rid=rid: s[h].pay_request(rid)] * 8
        res = parallel(jobs)
        assert all(r.status < 500 for r in res)
        assert sum(r.status == 201 for r in res) == 2
        assert total(s) == SEED_TOTAL
        assert s["dee"].balance() == 700 + 667 + 666
