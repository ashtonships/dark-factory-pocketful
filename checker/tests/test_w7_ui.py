"""W-7: stage-2 browser screens, driven in Chromium against the running service.

Every check here goes through the real UI (Playwright), with the API used only to arrange
state or to observe money.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

from pf import PASSWORD, Api, base_fixture, key

pytestmark = pytest.mark.item("W-7")

pw = pytest.importorskip("playwright.sync_api")
expect = pw.expect
expect.set_options(timeout=8000)

SHOTS = Path(os.environ.get("PF_OUT", "/tmp/pf-checker-out")) / "screens"


def fmt(minor: int, mu: int = 2, cur: str = "EUR") -> str:
    if mu == 0:
        return f"{minor} {cur}"
    q, r = divmod(minor, 10 ** mu)
    return f"{q}.{r:0{mu}d} {cur}"


def iso(delta):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delta)).replace(microsecond=0).isoformat()


def ui_fixture(**over):
    fx = base_fixture(settlement_operator_ids=["u_dee"])
    fx["authorizations"] = [
        {"id": "a_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 2000, "note": "deposit",
         "visibility": "public", "status": "open", "expires_at": iso(7200)},
    ]
    fx.update(over)
    return fx


@pytest.fixture(scope="session")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser, api):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, base_url=api.base)
    pg = ctx.new_page()
    yield pg
    ctx.close()


def T(page, tid):
    return page.get_by_test_id(tid)


def login(page, email="ada@example.com", password=PASSWORD, path="/"):
    page.goto("/login")
    T(page, "login-email").fill(email)
    T(page, "login-password").fill(password)
    T(page, "login-submit").click()
    expect(T(page, "current-user")).to_be_visible()
    if path:
        page.goto(path)
        expect(T(page, "current-user")).to_be_visible()


def shot(page, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def amount_of(loc) -> int:
    return int(loc.get_attribute("data-amount"))


def posts(page, path):
    """Record every POST to `path` the page sends: (headers, json body)."""
    seen = []
    def on(req):
        if req.method == "POST" and urlparse(req.url).path == path:
            try:
                body = json.loads(req.post_data or "null")
            except ValueError:
                body = req.post_data
            seen.append((req.headers, body))
    page.on("request", on)
    return seen


# ---------------------------------------------------------------- routes, auth, chrome

@pytest.mark.parametrize("path", ["/", "/requests", "/split", "/signup", "/login", "/authorizations"])
def test_routes_reachable_as_html(api, page, path):
    # ledger: 1005, 1008, 1009, 1010, 1011, 1012, 1203, 1015
    api.reset(ui_fixture())
    r = page.goto(path)
    assert r.status == 200 and "text/html" in r.headers.get("content-type", ""), (path, r.status)


def test_signup_flow_and_identity(api, page):
    # ledger: 1029, 1030, 1033, 1034
    api.reset(ui_fixture())
    page.goto("/signup")
    expect(T(page, "auth-error")).to_have_count(0)
    T(page, "signup-email").fill("Grace.H@example.com")
    T(page, "signup-password").fill("long enough pw")
    T(page, "signup-display-name").fill("Grace Hopper")
    T(page, "signup-submit").click()
    expect(T(page, "current-user")).to_contain_text("Grace Hopper")
    expect(T(page, "current-handle")).to_have_text("grace_h")


def test_signup_refused_shows_auth_error(api, page):
    # ledger: 1032
    api.reset(ui_fixture())
    page.goto("/signup")
    T(page, "signup-email").fill("ada@example.com")
    T(page, "signup-password").fill("long enough pw")
    T(page, "signup-display-name").fill("Again")
    T(page, "signup-submit").click()
    expect(T(page, "auth-error")).to_be_visible()
    assert T(page, "auth-error").inner_text().strip()


def test_login_error_then_success(api, page):
    # ledger: 1031, 1032
    api.reset(ui_fixture())
    page.goto("/login")
    expect(T(page, "auth-error")).to_have_count(0)
    T(page, "login-email").fill("ada@example.com")
    T(page, "login-password").fill("wrong password")
    T(page, "login-submit").click()
    expect(T(page, "auth-error")).to_be_visible()
    T(page, "login-password").fill(PASSWORD)
    T(page, "login-submit").click()
    expect(T(page, "current-user")).to_contain_text("Ada")
    expect(T(page, "auth-error")).to_have_count(0)


def test_identity_on_every_screen_and_logout(api, page):
    # ledger: 1033, 1034, 1035, 1006, 1027
    api.reset(ui_fixture())
    login(page)
    for path in ["/", "/requests", "/split", "/authorizations"]:
        page.goto(path)
        expect(T(page, "current-user")).to_contain_text("Ada")
        expect(T(page, "current-handle")).to_have_text("ada")
        expect(T(page, "logout-button")).to_be_visible()
    T(page, "logout-button").click()
    expect(T(page, "current-user")).to_have_count(0)
    page.goto("/")
    expect(T(page, "current-user")).to_have_count(0)


# ---------------------------------------------------------------- wallet

@pytest.mark.parametrize("cur,mu,bal,text", [("EUR", 2, 10000, "100.00 EUR"), ("JPY", 0, 1200, "1200 JPY"),
                                             ("BHD", 3, 1234567, "1234.567 BHD"), ("EUR", 2, 5, "0.05 EUR")])
def test_wallet_balance_formatting(api, page, cur, mu, bal, text):
    # ledger: 1036, 1047, 1048, 1049, 1205
    fx = ui_fixture(currency=cur, minor_units=mu, authorizations=[])
    fx["users"][0]["balance"] = bal
    api.reset(fx)
    login(page)
    expect(T(page, "wallet-balance")).to_have_text(text)
    assert amount_of(T(page, "wallet-balance")) == bal


def test_wallet_available_headline_and_held(api, page, browser):
    # ledger: 1205, 1206, 1207, 1220, 1221, 1019
    api.reset(ui_fixture())
    login(page)
    expect(T(page, "wallet-available")).to_have_text("80.00 EUR")
    assert amount_of(T(page, "wallet-available")) == 8000
    expect(T(page, "wallet-held")).to_have_text("20.00 EUR")
    assert amount_of(T(page, "wallet-held")) == 2000
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    # headline: available is rendered larger than total and held
    size = lambda t: float(T(page, t).evaluate("e => parseFloat(getComputedStyle(e).fontSize)"))
    assert size("wallet-available") > size("wallet-balance") and size("wallet-available") > size("wallet-held")
    shot(page, "wallet-with-hold-desktop")
    # no holds -> wallet-held absent
    page2 = browser.new_context(base_url=api.base).new_page()
    login(page2, "bob@example.com")
    expect(T(page2, "wallet-held")).to_have_count(0)
    expect(T(page2, "wallet-available")).to_have_text("25.00 EUR")


# ---------------------------------------------------------------- pay form

def fill_pay(page, handle, amount, note="", vis="public"):
    T(page, "pay-handle").fill(handle)
    T(page, "pay-amount").fill(amount)
    T(page, "pay-note").fill(note)
    T(page, "pay-visibility").select_option(vis)


def test_pay_flow_keep_values_no_double_send(api, page):
    # ledger: 1037, 1038, 1039, 1043, 1044, 1046, 1050, 1051, 1077, 1054, 1055, 1056, 1057, 1058
    api.reset(ui_fixture(authorizations=[]))
    login(page)
    sent = posts(page, "/payments")
    opts = T(page, "pay-visibility").evaluate("s => Array.from(s.options).map(o => o.value)")
    assert sorted(opts) == ["private", "public"]
    fill_pay(page, "bob", "15", "dinner 🍝", "private")
    T(page, "pay-submit").click()
    expect(T(page, "wallet-balance")).to_have_text("85.00 EUR")
    assert sent[0][1]["amount"] == 1500 and sent[0][1]["to_handle"] == "bob"
    pid = api.session("bob@example.com").get("/activity").json["payments"][0]["payment_id"]
    item = T(page, f"activity-item-{pid}")
    expect(item).to_have_attribute("data-visibility", "private")
    expect(T(page, f"activity-amount-{pid}")).to_have_text("15.00 EUR")
    expect(T(page, f"activity-note-{pid}")).to_have_text("dinner 🍝")
    parties = T(page, f"activity-parties-{pid}").inner_text()
    assert "ada" in parties and "bob" in parties
    # values kept
    expect(T(page, "pay-handle")).to_have_value("bob")
    expect(T(page, "pay-amount")).to_have_value("15")
    expect(T(page, "pay-note")).to_have_value("dinner 🍝")
    expect(T(page, "pay-visibility")).to_have_value("private")
    # unchanged resubmit: no second payment
    T(page, "pay-submit").click()
    page.wait_for_timeout(1200)
    expect(T(page, "wallet-balance")).to_have_text("85.00 EUR")
    expect(T(page, "pay-error")).to_have_count(0)
    assert api.session("ada@example.com").balance() == 8500
    assert len([p for p in api.session("ada@example.com").get("/activity").json["payments"] if p["amount"] == 1500]) == 1
    if len(sent) > 1:
        assert sent[1][0].get("idempotency-key") == sent[0][0].get("idempotency-key")


@pytest.mark.parametrize("before,after", [("15", "15.00"), ("bob", "@bob"), ("bob", " bob ")])
def test_changed_field_is_new_payment(api, page, before, after):
    # ledger: 1045, 9010
    api.reset(ui_fixture(authorizations=[]))
    login(page)
    field = "pay-amount" if before[0].isdigit() else "pay-handle"
    fill_pay(page, "bob", "15")
    T(page, field).fill(before)
    T(page, "pay-submit").click()
    expect(T(page, "wallet-balance")).to_have_text("85.00 EUR")
    T(page, field).fill(after)
    T(page, "pay-submit").click()
    expect(T(page, "wallet-balance")).to_have_text("70.00 EUR")
    assert api.session("ada@example.com").balance() == 7000


def test_amount_parsing_rules(api, page):
    # ledger: 1050, 1051, 1052, 1053
    api.reset(ui_fixture(authorizations=[]))
    login(page)
    sent = posts(page, "/payments")
    for bad in ["15.005", "abc", "1,5", ""]:
        fill_pay(page, "bob", bad)
        T(page, "pay-submit").click()
        expect(T(page, "pay-error")).to_be_visible()
        page.wait_for_timeout(300)
    assert sent == [], sent
    fill_pay(page, "bob", "15.5")
    T(page, "pay-submit").click()
    expect(T(page, "wallet-balance")).to_have_text("84.50 EUR")
    assert sent[-1][1]["amount"] == 1550
    expect(T(page, "pay-error")).to_have_count(0)


def test_jpy_amount_input(api, page):
    # ledger: 1048, 1052
    api.reset(ui_fixture(currency="JPY", minor_units=0, authorizations=[]))
    login(page)
    sent = posts(page, "/payments")
    fill_pay(page, "bob", "15.5")
    T(page, "pay-submit").click()
    expect(T(page, "pay-error")).to_be_visible()
    assert sent == []
    fill_pay(page, "bob", "15")
    T(page, "pay-submit").click()
    expect(T(page, "wallet-balance")).to_have_text("9985 JPY")


def test_refused_payment_competing_client(api, page):
    # ledger: 1040, 1084, 1085, 1086
    api.reset(ui_fixture(authorizations=[]))
    login(page)
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    api.session("ada@example.com").pay("cy", 9000)  # spent elsewhere
    fill_pay(page, "bob", "50", "rent", "private")
    T(page, "pay-submit").click()
    expect(T(page, "pay-error")).to_be_visible()
    expect(T(page, "wallet-balance")).to_have_text("10.00 EUR")
    expect(T(page, "pay-handle")).to_have_value("bob")
    expect(T(page, "pay-amount")).to_have_value("50")
    expect(T(page, "pay-note")).to_have_value("rent")
    expect(T(page, "pay-visibility")).to_have_value("private")
    expect(T(page, "pay-uncertain")).to_have_count(0)


def test_request_form(api, page):
    # ledger: 1041, 1042
    api.reset(ui_fixture(authorizations=[]))
    login(page)
    T(page, "request-handle").fill("ghost")
    T(page, "request-amount").fill("5")
    T(page, "request-note").fill("x")
    T(page, "request-submit").click()
    expect(T(page, "request-error")).to_be_visible()
    T(page, "request-handle").fill("cy")
    T(page, "request-submit").click()
    expect(T(page, "request-error")).to_have_count(0)
    rq = api.session("cy@example.com").get("/requests", {"direction": "incoming"}).json["requests"]
    assert len(rq) == 1 and rq[0]["amount"] == 500


# ---------------------------------------------------------------- lost and uncertain responses

def _lose_first_post(page, path, mode):
    state = {"n": 0, "committed": None}
    def handler(route):
        state["n"] += 1
        if state["n"] == 1:
            if mode == "abort-after-commit":
                state["committed"] = route.fetch()
                route.abort("failed")
            elif mode == "empty-201":
                state["committed"] = route.fetch()
                route.fulfill(status=201, body="", headers={"content-type": "application/json"})
            elif mode == "null-201":
                state["committed"] = route.fetch()
                route.fulfill(status=201, body="null", headers={"content-type": "application/json"})
            elif mode == "500":
                route.fulfill(status=500, body='{"error":{"code":"x","message":"boom"}}',
                              headers={"content-type": "application/json"})
        else:
            route.continue_()
    page.route(re.compile(r".*/payments(\?.*)?$"), lambda route: handler(route)
               if route.request.method == "POST" else route.continue_())
    return state


@pytest.mark.parametrize("mode", ["abort-after-commit", "empty-201", "null-201", "500"])
def test_lost_response_uncertain_then_retry_once(api, page, mode):
    # ledger: 1088, 1089, 1090, 1091, 1092, 1046, 9009
    api.reset(ui_fixture(authorizations=[]))
    login(page)
    sent = posts(page, "/payments")
    _lose_first_post(page, "/payments", mode)
    fill_pay(page, "bob", "12.34", "lost?")
    T(page, "pay-submit").click()
    expect(T(page, "pay-uncertain")).to_be_visible()
    assert T(page, "pay-uncertain").inner_text().strip()
    expect(T(page, "pay-error")).to_have_count(0)
    T(page, "pay-submit").click()
    expect(T(page, "pay-uncertain")).to_have_count(0)
    expect(T(page, "pay-error")).to_have_count(0)
    expect(T(page, "wallet-balance")).to_have_text("87.66 EUR")
    assert api.session("ada@example.com").balance() == 8766
    assert len(sent) == 2 and sent[0][0]["idempotency-key"] == sent[1][0]["idempotency-key"]
    assert sent[0][1] == sent[1][1]
    pays = [p for p in api.session("bob@example.com").get("/activity").json["payments"] if p["amount"] == 1234]
    assert len(pays) == 1
    expect(T(page, f"activity-item-{pays[0]['payment_id']}")).to_have_count(1)


# ---------------------------------------------------------------- refresh: latest wins

def test_wallet_refresh_latest_wins_and_keeps_form(api, page):
    # ledger: 1081, 1082, 1083, 1094, 1080
    api.reset(ui_fixture())
    login(page)
    expect(T(page, "wallet-available")).to_have_text("80.00 EUR")
    fill_pay(page, "cy", "1.23", "draft")
    ada = api.session("ada@example.com")
    ada.pay("cy", 1000)
    stale_me = ada.me().json
    stale_feed = ada.get("/activity", {"limit": 200}).json
    held = []
    def hold_first(route):
        p = urlparse(route.request.url).path
        if route.request.method == "GET" and p in ("/me", "/activity") and len([h for h in held if h[0] == p]) == 0:
            held.append((p, route))
        else:
            route.continue_()
    page.route(re.compile(r".*/(me|activity)(\?.*)?$"), hold_first)
    T(page, "wallet-refresh").click()
    page.wait_for_timeout(500)
    ada.pay("cy", 1000)
    T(page, "wallet-refresh").click()
    expect(T(page, "wallet-balance")).to_have_text("80.00 EUR")
    expect(T(page, "wallet-available")).to_have_text("60.00 EUR")
    for p, route in held:  # the earlier, slower reads arrive last
        body = stale_me if p == "/me" else stale_feed
        route.fulfill(status=200, body=json.dumps(body), headers={"content-type": "application/json"})
    page.wait_for_timeout(1000)
    expect(T(page, "wallet-balance")).to_have_text("80.00 EUR")
    expect(T(page, "wallet-available")).to_have_text("60.00 EUR")
    assert len(page.locator("[data-testid^='activity-item-']").all()) == 3
    expect(T(page, "pay-handle")).to_have_value("cy")
    expect(T(page, "pay-amount")).to_have_value("1.23")
    expect(T(page, "pay-note")).to_have_value("draft")
    assert held, "no refresh request was observed on /me or /activity"


# ---------------------------------------------------------------- activity feed

def test_activity_order_empty_and_note(api, page):
    # ledger: 1054, 1058, 1059, 1060
    api.reset(ui_fixture(payments=[], requests=[], authorizations=[]))
    login(page)
    expect(T(page, "empty-activity")).to_be_visible()
    ada = api.session("ada@example.com")
    first = ada.pay("bob", 100).json["payment_id"]
    import time
    time.sleep(1.1)
    second = ada.pay("cy", 200, note="").json["payment_id"]
    T(page, "wallet-refresh").click()
    expect(T(page, f"activity-item-{second}")).to_be_visible()
    expect(T(page, "empty-activity")).to_have_count(0)
    ids = page.locator("[data-testid='activity-list'] [data-testid^='activity-item-']").evaluate_all(
        "els => els.map(e => e.getAttribute('data-testid'))")
    assert ids.index(f"activity-item-{second}") < ids.index(f"activity-item-{first}"), ids
    expect(T(page, f"activity-note-{second}")).to_have_count(1)
    expect(T(page, f"activity-note-{second}")).to_have_text("")


def test_activity_privacy_for_third_party(api, page):
    # ledger: 1055
    api.reset(ui_fixture(authorizations=[]))
    ada = api.session("ada@example.com")
    priv = ada.pay("bob", 100, visibility="private").json["payment_id"]
    pub = ada.pay("bob", 100).json["payment_id"]
    login(page, "cy@example.com")
    expect(T(page, f"activity-item-{pub}")).to_have_attribute("data-visibility", "public")
    expect(T(page, f"activity-item-{priv}")).to_have_count(0)


# ---------------------------------------------------------------- requests screen

def test_requests_screen(api, page):
    # ledger: 1061, 1062, 1063, 1064, 1065, 1066, 1077, 1009
    api.reset(ui_fixture(authorizations=[]))
    ada = api.session("ada@example.com")
    out = ada.request("cy", 250).json["request_id"]
    login(page, path="/requests")
    expect(T(page, "incoming-list")).to_be_visible()
    expect(T(page, "outgoing-list")).to_be_visible()
    expect(T(page, "incoming-list").get_by_test_id("request-item-rq_1")).to_have_attribute("data-status", "pending")
    expect(T(page, "request-amount-rq_1")).to_have_text("12.00 EUR")
    expect(T(page, "outgoing-list").get_by_test_id(f"request-item-{out}")).to_be_visible()
    expect(T(page, "request-pay-rq_1")).to_be_visible()
    expect(T(page, "request-decline-rq_1")).to_be_visible()
    expect(T(page, "request-cancel-rq_1")).to_have_count(0)
    expect(T(page, f"request-cancel-{out}")).to_be_visible()
    expect(T(page, f"request-pay-{out}")).to_have_count(0)
    expect(T(page, f"request-decline-{out}")).to_have_count(0)
    shot(page, "requests-desktop")
    T(page, "request-pay-rq_1").click()
    expect(T(page, "request-item-rq_1")).to_have_attribute("data-status", "paid")
    expect(T(page, "request-pay-rq_1")).to_have_count(0)
    expect(T(page, "request-decline-rq_1")).to_have_count(0)
    assert ada.balance() == 8800
    T(page, f"request-cancel-{out}").click()
    expect(T(page, f"request-item-{out}")).to_have_attribute("data-status", "cancelled")
    expect(T(page, f"request-cancel-{out}")).to_have_count(0)


def test_decline_from_screen(api, page):
    # ledger: 1065
    api.reset(ui_fixture(authorizations=[]))
    login(page, path="/requests")
    T(page, "request-decline-rq_1").click()
    expect(T(page, "request-item-rq_1")).to_have_attribute("data-status", "declined")
    assert api.session("bob@example.com").get("/requests").json["requests"][0]["status"] == "declined"


def test_stale_pay_button_refused(api, page):
    # ledger: 1067, 1087
    api.reset(ui_fixture(authorizations=[]))
    login(page, path="/requests")
    expect(T(page, "request-pay-rq_1")).to_be_visible()
    assert api.session("bob@example.com").post("/requests/rq_1/cancel").status == 200
    T(page, "request-pay-rq_1").click()
    expect(T(page, "request-error")).to_be_visible()
    expect(T(page, "request-pay-rq_1")).to_have_count(0)
    expect(T(page, "request-item-rq_1")).to_have_attribute("data-status", "cancelled")
    assert api.session("ada@example.com").balance() == 10000


def test_empty_requests(api, page):
    # ledger: 1068
    api.reset(ui_fixture(requests=[], authorizations=[]))
    login(page, "cy@example.com", path="/requests")
    expect(T(page, "empty-requests")).to_be_visible()


# ---------------------------------------------------------------- split screen

def test_split_preview_matches_server(api, page):
    # ledger: 1069, 1070, 1071, 1072, 1073, 1075, 1076
    api.reset(ui_fixture(authorizations=[]))
    login(page, path="/split")
    sent = posts(page, "/splits")
    T(page, "split-amount").fill("0.10")
    T(page, "split-handles").fill("bob, ada,cy")
    T(page, "split-note").fill("pizza")
    expect(T(page, "split-preview")).to_be_visible()
    expect(T(page, "split-share-bob")).to_have_text("0.04 EUR")
    expect(T(page, "split-share-ada")).to_have_text("0.03 EUR")
    expect(T(page, "split-share-cy")).to_have_text("0.03 EUR")
    assert sent == []
    T(page, "split-submit").click()
    page.wait_for_timeout(1500)
    assert len(sent) == 1 and sent[0][1]["amount"] == 10 and sent[0][1]["participant_handles"] == ["bob", "ada", "cy"]
    incoming = api.session("bob@example.com").get("/requests", {"direction": "incoming"}).json["requests"]
    assert incoming[0]["amount"] == 4 and incoming[0]["note"] == "pizza"
    expect(T(page, "split-error")).to_have_count(0)


def test_split_refused(api, page):
    # ledger: 1074
    api.reset(ui_fixture(authorizations=[]))
    login(page, path="/split")
    T(page, "split-amount").fill("10")
    T(page, "split-handles").fill("bob, ghost")
    T(page, "split-submit").click()
    expect(T(page, "split-error")).to_be_visible()


def test_split_bad_amount_not_sent(api, page):
    # ledger: 1069, 1052
    api.reset(ui_fixture(authorizations=[]))
    login(page, path="/split")
    sent = posts(page, "/splits")
    T(page, "split-amount").fill("1.005")
    T(page, "split-handles").fill("bob")
    T(page, "split-submit").click()
    expect(T(page, "split-error")).to_be_visible()
    assert sent == []


# ---------------------------------------------------------------- authorizations screen

def test_authorizations_screen(api, page, browser):
    # ledger: 1203, 1210, 1211, 1212, 1213, 1214, 1215, 1216, 1217, 1218, 1220
    api.reset(ui_fixture())
    ada = api.session("ada@example.com")
    a2 = ada.post("/authorizations", {"to_handle": "cy", "amount": 300}, idem=key()).json
    login(page, "bob@example.com", path="/authorizations")
    expect(T(page, "authorization-item-a_1")).to_have_attribute("data-status", "open")
    expect(T(page, "authorization-amount-a_1")).to_have_text("20.00 EUR")
    exp = api.session("bob@example.com").get("/authorizations").json["authorizations"][0]["expires_at"]
    expect(T(page, "authorization-expires-a_1")).to_have_text(exp)
    expect(T(page, "authorization-captured-a_1")).to_have_count(0)
    expect(T(page, "authorization-void-a_1")).to_have_count(0)
    val = T(page, "authorization-capture-amount-a_1").input_value()
    assert re.fullmatch(r"20(\.0{1,2})?", val), val
    shot(page, "authorizations-desktop")
    T(page, "authorization-capture-amount-a_1").fill("15")
    T(page, "authorization-capture-a_1").click()
    expect(T(page, "authorization-item-a_1")).to_have_attribute("data-status", "captured")
    expect(T(page, "authorization-captured-a_1")).to_have_text("15.00 EUR")
    expect(T(page, "authorization-capture-a_1")).to_have_count(0)
    assert api.session("bob@example.com").balance() == 4000
    assert api.session("ada@example.com").me().json["held"] == 300
    # payer side: void button only on outgoing open
    page2 = browser.new_context(base_url=api.base).new_page()
    login(page2, "ada@example.com", path="/authorizations")
    aid = a2["authorization_id"]
    ids = page2.locator("[data-testid='authorization-list'] [data-testid^='authorization-item-']").evaluate_all(
        "els => els.map(e => e.getAttribute('data-testid'))")
    assert ids[0] == f"authorization-item-{aid}", ids
    expect(T(page2, f"authorization-capture-{aid}")).to_have_count(0)
    T(page2, f"authorization-void-{aid}").click()
    expect(T(page2, f"authorization-item-{aid}")).to_have_attribute("data-status", "voided")
    expect(T(page2, f"authorization-void-{aid}")).to_have_count(0)
    assert api.session("ada@example.com").me().json["held"] == 0


def test_authorization_error_when_refused(api, page):
    # ledger: 1218
    api.reset(ui_fixture())
    login(page, "bob@example.com", path="/authorizations")
    expect(T(page, "authorization-capture-a_1")).to_be_visible()
    assert api.session("ada@example.com").post("/authorizations/a_1/void").status == 200
    T(page, "authorization-capture-a_1").click()
    expect(T(page, "authorization-error")).to_be_visible()


def test_empty_authorizations(api, page):
    # ledger: 1219
    api.reset(ui_fixture())
    login(page, "dee@example.com", path="/authorizations")
    expect(T(page, "empty-authorizations")).to_be_visible()


def test_authorize_form_and_error(api, page):
    # ledger: 1208, 1209, 1220 (D-11: form on / and /authorizations)
    api.reset(ui_fixture())
    login(page, path="/authorizations")
    expect(T(page, "authorize-submit")).to_be_visible()
    page.goto("/")
    expect(T(page, "authorize-submit")).to_be_visible()
    T(page, "authorize-handle").fill("cy")
    T(page, "authorize-amount").fill("90")
    T(page, "authorize-note").fill("too much")
    T(page, "authorize-visibility").select_option("private")
    T(page, "authorize-submit").click()
    expect(T(page, "authorize-error")).to_be_visible()
    T(page, "authorize-amount").fill("30")
    T(page, "authorize-submit").click()
    expect(T(page, "wallet-held")).to_have_text("50.00 EUR")
    expect(T(page, "wallet-available")).to_have_text("50.00 EUR")
    expect(T(page, "authorize-error")).to_have_count(0)


# ---------------------------------------------------------------- upgrade from a stage-1 export

def test_upgrade_keeps_browser_session_and_retry(api, page):
    # ledger: 1096, 1097, 1098, 1101
    s1 = os.environ.get("PF_STAGE1_URL")
    if not s1:
        pytest.skip("no stage-1 instance (run_checks starts one in --repo mode)")
    old = Api(s1)
    fx = base_fixture()
    old.reset(fx)
    api.reset(ui_fixture(authorizations=[]))
    backend = {"url": s1}

    def via_backend(route):
        r = route.request
        if r.resource_type in ("fetch", "xhr") and backend["url"]:
            u = urlparse(r.url)
            route.continue_(url=backend["url"] + u.path + (f"?{u.query}" if u.query else ""))
        else:
            route.continue_()
    page.route("**/*", via_backend)
    login(page)
    expect(T(page, "wallet-balance")).to_have_text("100.00 EUR")
    sent = posts(page, "/payments")
    lost = {"n": 0}
    def lose(route):
        if route.request.method == "POST" and lost["n"] == 0:
            lost["n"] += 1
            u = urlparse(route.request.url)
            route.fetch(url=backend["url"] + u.path)
            route.abort("failed")
        else:
            route.fallback()
    page.route(re.compile(r".*/payments$"), lose)
    fill_pay(page, "bob", "7.50", "upgrade")
    T(page, "pay-submit").click()
    expect(T(page, "pay-uncertain")).to_be_visible()
    snap = old.req("GET", "/_test/export").json
    old.close()
    assert api.req("POST", "/_test/import", body=snap).status == 204
    backend["url"] = None  # the stage-2 service now answers at the same origin
    T(page, "pay-submit").click()
    expect(T(page, "pay-uncertain")).to_have_count(0)
    expect(T(page, "pay-error")).to_have_count(0)
    expect(T(page, "wallet-balance")).to_have_text("92.50 EUR")
    expect(T(page, "current-user")).to_contain_text("Ada")
    assert api.session("ada@example.com").balance() == 9250
    assert len(sent) >= 2 and sent[0][0]["idempotency-key"] == sent[-1][0]["idempotency-key"]
    page.goto("/requests")
    expect(T(page, "current-user")).to_contain_text("Ada")
    T(page, "request-pay-rq_1").click()
    expect(T(page, "request-item-rq_1")).to_have_attribute("data-status", "paid")


# ---------------------------------------------------------------- responsive and accessible

@pytest.mark.parametrize("width", [375, 1280])
def test_no_horizontal_scroll_and_labels(api, browser, width):
    # ledger: 1025, 1026, 1016
    api.reset(ui_fixture())
    ctx = browser.new_context(viewport={"width": width, "height": 900}, base_url=api.base)
    page = ctx.new_page()
    try:
        for path in ["/login", "/signup"]:
            page.goto(path)
            page.wait_for_timeout(300)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (path, width)
            shot(page, f"{path.strip('/') or 'home'}-{width}")
        login(page)
        for path in ["/", "/requests", "/split", "/authorizations"]:
            page.goto(path)
            expect(T(page, "current-user")).to_be_visible()
            page.wait_for_timeout(300)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (path, width)
            shot(page, f"{path.strip('/') or 'home'}-{width}")
            unlabeled = page.evaluate("""() => Array.from(document.querySelectorAll('input[data-testid], select[data-testid]'))
                .filter(e => e.type !== 'hidden' && e.offsetParent !== null)
                .filter(e => !(e.labels && e.labels.length) && !e.getAttribute('aria-labelledby'))
                .map(e => e.getAttribute('data-testid'))""")
            assert unlabeled == [], (path, unlabeled)
    finally:
        ctx.close()
