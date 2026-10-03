"""W-4: export/import (§10) and atomic net settlements (§11)."""

from __future__ import annotations

import json

import pytest

from pf import PASSWORD, RFC3339, base_fixture, is_error, key, parallel, total

pytestmark = pytest.mark.item("W-4")

SEED_TOTAL = 10000 + 2500 + 0 + 700


def op_fixture(**over):
    fx = base_fixture(settlement_operator_ids=["u_dee"])
    fx.update(over)
    return fx


@pytest.fixture
def ops(api):
    fx = op_fixture()
    api.reset(fx)
    return api.sessions(fx)


def settle(s, transfers, idem=None, **extra):
    return s.post("/settlements", {"transfers": transfers, **extra}, idem=idem or key())


def export(api):
    r = api.req("GET", "/_test/export")
    assert r.status == 200, r
    return r.json


def imp(api, obj):
    return api.req("POST", "/_test/import", body=obj)


# ---------------------------------------------------------------- export / import

def test_export_shape_and_no_plaintext(api, ops):
    # ledger: 232, 233, 235, 130, 234
    e = export(api)
    assert e["track"] == "pocketful" and e["format_version"] == 1 and isinstance(e["state"], dict)
    assert PASSWORD not in json.dumps(e)


def test_roundtrip_preserves_everything(api, ops):
    # ledger: 236, 237, 238, 241, 245, 246, 248, 273
    ada, bob, dee = ops["ada"], ops["bob"], ops["dee"]
    k_pay, k_req, k_set = key(), key(), key()
    p = ada.pay("bob", 321, idem=k_pay, note="pre", visibility="private")
    q = bob.request("ada", 50, idem=k_req)
    st = settle(dee, [{"from_handle": "ada", "to_handle": "cy", "amount": 10}], idem=k_set)
    k_fail = key()
    assert is_error(seeded_fail := ops["cy"].pay("bob", 999999, idem=k_fail), 409, "insufficient_funds"), seeded_fail
    assert p.status == q.status == st.status == 201
    bal = {h: s.balance() for h, s in ops.items()}
    feeds = {h: s.get("/activity", {"limit": 200}).json for h, s in ops.items()}
    rq = {h: s.get("/requests", {"limit": 200}).json for h, s in ops.items()}
    snap = export(api)

    # wipe the destination completely, then import the unchanged object
    api.reset(base_fixture(users=[{"id": "u_z", "email": "z@example.com", "password": PASSWORD,
                                   "display_name": "Z", "handle": "zz", "balance": 5}],
                           payments=[], requests=[]))
    assert imp(api, snap).status == 204
    assert imp(api, snap).status == 204  # repeat: replacement, not merge
    assert api.login("z@example.com").status == 401  # ledger: 249
    # old tokens still valid, balances identical, records identical (ids, timestamps)
    for h, s in ops.items():
        assert s.balance() == bal[h], h
        assert s.get("/activity", {"limit": 200}).json == feeds[h], h
        assert s.get("/requests", {"limit": 200}).json == rq[h], h
    assert api.login("ada@example.com").status == 200  # hashed-password login survives
    # completed idempotent responses replay byte-identical; no money moves
    r = ada.pay("bob", 321, idem=k_pay, note="pre", visibility="private")
    assert r.status == 200 and r.json == p.json, r
    assert is_error(ada.pay("bob", 322, idem=k_pay), 409, "idempotency_key_reuse")
    r = bob.request("ada", 50, idem=k_req)
    assert r.status == 200 and r.json == q.json
    r = settle(dee, [{"from_handle": "ada", "to_handle": "cy", "amount": 10}], idem=k_set)
    assert r.status == 200 and r.json == st.json  # ledger: 271, 273
    # failed key remains reusable (ledger: 247)
    assert ops["cy"].pay("bob", 1, idem=k_fail).status == 201
    assert total(ops) == SEED_TOTAL
    # operator permission survived
    assert settle(dee, [{"from_handle": "bob", "to_handle": "cy", "amount": 1}]).status == 201


def test_export_is_snapshot(api, ops):
    # ledger: 244
    snap = export(api)
    frozen = json.dumps(snap, sort_keys=True)
    ops["ada"].pay("bob", 100)
    api.signup("later@example.com")
    assert json.dumps(snap, sort_keys=True) == frozen
    assert imp(api, snap).status == 204
    assert ops["ada"].balance() == 10000
    assert api.login("later@example.com").status == 401


@pytest.mark.parametrize("mutate", [
    lambda e: e.__setitem__("track", "other"),
    lambda e: e.__setitem__("format_version", 2),
    lambda e: e.pop("state"),
    lambda e: e.pop("track"),
    lambda e: e.pop("format_version"),
    lambda e: e.__setitem__("state", "nope"),
    lambda e: e.__setitem__("state", {}),
])
def test_invalid_import_422_no_change(api, ops, mutate):
    # ledger: 242
    e = export(api)
    ops["ada"].pay("bob", 100)
    mutate(e)
    r = imp(api, e)
    assert is_error(r, 422, "validation_failed"), r
    assert ops["ada"].balance() == 9900


def test_import_unparseable_400(api, ops):
    # ledger: 242, 95
    assert is_error(api.req("POST", "/_test/import", raw="{x"), 400, "malformed_request")
    assert ops["ada"].balance() == 10000


def test_reset_clears_imported_state(api, ops):
    # ledger: 250
    snap = export(api)
    tok = ops["ada"]
    api.reset(base_fixture(users=[{"id": "u_q", "email": "q@example.com", "password": PASSWORD,
                                   "display_name": "Q", "handle": "q", "balance": 1}], payments=[], requests=[]))
    assert imp(api, snap).status == 204
    api.reset(base_fixture(users=[{"id": "u_q", "email": "q@example.com", "password": PASSWORD,
                                   "display_name": "Q", "handle": "q", "balance": 1}], payments=[], requests=[]))
    assert is_error(tok.me(), 401, "unauthenticated")
    assert api.login("ada@example.com").status == 401


def test_export_import_unauthenticated_and_quick(api, ops):
    # ledger: 233, 243
    import time
    t = time.monotonic()
    snap = export(api)
    assert imp(api, snap).status == 204
    assert time.monotonic() - t < 10


# ---------------------------------------------------------------- settlements

def test_settlement_auth(api, ops):
    # ledger: 255, 256, 253
    body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]}
    assert is_error(api.req("POST", "/settlements", body=body, headers={"Idempotency-Key": key()}),
                    401, "unauthenticated")
    assert is_error(ops["ada"].post("/settlements", body, idem=key()), 403, "forbidden")
    assert is_error(ops["dee"].post("/settlements", body), 400, "missing_idempotency_key")


def test_settlement_201_shape(api, ops):
    # ledger: 253, 259, 266, 267, 268, 270
    dee = ops["dee"]
    r = settle(dee, [{"from_handle": "ada", "to_handle": "bob", "amount": 100, "note": "n1", "visibility": "private"},
                     {"from_handle": "bob", "to_handle": "cy", "amount": 50}])
    assert r.status == 201, r
    s = r.json
    assert isinstance(s["settlement_id"], str) and RFC3339.match(s["committed_at"])
    ps = s["payments"]
    assert [(p["from_handle"], p["to_handle"], p["amount"]) for p in ps] == [("ada", "bob", 100), ("bob", "cy", 50)]
    assert ps[0]["note"] == "n1" and ps[0]["visibility"] == "private"
    assert ps[1]["note"] == "" and ps[1]["visibility"] == "public"
    for p in ps:
        assert p["settlement_id"] == s["settlement_id"] and p["request_id"] is None
        assert p["created_at"] == s["committed_at"]
        assert p["currency"] == "EUR" and p["payment_id"]
    assert ops["ada"].balance() == 9900 and ops["bob"].balance() == 2550 and ops["cy"].balance() == 50
    assert total(ops) == SEED_TOTAL


def test_nonmember_settlement_id_null(api, ops):
    # ledger: 267
    r = ops["ada"].pay("bob", 5)
    assert r.status == 201 and "settlement_id" in r.json and r.json["settlement_id"] is None
    for p in ops["ada"].get("/activity").json["payments"]:
        assert "settlement_id" in p
    assert ops["ada"].pay_request("rq_1").json["settlement_id"] is None


def test_net_affordability(api, ops):
    # ledger: 263
    # cy has 0: receives 500 then sends 500 -> net 0, affordable whatever the order
    r = settle(ops["dee"], [{"from_handle": "cy", "to_handle": "ada", "amount": 500},
                            {"from_handle": "bob", "to_handle": "cy", "amount": 500}])
    assert r.status == 201, r
    assert ops["cy"].balance() == 0 and ops["ada"].balance() == 10500 and ops["bob"].balance() == 2000


def test_insufficient_collective_all_or_nothing(api, ops):
    # ledger: 264, 265, 10
    k = key()
    bad = [{"from_handle": "ada", "to_handle": "bob", "amount": 100},
           {"from_handle": "cy", "to_handle": "ada", "amount": 1}]
    assert is_error(settle(ops["dee"], bad, idem=k), 409, "insufficient_funds")
    assert ops["ada"].balance() == 10000 and ops["bob"].balance() == 2500
    assert not [p for p in ops["cy"].get("/activity", {"limit": 200}).json["payments"]
                if p.get("settlement_id")]
    # key not claimed: a different body with the same key is a first use
    r = settle(ops["dee"], [{"from_handle": "ada", "to_handle": "bob", "amount": 100}], idem=k)
    assert r.status == 201, r


@pytest.mark.parametrize("transfers,status,code", [
    ([], 422, "validation_failed"),
    ([{"from_handle": "ada", "to_handle": "bob", "amount": 1}] * 33, 422, "validation_failed"),
    ("nope", 422, "validation_failed"),
    ([5], 422, "validation_failed"),
    ([{"from_handle": "ada", "to_handle": "ada", "amount": 1}], 422, "self_payment"),
    ([{"from_handle": "ada", "to_handle": "ghost", "amount": 1}], 404, "not_found"),
    ([{"from_handle": "ghost", "to_handle": "ada", "amount": 1}], 404, "not_found"),
    ([{"from_handle": "ada", "to_handle": "bob", "amount": 0}], 422, "validation_failed"),
    ([{"from_handle": "ada", "to_handle": "bob", "amount": "1"}], 422, "validation_failed"),
    ([{"from_handle": "ada", "to_handle": "bob", "amount": 1, "note": None}], 422, "validation_failed"),
    ([{"from_handle": "ada", "to_handle": "bob", "amount": 1, "visibility": "x"}], 422, "validation_failed"),
    ([{"from_handle": "ada", "to_handle": "bob", "amount": 1, "note": "n" * 201}], 422, "validation_failed"),
    # input order decides between entry errors; entry errors beat insufficient funds
    ([{"from_handle": "ada", "to_handle": "ada", "amount": 1},
      {"from_handle": "ada", "to_handle": "ghost", "amount": 1}], 422, "self_payment"),
    ([{"from_handle": "ada", "to_handle": "ghost", "amount": 1},
      {"from_handle": "ada", "to_handle": "ada", "amount": 1}], 404, "not_found"),
    ([{"from_handle": "cy", "to_handle": "bob", "amount": 999},
      {"from_handle": "ada", "to_handle": "ghost", "amount": 1}], 404, "not_found"),
    ([{"from_handle": "cy", "to_handle": "bob", "amount": 999},
      {"from_handle": "ada", "to_handle": "bob", "amount": -1}], 422, "validation_failed"),
])
def test_settlement_validation(api, ops, transfers, status, code):
    # ledger: 258, 259, 260, 261, 265
    r = ops["dee"].post("/settlements", {"transfers": transfers}, idem=key())
    assert is_error(r, status, code), r
    assert total(ops) == SEED_TOTAL and ops["ada"].balance() == 10000


def test_settlement_32_ok_and_unknown_fields(api, ops):
    # ledger: 258, 262
    r = settle(ops["dee"], [{"from_handle": "ada", "to_handle": "bob", "amount": 1, "memo": 1}] * 32, extra_field=True)
    assert r.status == 201 and len(r.json["payments"]) == 32, r
    assert len({p["payment_id"] for p in r.json["payments"]}) == 32


def test_settlement_missing_transfers_422(api, ops):
    # ledger: 260
    assert is_error(ops["dee"].post("/settlements", {}, idem=key()), 422, "validation_failed")


def test_settlement_replay(api, ops):
    # ledger: 271, 272
    k = key()
    t = [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]
    a, b = settle(ops["dee"], t, idem=k), settle(ops["dee"], t, idem=k)
    assert a.status == 201 and b.status == 200 and a.json == b.json
    assert is_error(settle(ops["dee"], t * 2, idem=k), 409, "idempotency_key_reuse")
    assert ops["ada"].balance() == 9990


def test_settlement_feed_visibility_and_operator_privacy(api, ops):
    # ledger: 254, 269
    r = settle(ops["dee"], [{"from_handle": "ada", "to_handle": "bob", "amount": 10, "visibility": "private"},
                            {"from_handle": "bob", "to_handle": "cy", "amount": 5}])
    priv, pub = (p["payment_id"] for p in r.json["payments"])
    ids = lambda h: {p["payment_id"] for p in ops[h].get("/activity", {"limit": 200}).json["payments"]}
    assert priv in ids("ada") and priv in ids("bob")
    assert priv not in ids("cy") and priv not in ids("dee")
    assert pub in ids("dee") and pub in ids("ada")
    # operator gains no access to others' requests
    assert ops["dee"].get("/requests").json["requests"] == []
    assert is_error(ops["dee"].pay_request("rq_1"), 403, "forbidden")


def test_concurrent_settlements_invariants(api):
    # ledger: 9, 10, 265, 143
    for _ in range(3):
        fx = op_fixture()
        api.reset(fx)
        s = api.sessions(fx)
        k = key()
        same = [{"from_handle": "dee", "to_handle": "cy", "amount": 700}]
        jobs = [lambda: settle(s["dee"], same, idem=k)] * 10
        jobs += [lambda i=i: settle(s["dee"], [{"from_handle": "bob", "to_handle": "cy", "amount": 400},
                                                {"from_handle": "cy", "to_handle": "ada", "amount": 300}])
                 for i in range(15)]
        jobs += [lambda: s["bob"].pay("ada", 300)] * 10
        res = parallel(jobs)
        assert all(r.status < 500 for r in res), [r for r in res if r.status >= 500]
        assert sum(r.status == 201 for r in res[:10]) == 1
        bal = {h: x.balance() for h, x in s.items()}
        assert all(v >= 0 for v in bal.values()) and sum(bal.values()) == SEED_TOTAL, bal
        assert bal["dee"] == 0
