"""W-13 / D-27: statement snapshots travel in exports (additive `snapshots`, format_version 1) and imported
tokens page their frozen result until the importing service's next reset. Binds from stage 3 (amended)."""

from __future__ import annotations

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
