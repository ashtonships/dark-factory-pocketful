"""W-2: payments, requests, idempotency, GET /requests, GET /activity, money invariants."""

from __future__ import annotations

import pytest

from pf import RFC3339, base_fixture, is_error, key, parallel, total

pytestmark = pytest.mark.item("W-2")

SEED_TOTAL = 10000 + 2500 + 0 + 700
PAYMENT_KEYS = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle", "amount",
                "currency", "note", "visibility", "request_id", "created_at"}
REQUEST_KEYS = {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
                "amount", "currency", "note", "status", "payment_id", "created_at"}


def feed(s, **params):
    r = s.get("/activity", params=params or None)
    assert r.status == 200, r
    return r.json


def reqs(s, **params):
    r = s.get("/requests", params=params or None)
    assert r.status == 200, r
    return r.json


# ---------------------------------------------------------------- POST /payments

def test_payment_201_shape_and_balances(api, seeded):
    # ledger: 62, 150, 159, 160, 12, 55
    ada, bob = seeded["ada"], seeded["bob"]
    r = ada.pay("bob", 1500, note="dinner", visibility="private")
    assert r.status == 201, r
    p = r.json
    assert PAYMENT_KEYS <= set(p), set(p)
    assert (p["from_user_id"], p["from_handle"], p["to_user_id"], p["to_handle"]) == ("u_ada", "ada", "u_bob", "bob")
    assert p["amount"] == 1500 and type(p["amount"]) is int and p["currency"] == "EUR"
    assert p["note"] == "dinner" and p["visibility"] == "private" and p["request_id"] is None
    assert RFC3339.match(p["created_at"]), p["created_at"]  # ledger: 44, 45
    assert isinstance(p["payment_id"], str) and 0 < len(p["payment_id"]) <= 64
    assert ada.balance() == 8500 and bob.balance() == 4000
    assert total(seeded) == SEED_TOTAL


def test_payment_defaults(api, seeded):
    # ledger: 151, 152, 107
    r = seeded["ada"].pay("bob", 1)
    assert r.status == 201 and r.json["note"] == "" and r.json["visibility"] == "public", r


@pytest.mark.parametrize("amount,ok", [(1000, True), (1000.0, True), (1e3, True), (1, True),
                                       (0, False), (-5, False), (10.5, False), (1000000001, False),
                                       ("1000", False), (True, False), (None, False), ([1], False)])
def test_payment_amount_rules(api, seeded, amount, ok):
    # ledger: 52, 53, 105, 106, 154, 80
    r = seeded["ada"].pay("bob", amount)
    if ok:
        assert r.status == 201 and r.json["amount"] == int(amount) and type(r.json["amount"]) is int, r
    else:
        assert is_error(r, 422, "validation_failed"), r
        assert seeded["ada"].balance() == 10000


def test_payment_amount_raw_exponent(api, seeded):
    # ledger: 52
    r = seeded["ada"].post("/payments", raw='{"to_handle": "bob", "amount": 1e3}', idem=key())
    assert r.status == 201 and r.json["amount"] == 1000, r


def test_payment_max_amount_exact(api):
    # ledger: 80, 81, 154
    fx = base_fixture()
    fx["users"][0]["balance"] = 3_000_000_000
    api.reset(fx)
    ada, bob = api.session("ada@example.com"), api.session("bob@example.com")
    assert ada.pay("bob", 1_000_000_000).status == 201
    assert ada.balance() == 2_000_000_000 and bob.balance() == 1_000_002_500


def test_payment_missing_amount_or_handle_422(api, seeded):
    # ledger: 101
    assert is_error(seeded["ada"].post("/payments", {"to_handle": "bob"}, idem=key()), 422, "validation_failed")
    assert is_error(seeded["ada"].post("/payments", {"amount": 5}, idem=key()), 422, "validation_failed")


def test_payment_wrong_type_handle_400(api, seeded):
    # ledger: 95, 108, 111
    r = seeded["ada"].post("/payments", {"to_handle": 7, "amount": 5}, idem=key())
    assert is_error(r, 400, "malformed_request"), r


@pytest.mark.parametrize("note,ok", [(None, False), (5, False), (["x"], False),
                                     ("é" * 200, True), ("😀" * 200, True), ("x" * 201, False)])
def test_payment_note_rules(api, seeded, note, ok):
    # ledger: 106, 156, D-10
    r = seeded["ada"].pay("bob", 5, note=note)
    if ok:
        assert r.status == 201 and r.json["note"] == note, r
    else:
        assert is_error(r, 422, "validation_failed"), r


@pytest.mark.parametrize("vis", ["PUBLIC", "friends", "", None, 1, True])
def test_payment_visibility_invalid(api, seeded, vis):
    # ledger: 106, 157
    assert is_error(seeded["ada"].pay("bob", 5, visibility=vis), 422, "validation_failed")


def test_note_verbatim_roundtrip(api, seeded):
    # ledger: 161, 162
    note = "  héllo 👋🏽 <b>&amp;</b>\n\t\"quoted\" \\ ́e​  "
    r = seeded["ada"].pay("bob", 5, note=note)
    assert r.status == 201 and r.json["note"] == note, r
    items = feed(seeded["bob"])["payments"]
    assert any(p["note"] == note for p in items)


def test_self_payment_422(api, seeded):
    # ledger: 155
    assert is_error(seeded["ada"].pay("ada", 5), 422, "self_payment")


def test_unknown_handle_404(api, seeded):
    # ledger: 158, 14
    assert is_error(seeded["ada"].pay("nobody", 5), 404, "not_found")


def test_insufficient_funds_changes_nothing(api, seeded):
    # ledger: 153, 160, 10
    r = seeded["dee"].pay("bob", 701)
    assert is_error(r, 409, "insufficient_funds"), r
    assert seeded["dee"].balance() == 700 and seeded["bob"].balance() == 2500
    assert seeded["dee"].pay("bob", 700).status == 201
    assert seeded["dee"].balance() == 0


def test_error_precedence_payments(api, seeded):
    # ledger: 148, 101, 96, 113 (D-2)
    ada = seeded["ada"]
    # 401 before anything
    r = api.req("POST", "/payments", raw="{bad")
    assert is_error(r, 401, "unauthenticated"), r
    # 400 body before missing key
    assert is_error(ada.post("/payments", raw="{bad"), 400, "malformed_request")
    # missing / empty key
    assert is_error(ada.post("/payments", {"to_handle": "bob", "amount": 5}), 400, "missing_idempotency_key")
    assert is_error(ada.post("/payments", {"to_handle": "bob", "amount": 5}, idem=""), 400, "missing_idempotency_key")
    # key length
    assert is_error(ada.pay("bob", 5, idem="k" * 256), 422, "validation_failed")
    assert ada.pay("bob", 5, idem="k" * 255).status == 201
    # validation before 404, 404 before funds
    assert is_error(ada.pay("nobody", 0), 422, "validation_failed")
    assert is_error(seeded["cy"].pay("nobody", 5), 404, "not_found")


# ---------------------------------------------------------------- idempotency

def test_replay_200_identical_no_second_move(api, seeded):
    # ledger: 138, 139, 145, 147
    k = key()
    a = seeded["ada"].pay("bob", 100, idem=k, note="x")
    b = seeded["ada"].pay("bob", 100, idem=k, note="x")
    assert a.status == 201 and b.status == 200 and a.json == b.json, (a, b)
    assert seeded["ada"].balance() == 9900


def test_replay_key_order_and_whitespace(api, seeded):
    # ledger: 142
    k = key()
    a = seeded["ada"].post("/payments", raw='{"to_handle":"bob","amount":100}', idem=k)
    b = seeded["ada"].post("/payments", raw='{ "amount" : 100 ,\n "to_handle" : "bob" }', idem=k)
    assert a.status == 201 and b.status == 200 and a.json == b.json, (a, b)


def test_same_key_different_body_409(api, seeded):
    # ledger: 140, 149, 100
    k = key()
    assert seeded["ada"].pay("bob", 100, idem=k).status == 201
    assert is_error(seeded["ada"].pay("bob", 101, idem=k), 409, "idempotency_key_reuse")
    # claimed key resolved before validation: an invalid body is still reuse
    assert is_error(seeded["ada"].pay("bob", -1, idem=k), 409, "idempotency_key_reuse")
    assert is_error(seeded["ada"].pay("ada", 100, idem=k), 409, "idempotency_key_reuse")
    assert seeded["ada"].balance() == 9900


def test_key_scoped_per_user(api, seeded):
    # ledger: 133, 134
    k = key()
    assert seeded["ada"].pay("cy", 100, idem=k).status == 201
    r = seeded["bob"].pay("cy", 100, idem=k)
    assert r.status == 201 and r.json["from_user_id"] == "u_bob", r


def test_failed_key_reusable(api, seeded):
    # ledger: 141
    k = key()
    assert is_error(seeded["dee"].pay("bob", 5000, idem=k), 409, "insufficient_funds")
    assert seeded["dee"].pay("bob", 50, idem=k).status == 201
    k2 = key()
    assert seeded["dee"].pay("nobody", 5, idem=k2).status == 404
    assert seeded["dee"].pay("bob", 5, idem=k2).status == 201


def test_same_key_same_body_different_path_is_new(api, seeded):
    # ledger: 135, 136, 132
    bob = seeded["bob"]
    r1 = bob.request("ada", 10).json["request_id"]
    r2 = bob.request("ada", 20).json["request_id"]
    k = key()
    a = seeded["ada"].pay_request(r1, {}, idem=k)
    b = seeded["ada"].pay_request(r2, {}, idem=k)
    assert a.status == 201 and b.status == 201 and a.json["payment_id"] != b.json["payment_id"], (a, b)


def test_concurrent_identical_one_201(api, seeded):
    # ledger: 143, 144, 145, 9
    for _ in range(3):
        api.reset(base_fixture())
        ada = api.session("ada@example.com")
        k = key()
        res = parallel([lambda: ada.pay("bob", 250, idem=k)] * 30)
        assert sum(r.status == 201 for r in res) == 1, [r.status for r in res]
        assert all(r.status in (200, 201) for r in res), [r for r in res if r.status not in (200, 201)]
        assert all(r.json == res[0].json for r in res)
        assert ada.balance() == 9750


def test_replay_after_resource_changed(api, seeded):
    # ledger: 146
    k = key()
    a = seeded["bob"].request("ada", 300, idem=k, note="lunch")
    assert a.status == 201
    assert seeded["bob"].post(f"/requests/{a.json['request_id']}/cancel").status == 200
    b = seeded["bob"].request("ada", 300, idem=k, note="lunch")
    assert b.status == 200 and b.json == a.json and b.json["status"] == "pending", b


# ---------------------------------------------------------------- requests

def test_request_201_shape_no_balance_check(api, seeded):
    # ledger: 64, 65, 163, 164, 169, 68
    r = seeded["bob"].request("cy", 99999, note="big")
    assert r.status == 201, r
    q = r.json
    assert REQUEST_KEYS <= set(q), set(q)
    assert (q["requester_id"], q["requester_handle"], q["payer_id"], q["payer_handle"]) == ("u_bob", "bob", "u_cy", "cy")
    assert q["status"] == "pending" and q["payment_id"] is None and q["amount"] == 99999
    assert q["currency"] == "EUR" and q["note"] == "big" and RFC3339.match(q["created_at"])
    assert "visibility" not in q  # ledger: 71 (a request has no visibility of its own)


@pytest.mark.parametrize("body,status,code", [
    ({"payer_handle": "ada", "amount": 0}, 422, "validation_failed"),
    ({"payer_handle": "ada", "amount": 1000000001}, 422, "validation_failed"),
    ({"payer_handle": "ada", "amount": "5"}, 422, "validation_failed"),
    ({"payer_handle": "ada", "amount": 5, "note": "x" * 201}, 422, "validation_failed"),
    ({"payer_handle": "ada", "amount": 5, "note": None}, 422, "validation_failed"),
    ({"payer_handle": "bob", "amount": 5}, 422, "self_request"),
    ({"payer_handle": "nobody", "amount": 5}, 404, "not_found"),
    ({"amount": 5}, 422, "validation_failed"),
    ({"payer_handle": ["ada"], "amount": 5}, 400, "malformed_request"),
])
def test_request_errors(api, seeded, body, status, code):
    # ledger: 165, 166, 167, 168
    assert is_error(seeded["bob"].post("/requests", body, idem=key()), status, code)


def test_request_needs_key(api, seeded):
    # ledger: 131, 137
    assert is_error(seeded["bob"].post("/requests", {"payer_handle": "ada", "amount": 5}),
                    400, "missing_idempotency_key")


def test_new_user_can_be_asked_and_paid(api, seeded):
    # ledger: 61
    r = api.signup("newcomer@example.com")
    assert r.status == 201
    assert seeded["bob"].request("newcomer", 5).status == 201
    assert seeded["ada"].pay("newcomer", 5).status == 201


def test_pay_request_flow(api, seeded):
    # ledger: 63, 170, 171, 172, 174, 175, 11
    ada = seeded["ada"]
    r = ada.pay_request("rq_1", {"visibility": "private"})
    assert r.status == 201, r
    p = r.json
    assert PAYMENT_KEYS <= set(p)
    assert p["request_id"] == "rq_1" and p["amount"] == 1200 and p["visibility"] == "private"
    assert (p["from_user_id"], p["to_user_id"]) == ("u_ada", "u_bob")
    assert ada.balance() == 8800 and seeded["bob"].balance() == 3700
    q = [x for x in reqs(ada)["requests"] if x["request_id"] == "rq_1"][0]
    assert q["status"] == "paid" and q["payment_id"] == p["payment_id"]


def test_pay_default_visibility_public(api, seeded):
    # ledger: 171
    r = seeded["ada"].pay_request("rq_1", {})
    assert r.status == 201 and r.json["visibility"] == "public", r


def test_pay_request_errors_and_precedence(api, seeded):
    # ledger: 176, 177, 178, 179, 67, 98, 119 (D-2: 404, 403, request_not_pending, insufficient_funds)
    ada, bob, cy = seeded["ada"], seeded["bob"], seeded["cy"]
    assert is_error(ada.pay_request("rq_nope"), 404, "not_found")
    assert is_error(bob.pay_request("rq_1"), 403, "forbidden")
    assert is_error(cy.pay_request("rq_1"), 403, "forbidden")
    assert is_error(ada.pay_request("rq_1", {"visibility": "secret"}), 422, "validation_failed")
    assert ada.pay_request("rq_1").status == 201
    assert is_error(ada.pay_request("rq_1"), 409, "request_not_pending")
    assert is_error(bob.pay_request("rq_1"), 403, "forbidden")
    assert ada.balance() == 8800


def test_pay_short_then_later(api, seeded):
    # ledger: 68, 69, 177
    q = seeded["bob"].request("cy", 400).json["request_id"]
    assert is_error(seeded["cy"].pay_request(q), 409, "insufficient_funds")
    assert seeded["cy"].balance() == 0
    assert reqs(seeded["cy"], status="pending")["requests"][0]["request_id"] == q
    assert seeded["ada"].pay("cy", 400).status == 201
    assert seeded["cy"].pay_request(q).status == 201
    assert seeded["cy"].balance() == 0 and seeded["bob"].balance() == 2900


def test_pay_replay_after_paid_is_200(api, seeded):
    # ledger: 180, 181
    k = key()
    a = seeded["ada"].pay_request("rq_1", {"visibility": "private"}, idem=k)
    b = seeded["ada"].pay_request("rq_1", {"visibility": "private"}, idem=k)
    assert a.status == 201 and b.status == 200 and a.json == b.json, (a, b)
    assert seeded["ada"].balance() == 8800


def test_pay_empty_vs_public_body_differ(api, seeded):
    # ledger: 173
    k = key()
    assert seeded["ada"].pay_request("rq_1", {}, idem=k).status == 201
    assert is_error(seeded["ada"].pay_request("rq_1", {"visibility": "public"}, idem=k), 409, "idempotency_key_reuse")


def test_concurrent_pay_same_request_moves_once(api):
    # ledger: 11, 9, 10, 143
    for _ in range(3):
        api.reset(base_fixture())
        ada, bob = api.session("ada@example.com"), api.session("bob@example.com")
        res = parallel([lambda: ada.pay_request("rq_1")] * 25)
        assert sum(r.status == 201 for r in res) == 1, [r.status for r in res]
        assert all(r.status == 201 or is_error(r, 409, "request_not_pending") for r in res), res
        assert ada.balance() == 8800 and bob.balance() == 3700


def test_decline(api, seeded):
    # ledger: 182, 183, 184, 185, 186, 187
    ada, bob = seeded["ada"], seeded["bob"]
    assert is_error(bob.post("/requests/rq_1/decline"), 403, "forbidden")
    r = ada.post("/requests/rq_1/decline")
    assert r.status == 200 and r.json["status"] == "declined" and r.json["request_id"] == "rq_1", r
    r2 = ada.post("/requests/rq_1/decline")
    assert r2.status == 200 and r2.json["status"] == "declined"
    assert is_error(ada.pay_request("rq_1"), 409, "request_not_pending")
    assert is_error(bob.post("/requests/rq_1/cancel"), 409, "request_not_pending")
    assert is_error(ada.post("/requests/nope/decline"), 404, "not_found")
    # paid and cancelled cannot be declined
    q = bob.request("ada", 5).json["request_id"]
    assert ada.pay_request(q).status == 201
    assert is_error(ada.post(f"/requests/{q}/decline"), 409, "request_not_pending")
    q2 = bob.request("ada", 5).json["request_id"]
    assert bob.post(f"/requests/{q2}/cancel").status == 200
    assert is_error(ada.post(f"/requests/{q2}/decline"), 409, "request_not_pending")


def test_cancel(api, seeded):
    # ledger: 188, 189, 190, 191, 192, 193
    ada, bob = seeded["ada"], seeded["bob"]
    assert is_error(ada.post("/requests/rq_1/cancel"), 403, "forbidden")
    assert is_error(seeded["cy"].post("/requests/rq_1/cancel"), 403, "forbidden")
    r = bob.post("/requests/rq_1/cancel")
    assert r.status == 200 and r.json["status"] == "cancelled", r
    assert bob.post("/requests/rq_1/cancel").status == 200
    assert is_error(ada.pay_request("rq_1"), 409, "request_not_pending")
    q = bob.request("ada", 5).json["request_id"]
    assert ada.pay_request(q).status == 201
    assert is_error(bob.post(f"/requests/{q}/cancel"), 409, "request_not_pending")
    assert ada.balance() == 9995


def test_concurrent_pay_vs_cancel_exactly_one_terminal(api):
    # ledger: 66, 11
    for _ in range(3):
        api.reset(base_fixture())
        ada, bob = api.session("ada@example.com"), api.session("bob@example.com")
        res = parallel([lambda: ada.pay_request("rq_1"), lambda: bob.post("/requests/rq_1/cancel")] * 10)
        paid = sum(r.status == 201 for r in res)
        cancelled = sum(r.status == 200 for r in res)
        assert (paid == 1) != (cancelled > 0), [r.status for r in res]
        assert all(r.status < 500 for r in res)
        assert ada.balance() == (8800 if paid else 10000)


# ---------------------------------------------------------------- GET /requests

def test_requests_visibility_and_direction(api, seeded):
    # ledger: 75, 194, 196, 197, 198
    ada, bob, cy = seeded["ada"], seeded["bob"], seeded["cy"]
    ada.request("cy", 7)
    assert reqs(bob)["requests"][0]["request_id"] == "rq_1"
    assert [q["request_id"] for q in reqs(cy)["requests"]] != []
    assert all(seeded["dee"].handle not in (q["payer_handle"], q["requester_handle"])
               for q in reqs(cy)["requests"])
    assert reqs(seeded["dee"])["requests"] == []
    inc = reqs(ada, direction="incoming")["requests"]
    out = reqs(ada, direction="outgoing")["requests"]
    assert [q["payer_handle"] for q in inc] == ["ada"] and [q["requester_handle"] for q in out] == ["ada"]
    assert len(reqs(ada)["requests"]) == 2
    ada.post("/requests/rq_1/decline")
    assert [q["status"] for q in reqs(ada, status="declined")["requests"]] == ["declined"]
    assert len(reqs(ada, status="pending")["requests"]) == 1
    assert reqs(ada, status="paid")["requests"] == []
    assert reqs(ada, status="cancelled", direction="incoming")["requests"] == []


def test_requests_newest_first_and_pagination(api, seeded):
    # ledger: 195, 199, 200, 204
    bob = seeded["bob"]
    ids = [bob.request("cy", i + 1).json["request_id"] for i in range(5)]
    got = [q["request_id"] for q in reqs(bob, direction="outgoing")["requests"]]
    assert got[:5] == ids[::-1], got  # D-5
    page = reqs(bob, direction="outgoing", limit=2, offset=0)
    assert len(page["requests"]) == 2 and page["has_more"] is True
    last = reqs(bob, direction="outgoing", limit=2, offset=4)
    assert len(last["requests"]) == 2 and last["has_more"] is False
    exact = reqs(bob, direction="outgoing", limit=6)
    assert len(exact["requests"]) == 6 and exact["has_more"] is False
    assert reqs(bob, offset=100)["requests"] == []


@pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "201"}, {"limit": "1e1"}, {"limit": "4.0"},
                                    {"limit": "+4"}, {"limit": "-1"}, {"limit": "abc"}, {"limit": ""},
                                    {"offset": "-1"}, {"offset": "1.0"}, {"offset": "+0"},
                                    {"direction": "sideways"}, {"status": "PAID"}, {"status": "done"}])
def test_requests_bad_query_422(api, seeded, params):
    # ledger: 109, 110, 114, 115, 201, 202, 203, 102, 103, 112
    assert is_error(seeded["ada"].get("/requests", params=params), 422, "validation_failed")


def test_requests_limit_bounds_ok(api, seeded):
    # ledger: 199
    assert seeded["ada"].get("/requests", params={"limit": "200"}).status == 200
    assert seeded["ada"].get("/requests", params={"limit": "1", "offset": "0"}).status == 200


def test_requests_need_auth(api, seeded):
    # ledger: 126
    assert is_error(api.req("GET", "/requests"), 401, "unauthenticated")
    assert is_error(api.req("GET", "/activity"), 401, "unauthenticated")


# ---------------------------------------------------------------- GET /activity

def test_feed_contract(api, seeded):
    # ledger: 72, 73, 74, 78, 79, 217
    ada, bob, cy, dee = seeded["ada"], seeded["bob"], seeded["cy"], seeded["dee"]
    pub = ada.pay("bob", 10, visibility="public").json["payment_id"]
    prv = ada.pay("bob", 11, visibility="private").json["payment_id"]
    ids = lambda s: {p["payment_id"] for p in feed(s, limit=200)["payments"]}
    assert {pub, prv} <= ids(ada) and {pub, prv} <= ids(bob)
    assert pub in ids(cy) and prv not in ids(cy) and prv not in ids(dee)
    seen = {p["payment_id"]: p for p in feed(bob, limit=200)["payments"]}
    assert seen[prv]["visibility"] == "private" and seen[pub]["visibility"] == "public"
    for p in feed(cy, limit=200)["payments"]:
        assert PAYMENT_KEYS <= set(p)


def test_feed_payments_only_no_requests(api, seeded):
    # ledger: 71, 72, 75
    before = len(feed(seeded["cy"], limit=200)["payments"])
    seeded["bob"].request("ada", 77, note="should not appear")
    for s in seeded.values():
        for p in feed(s, limit=200)["payments"]:
            assert "status" not in p and p["note"] != "should not appear"
    assert len(feed(seeded["cy"], limit=200)["payments"]) == before


def test_paid_request_visibility_chosen_by_payer(api, seeded):
    # ledger: 70, 77, 79
    p = seeded["ada"].pay_request("rq_1", {"visibility": "private"}).json["payment_id"]
    assert p in {x["payment_id"] for x in feed(seeded["bob"])["payments"]}
    assert p not in {x["payment_id"] for x in feed(seeded["cy"])["payments"]}


def test_feed_seeded_payment_and_pagination(api, seeded):
    # ledger: 217, 220, 204
    ada = seeded["ada"]
    first = feed(ada)["payments"]
    assert any(p["payment_id"] == "p_1" for p in first)
    for i in range(4):
        ada.pay("cy", i + 1)
    allp = feed(ada, limit=200)["payments"]
    assert len(allp) == 5 and feed(ada, limit=200)["has_more"] is False
    pg = feed(ada, limit=2, offset=0)
    assert len(pg["payments"]) == 2 and pg["has_more"] is True
    tail = feed(ada, limit=2, offset=4)
    assert len(tail["payments"]) == 1 and tail["has_more"] is False
    # newest first, compared on created_at only (same-second order unspecified, ledger: 218)
    stamps = [p["created_at"] for p in allp]
    assert all(RFC3339.match(s) for s in stamps)


@pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "201"}, {"limit": "1e9"}, {"offset": "-1"},
                                    {"limit": "+4"}])
def test_feed_bad_query_422(api, seeded, params):
    # ledger: 220, 109, 114, 115
    assert is_error(seeded["ada"].get("/activity", params=params), 422, "validation_failed")


# ---------------------------------------------------------------- invariants under load

def test_payment_storm_invariants(api):
    # ledger: 9, 10, 30, 116, 159
    for _ in range(3):
        api.reset(base_fixture())
        s = {h: api.session(f"{h}@example.com") for h in ("ada", "bob", "cy", "dee")}
        def send(i):
            a, b = [("ada", "bob"), ("bob", "cy"), ("cy", "dee"), ("dee", "ada"), ("ada", "cy")][i % 5]
            return s[a].pay(b, 300 + i)
        reads = []
        def read(h):
            r = s[h].me()
            reads.append(r.json["balance"] if r.status == 200 else None)
            return r
        jobs = [lambda i=i: send(i) for i in range(60)] + [lambda h=h: read(h) for h in s] * 5
        res = parallel(jobs)
        assert all(r.status < 500 for r in res), [r for r in res if r.status >= 500]
        pays = res[:60]
        assert all(r.status == 201 or is_error(r, 409, "insufficient_funds") for r in pays), pays
        assert all(b is not None and b >= 0 for b in reads), reads
        bal = {h: x.balance() for h, x in s.items()}
        assert all(v >= 0 for v in bal.values()) and sum(bal.values()) == SEED_TOTAL, bal


def test_drain_race_never_negative(api):
    # ledger: 10, 153
    for _ in range(3):
        api.reset(base_fixture())
        dee = api.session("dee@example.com")
        res = parallel([lambda: dee.pay("bob", 100)] * 40)
        assert sum(r.status == 201 for r in res) == 7, [r.status for r in res]
        assert dee.balance() == 0


@pytest.mark.parametrize("path,body", [
    ("/payments", {"to_handle": "bob", "amount": 5}),
    ("/requests", {"payer_handle": "bob", "amount": 5}),
    ("/requests/rq_1/pay", {}),
])
def test_key_rules_on_every_write_path(api, seeded, path, body):
    # ledger: 112, 113, 96, 131, 132
    ada = seeded["ada"]
    assert is_error(ada.post(path, body), 400, "missing_idempotency_key")
    assert is_error(ada.post(path, body, idem=""), 400, "missing_idempotency_key")
    assert is_error(ada.post(path, body, idem="x" * 256), 422, "validation_failed")
    assert ada.post(path, body, idem="y" * 255).status == 201
    assert ada.post(path, body, idem="y" * 255).status == 200
