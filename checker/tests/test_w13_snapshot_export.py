"""W-13 / D-27: statement snapshots travel in exports (additive `snapshots`, format_version 1) and imported
tokens page their frozen result until the importing service's next reset. Binds from stage 3 (amended)."""

from __future__ import annotations

import json
import os

import pytest

from pf import Api, is_error, key
from s3 import T1, history_fixture

pytestmark = pytest.mark.item("W-13")


def frozen_then_changed(api):
    """Reset, take a two-page snapshot for ada, then change history so a live read differs."""
    fx = history_fixture()
    api.reset(fx)
    ada = api.session("ada@example.com")
    p1 = ada.get("/statement", params={"limit": 2}).json
    tok = p1["snapshot"]
    p2 = ada.get("/statement", params={"snapshot": tok, "limit": 2, "offset": 2}).json
    assert ada.post("/payments/p_a/corrections", {"expected_revision": 1, "amount": 400, "effective_at": T1,
                                                  "reason": "fix"}, idem=key()).status == 201
    assert ada.pay("bob", 7).status == 201
    return ada, tok, p1, p2


def page(other, s, tok, offset):
    return other.req("GET", "/statement", headers={"Authorization": f"Bearer {s.token}"},
                     params={"snapshot": tok, "limit": 2, "offset": offset})


def test_snapshot_survives_same_stage_export_import(api):
    # ledger: 3046, D-27, 2084, 2085
    url2 = os.environ.get("PF_BASE_URL_2")
    if not url2:
        pytest.skip("no second instance (run_checks starts one in --repo mode)")
    ada, tok, p1, p2 = frozen_then_changed(api)
    snap = api.req("GET", "/_test/export").json
    assert snap["format_version"] == 1
    other = Api(url2)
    try:
        other.reset(history_fixture())
        assert other.req("POST", "/_test/import", body=snap).status == 204
        a, b = page(other, ada, tok, 0), page(other, ada, tok, 2)
        assert a.status == 200 and b.status == 200, (a, b)
        for got, want in ((a.json, p1), (b.json, p2)):
            assert got["entries"] == want["entries"] and got["has_more"] == want["has_more"]
            assert got["opening_balance"] == want["opening_balance"] == 11100
            assert got["closing_balance"] == want["closing_balance"] == 10000
        bob = other.session("bob@example.com")
        assert is_error(page(other, bob, tok, 0), 404, "not_found")      # still bound to its owner
        other.reset(history_fixture())
        ada2 = other.session("ada@example.com")
        assert is_error(page(other, ada2, tok, 0), 404, "not_found")     # tokens last until reset
    finally:
        other.close()


def test_export_without_snapshots_still_imports(api):
    # ledger: 3046, D-27 (an absent array means none)
    url2 = os.environ.get("PF_BASE_URL_2")
    if not url2:
        pytest.skip("no second instance (run_checks starts one in --repo mode)")
    ada, tok, _, _ = frozen_then_changed(api)
    snap = api.req("GET", "/_test/export").json

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if "snapshot" not in k}
        return o
    other = Api(url2)
    try:
        other.reset(history_fixture())
        assert other.req("POST", "/_test/import", body=strip(snap)).status == 204
        assert is_error(page(other, ada, tok, 0), 404, "not_found")
        me = other.req("GET", "/me", headers={"Authorization": f"Bearer {ada.token}"}).json
        assert me["balance"] == 10600 - 7
    finally:
        other.close()


def test_token_taken_before_import_survives_import(api):
    # ledger: 3046, D-27 (imported snapshots merge in; the importer's own live tokens keep paging)
    url2 = os.environ.get("PF_BASE_URL_2")
    if not url2:
        pytest.skip("no second instance (run_checks starts one in --repo mode)")
    ada_a, tok_a, p1_a, _ = frozen_then_changed(api)
    snap = api.req("GET", "/_test/export").json
    other = Api(url2)
    try:
        fx = history_fixture()
        other.reset(fx)
        ada_b = other.session("ada@example.com")
        mine = ada_b.get("/statement", params={"limit": 2}).json
        assert other.req("POST", "/_test/import", body=snap).status == 204
        r = page(other, ada_a, mine["snapshot"], 0)  # same owner (u_ada), now holding the imported session
        assert r.status == 200, r
        assert r.json["entries"] == mine["entries"] and r.json["closing_balance"] == mine["closing_balance"]
        assert page(other, ada_a, tok_a, 0).json["entries"] == p1_a["entries"]
    finally:
        other.close()


# ---------------------------------------------------------------- D-27 merge rule (ledger 99aaa2c)

def _second():
    url2 = os.environ.get("PF_BASE_URL_2")
    if not url2:
        pytest.skip("no second instance (run_checks starts one in --repo mode)")
    return Api(url2)


def _exported_snapshots(snap):
    assert isinstance(snap.get("snapshots"), list) and snap["snapshots"], "export carries no snapshots array"
    return snap["snapshots"]


def test_same_export_imported_twice(api):
    # ledger: 3046, D-27 (an identical imported token is accepted unchanged)
    ada, tok, p1, p2 = frozen_then_changed(api)
    snap = api.req("GET", "/_test/export").json
    other = _second()
    try:
        other.reset(history_fixture())
        assert other.req("POST", "/_test/import", body=snap).status == 204
        first = [page(other, ada, tok, 0).json, page(other, ada, tok, 2).json]
        r = other.req("POST", "/_test/import", body=snap)
        assert r.status == 204, r
        second = [page(other, ada, tok, 0).json, page(other, ada, tok, 2).json]
        assert first == second and first[0]["entries"] == p1["entries"] and first[1]["entries"] == p2["entries"]
    finally:
        other.close()


@pytest.mark.parametrize("clash", ["owner", "result"])
def test_clashing_token_rejects_whole_import(api, clash):
    # ledger: 3046, D-27 (clash with a live token: 422, nothing changes)
    ada, tok, p1, _ = frozen_then_changed(api)
    snap = api.req("GET", "/_test/export").json
    other = _second()
    try:
        other.reset(history_fixture())
        assert other.req("POST", "/_test/import", body=snap).status == 204  # tok is now live on B
        before = other.req("GET", "/_test/export")
        bad = json.loads(json.dumps(snap))
        item = [s for s in _exported_snapshots(bad) if s.get("token") == tok][0]
        if clash == "owner":
            item["user_id"] = "u_bob"
        else:
            item["result"]["closing_balance"] = item["result"]["closing_balance"] + 1
        bad["state"]["tables"]["users"][0]["display_name"] = "Changed"  # would show if rows were applied
        r = other.req("POST", "/_test/import", body=bad)
        assert is_error(r, 422, "validation_failed"), r
        after = other.req("GET", "/_test/export")
        assert after.status == 200 and after.text == before.text
        assert page(other, ada, tok, 0).json["entries"] == p1["entries"]
    finally:
        other.close()


@pytest.mark.parametrize("variant", ["identical", "different"])
def test_duplicate_token_within_export(api, variant):
    # ledger: 3046, D-27 (a duplicate token inside one export: 422)
    ada, tok, _, _ = frozen_then_changed(api)
    snap = api.req("GET", "/_test/export").json
    item = [s for s in _exported_snapshots(snap) if s.get("token") == tok][0]
    dup = json.loads(json.dumps(item))
    if variant == "different":
        dup["result"]["closing_balance"] = dup["result"]["closing_balance"] + 1
    snap["snapshots"].append(dup)
    other = _second()
    try:
        other.reset(history_fixture())
        before = other.req("GET", "/_test/export")
        r = other.req("POST", "/_test/import", body=snap)
        assert is_error(r, 422, "validation_failed"), r
        assert other.req("GET", "/_test/export").text == before.text
    finally:
        other.close()
