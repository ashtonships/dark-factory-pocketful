/*
 * Browser drill for the W-6 screens against ui-core/devstub.py.
 *   python3 ui-core/devstub.py --port <p> &
 *   NODE_PATH=<dir with playwright-core> node ui-core/browser-drill.js http://127.0.0.1:<p> [shots-dir]
 * Drives the system Chrome; checks every stage-2 behaviour W-6 covers, at a
 * desktop width and at 375 CSS px. Dev tooling only, not part of any stage.
 */
"use strict";
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const BASE = process.argv[2] || "http://127.0.0.1:8080";
const SHOTS = process.argv[3] || null;
// DRILL_SCALE stretches every wait and fixed pause on a loaded host (default 1).
const S = Number(process.env.DRILL_SCALE || 1);
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

let passed = 0, failed = 0;
function check(name, cond, detail) {
  if (cond) { passed++; console.log("PASS " + name); }
  else { failed++; console.log("FAIL " + name + (detail !== undefined ? " -- " + JSON.stringify(detail) : "")); }
}

async function call(method, p, body, token, key) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  if (key) headers["Idempotency-Key"] = key;
  const res = await fetch(BASE + p, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  return { status: res.status, data: text ? JSON.parse(text) : null };
}
const login = async (email) => (await call("POST", "/auth/login", { email, password: "correct horse" })).data.token;
const faults = (rules) => call("POST", "/_dev/faults", { rules });

function fixture() {
  const later = new Date(Date.now() + 2 * 3600e3).toISOString().replace(/\.\d+Z$/, "+00:00");
  return {
    currency: "EUR", minor_units: 2,
    users: [
      { id: "u_ada", email: "ada@example.com", password: "correct horse", display_name: "Ada Lovelace", handle: "ada", balance: 10000 },
      { id: "u_bob", email: "bob@example.com", password: "correct horse", display_name: "Bob", handle: "bob", balance: 2500 },
      { id: "u_cy", email: "cy@example.com", password: "correct horse", display_name: "Cy", handle: "cy", balance: 0 }
    ],
    payments: [
      { id: "p_1", from_user_id: "u_ada", to_user_id: "u_bob", amount: 500, note: "coffee ☕", visibility: "public" },
      { id: "p_2", from_user_id: "u_bob", to_user_id: "u_cy", amount: 100, note: "secret", visibility: "private" }
    ],
    requests: [
      { id: "rq_1", requester_id: "u_bob", payer_id: "u_ada", amount: 1200, note: "taxi", status: "pending" },
      { id: "rq_2", requester_id: "u_ada", payer_id: "u_bob", amount: 300, note: "snacks", status: "pending" }
    ],
    authorizations: [
      { id: "a_1", from_user_id: "u_ada", to_user_id: "u_bob", amount: 2000, note: "deposit", visibility: "public", status: "open", expires_at: later }
    ]
  };
}

const T = (id) => `[data-testid="${id}"]`;
async function text(page, id) { return (await page.locator(T(id)).textContent()).trim(); }
async function count(page, id) { return page.locator(T(id)).count(); }
async function attr(page, id, a) { return page.locator(T(id)).getAttribute(a); }
async function waitText(page, id, expected, timeout = 4000 * S) {
  try { await page.waitForFunction(([s, e]) => { const el = document.querySelector(s); return el && el.textContent.trim() === e; }, [T(id), expected], { timeout }); return true; }
  catch (e) { return false; }
}
async function waitGone(page, id, timeout = 4000 * S) {
  try { await page.locator(T(id)).waitFor({ state: "detached", timeout }); return true; } catch (e) { return false; }
}
async function waitPresent(page, id, timeout = 4000 * S) {
  try { await page.locator(T(id)).first().waitFor({ state: "attached", timeout }); return true; } catch (e) { return false; }
}
async function signIn(page, email) {
  await page.goto(BASE + "/login");
  await page.fill(T("login-email"), email);
  await page.fill(T("login-password"), "correct horse");
  await page.click(T("login-submit"));
  await page.waitForURL(BASE + "/");
  await waitPresent(page, "wallet-available");
}
// Design rule 4: wallet-available is the largest money figure on the page.
async function availableIsLargest(page) {
  return page.evaluate(() => {
    const hero = document.querySelector('[data-testid="wallet-available"]');
    if (!hero) return { ok: false, why: "no wallet-available" };
    const size = (el) => parseFloat(getComputedStyle(el).fontSize);
    const others = Array.from(document.querySelectorAll('[data-testid="wallet-balance"], [data-testid="wallet-held"], .amount, .hold-amount, [data-testid^="split-share-"]'))
      .filter((el) => el !== hero);
    const max = Math.max(0, ...others.map(size));
    return { ok: size(hero) > max, hero: size(hero), max };
  });
}
async function noHorizontalScroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
}

let browser;
async function newCtx(opts) {
  const c = await browser.newContext(opts);
  c.setDefaultTimeout(10000 * S);
  return c;
}
async function run() {
  browser = await chromium.launch({ executablePath: CHROME, headless: true });
  await call("POST", "/_test/reset", fixture());
  await faults([]);

  // ------------------------------------------------------------- auth --
  const ctx = await newCtx({ viewport: { width: 1280, height: 900 } });
  ctx.setDefaultTimeout(10000 * S);
  const page = await ctx.newPage();
  const posts = [];
  page.on("request", (r) => { if (r.method() === "POST") posts.push(r.url().replace(BASE, "")); });

  await page.goto(BASE + "/");
  await page.waitForURL(BASE + "/login");
  check("signed-out / redirects to /login", page.url() === BASE + "/login");
  check("auth-error absent before any attempt", (await count(page, "auth-error")) === 0);
  await page.fill(T("login-email"), "ada@example.com");
  await page.fill(T("login-password"), "wrong password");
  await page.click(T("login-submit"));
  check("wrong password shows auth-error", await waitPresent(page, "auth-error"));
  await signIn(page, "ada@example.com");
  check("current-user contains the display name", (await text(page, "current-user")).includes("Ada Lovelace"));
  check("current-handle is exactly the handle", (await text(page, "current-handle")) === "ada");

  // ----------------------------------------------------------- wallet --
  check("wallet-available is 80.00 EUR (headline)", (await text(page, "wallet-available")) === "80.00 EUR", await text(page, "wallet-available"));
  check("wallet-available data-amount", (await attr(page, "wallet-available", "data-amount")) === "8000");
  check("wallet-balance is total 100.00 EUR", (await text(page, "wallet-balance")) === "100.00 EUR");
  check("wallet-balance data-amount", (await attr(page, "wallet-balance", "data-amount")) === "10000");
  check("wallet-held 20.00 EUR with data-amount", (await text(page, "wallet-held")) === "20.00 EUR" && (await attr(page, "wallet-held", "data-amount")) === "2000");
  const heroSize = await page.evaluate(() => {
    const px = (s) => parseFloat(getComputedStyle(document.querySelector(s)).fontSize);
    return [px('[data-testid="wallet-available"]'), px('[data-testid="wallet-balance"]'), px('[data-testid="wallet-held"]')];
  });
  check("available is visibly the largest amount", heroSize[0] > heroSize[1] && heroSize[0] > heroSize[2], heroSize);
  { const r = await availableIsLargest(page); check("/: available is the largest money figure", r.ok, r); }

  // ------------------------------------------------------------- feed --
  check("feed shows public p_1 with visibility", (await attr(page, "activity-item-p_1", "data-visibility")) === "public");
  check("feed hides third-party private p_2", (await count(page, "activity-item-p_2")) === 0);
  check("activity-parties contains both handles", /ada/.test(await text(page, "activity-parties-p_1")) && /bob/.test(await text(page, "activity-parties-p_1")));
  check("activity-amount exact", (await text(page, "activity-amount-p_1")) === "5.00 EUR");
  check("activity-note exact (unicode)", (await page.locator(T("activity-note-p_1")).textContent()) === "coffee ☕");
  check("empty-activity absent when items exist", (await count(page, "empty-activity")) === 0);

  // -------------------------------------------------------------- pay --
  await page.fill(T("pay-handle"), "bob");
  await page.fill(T("pay-amount"), "15.00");
  await page.fill(T("pay-note"), "");
  await page.selectOption(T("pay-visibility"), "private");
  await page.click(T("pay-submit"));
  check("pay success refreshes total to 85.00 EUR", await waitText(page, "wallet-balance", "85.00 EUR"));
  const firstItems = await page.locator('[data-testid="activity-list"] > li').count();
  const newestId = await page.locator('[data-testid="activity-list"] > li').first().getAttribute("data-testid");
  check("new private payment is first in the feed", (await page.locator(T(newestId)).getAttribute("data-visibility")) === "private");
  check("its empty note element is present", (await page.locator(T(newestId.replace("item", "note"))).count()) === 1);
  check("pay form keeps values after success",
    (await page.inputValue(T("pay-handle"))) === "bob" && (await page.inputValue(T("pay-amount"))) === "15.00" && (await page.inputValue(T("pay-visibility"))) === "private");
  await page.click(T("pay-submit"));
  await page.waitForTimeout(600 * S);
  check("unchanged resubmit: balance falls once", (await text(page, "wallet-balance")) === "85.00 EUR");
  check("unchanged resubmit: feed has one payment", (await page.locator('[data-testid="activity-list"] > li').count()) === firstItems);
  check("unchanged resubmit: pay-error absent", (await count(page, "pay-error")) === 0);
  await page.fill(T("pay-note"), "second");
  await page.click(T("pay-submit"));
  check("changed field is a new payment", await waitText(page, "wallet-balance", "70.00 EUR"));

  // local validation
  const before = posts.length;
  await page.fill(T("pay-amount"), "15.005");
  await page.click(T("pay-submit"));
  check("15.005 shows pay-error", await waitPresent(page, "pay-error"));
  await page.fill(T("pay-amount"), "abc");
  await page.click(T("pay-submit"));
  await page.waitForTimeout(200 * S);
  check("invalid amounts send no request", posts.length === before, posts.slice(before));

  // refusal with competing client: bob pays ada 1.00 behind the page's back
  const bobTok = await login("bob@example.com");
  await call("POST", "/payments", { to_handle: "ada", amount: 100 }, bobTok, "k-ext-1");
  await page.fill(T("pay-handle"), "bob");
  await page.fill(T("pay-amount"), "999.00");
  await page.fill(T("pay-note"), "too much");
  await page.click(T("pay-submit"));
  check("insufficient funds shows pay-error", await waitPresent(page, "pay-error"));
  check("refusal refreshes the balance (71.00 EUR)", await waitText(page, "wallet-balance", "71.00 EUR"));
  check("refusal keeps all pay inputs",
    (await page.inputValue(T("pay-handle"))) === "bob" && (await page.inputValue(T("pay-amount"))) === "999.00" && (await page.inputValue(T("pay-note"))) === "too much");
  check("pay-uncertain absent on a refusal", (await count(page, "pay-uncertain")) === 0);

  // lost response after commit
  await faults([{ method: "POST", path: "/payments", action: "drop_after_commit", times: 1 }]);
  await page.fill(T("pay-amount"), "2.00");
  await page.fill(T("pay-note"), "lost");
  await page.click(T("pay-submit"));
  check("lost response shows pay-uncertain", await waitPresent(page, "pay-uncertain"));
  check("pay-uncertain has text", (await text(page, "pay-uncertain")).length > 0);
  check("pay-uncertain uses the picked copy", (await text(page, "pay-uncertain")).includes("Payment result unknown. Retry with the same details."), await text(page, "pay-uncertain"));
  check("pay-error absent while uncertain", (await count(page, "pay-error")) === 0);
  await page.click(T("pay-submit"));
  check("retry clears pay-uncertain", await waitGone(page, "pay-uncertain"));
  check("retry: pay-error absent", (await count(page, "pay-error")) === 0);
  check("retry refreshes; money moved once (69.00 EUR)", await waitText(page, "wallet-balance", "69.00 EUR"));
  const lostItems = await page.locator('[data-testid="activity-list"] li:has([data-testid^="activity-note-"]:text-is("lost"))').count();
  check("feed holds exactly one 'lost' payment", lostItems === 1, lostItems);

  // PF-A1: committed 201 whose body is empty / null / not the payment
  for (const bad of ["", "null", "{}"]) {
    const was = Number(await attr(page, "wallet-balance", "data-amount"));
    await faults([{ method: "POST", path: "/payments", action: "replace_body", body: bad, times: 1 }]);
    await page.fill(T("pay-amount"), "0.50");
    await page.fill(T("pay-note"), "body " + JSON.stringify(bad));
    await page.click(T("pay-submit"));
    check("201 with body " + JSON.stringify(bad) + ": pay-uncertain, no pay-error", await waitPresent(page, "pay-uncertain") && (await count(page, "pay-error")) === 0);
    check("201 with body " + JSON.stringify(bad) + ": inputs kept", (await page.inputValue(T("pay-amount"))) === "0.50" && (await page.inputValue(T("pay-handle"))) === "bob");
    await page.click(T("pay-submit"));
    check("201 with body " + JSON.stringify(bad) + ": retry clears, money moved once",
      await waitGone(page, "pay-uncertain") && await waitText(page, "wallet-balance", P2(was - 50)) && (await count(page, "pay-error")) === 0);
  }

  // PF-A2: raw edits are new intents even when they normalise the same
  {
    const was = Number(await attr(page, "wallet-balance", "data-amount"));
    await page.fill(T("pay-handle"), "bob");
    await page.fill(T("pay-note"), "raw");
    await page.fill(T("pay-amount"), "1");
    await page.click(T("pay-submit"));
    check("PF-A2 '1' pays", await waitText(page, "wallet-balance", P2(was - 100)));
    await page.fill(T("pay-amount"), "1.00");
    await page.click(T("pay-submit"));
    check("PF-A2 '1' -> '1.00' is a second payment", await waitText(page, "wallet-balance", P2(was - 200)));
    await page.fill(T("pay-handle"), "@bob");
    await page.click(T("pay-submit"));
    check("PF-A2 'bob' -> '@bob' is a third payment", await waitText(page, "wallet-balance", P2(was - 300)));
    await page.click(T("pay-submit"));
    await page.waitForTimeout(500 * S);
    check("PF-A2 unchanged resubmit still replays", (await text(page, "wallet-balance")) === P2(was - 300));
    await page.fill(T("pay-note"), "lost");
    await page.fill(T("pay-amount"), "2.00");
    await page.fill(T("pay-handle"), "bob");
  }

  // latest refresh wins with out-of-order responses
  const beforeRace = Number(await attr(page, "wallet-balance", "data-amount"));
  await faults([{ method: "GET", path: "/me", action: "delay", ms: 1500 * S, times: 1 }]);
  await page.click(T("wallet-refresh"));          // slow, will carry the old balance
  await page.waitForTimeout(150 * S);
  await call("POST", "/payments", { to_handle: "ada", amount: 1000 }, bobTok, "k-ext-2");
  await page.click(T("wallet-refresh"));          // fast, carries old + 10.00
  check("later refresh shows the new balance", await waitText(page, "wallet-balance", P2(beforeRace + 1000)));
  await page.waitForTimeout(1800 * S);
  check("delayed earlier refresh does not overwrite", (await text(page, "wallet-balance")) === P2(beforeRace + 1000), await text(page, "wallet-balance"));
  check("refresh keeps the pay form", (await page.inputValue(T("pay-note"))) === "lost");

  // request form
  await page.fill(T("request-handle"), "cy");
  await page.fill(T("request-amount"), "3");
  await page.fill(T("request-note"), "lunch");
  await page.click(T("request-submit"));
  await page.waitForTimeout(400 * S);
  check("request form: no request-error on success", (await count(page, "request-error")) === 0);
  await page.fill(T("request-handle"), "nobody_here");
  await page.fill(T("request-amount"), "3");
  await page.click(T("request-submit"));
  check("request to unknown handle shows request-error", await waitPresent(page, "request-error"));
  // authorize form on / (D-11)
  const availHome = Number(await attr(page, "wallet-available", "data-amount"));
  const totalHome = await attr(page, "wallet-balance", "data-amount");
  await page.fill(T("authorize-handle"), "cy");
  await page.fill(T("authorize-amount"), "1.005");
  await page.click(T("authorize-submit"));
  check("/ authorize: 1.005 shows authorize-error", await waitPresent(page, "authorize-error"));
  await page.fill(T("authorize-amount"), "2.5");
  await page.fill(T("authorize-note"), "home hold");
  await page.selectOption(T("authorize-visibility"), "private");
  await page.click(T("authorize-submit"));
  check("/ authorize: available refreshes down by 2.50", await page.waitForFunction(([s, v]) => document.querySelector(s)?.getAttribute("data-amount") === v, [T("wallet-available"), String(availHome - 250)], { timeout: 4000 * S }).then(() => true, () => false));
  check("/ authorize: total unchanged, held shown", (await attr(page, "wallet-balance", "data-amount")) === totalHome && (await count(page, "wallet-held")) === 1);
  check("/ authorize: authorize-error cleared", (await count(page, "authorize-error")) === 0);
  await page.click(T("authorize-submit"));
  await page.waitForTimeout(500 * S);
  check("/ authorize: unchanged resubmit holds once", (await attr(page, "wallet-available", "data-amount")) === String(availHome - 250));
  await page.fill(T("authorize-amount"), "99999");
  await page.click(T("authorize-submit"));
  check("/ authorize beyond available: authorize-error", await waitPresent(page, "authorize-error"));
  const homeAuth = (await call("GET", "/authorizations?direction=outgoing&status=open", undefined, await login("ada@example.com"))).data.authorizations.find((a) => a.note === "home hold");
  check("/ authorize created a private 2.50 hold for cy", !!homeAuth && homeAuth.amount === 250 && homeAuth.visibility === "private" && homeAuth.to_handle === "cy");
  await call("POST", "/authorizations/" + homeAuth.authorization_id + "/void", {}, await login("ada@example.com"));
  await page.click(T("wallet-refresh"));
  await waitText(page, "wallet-available", (availHome / 100).toFixed(2) + " EUR");
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "desktop-wallet.png"), fullPage: true });
  check("desktop /: no horizontal scroll", await noHorizontalScroll(page));

  // --------------------------------------------------------- requests --
  await page.goto(BASE + "/requests");
  await waitPresent(page, "request-item-rq_1");
  check("incoming rq_1 pending with pay and decline", (await attr(page, "request-item-rq_1", "data-status")) === "pending"
    && (await count(page, "request-pay-rq_1")) === 1 && (await count(page, "request-decline-rq_1")) === 1 && (await count(page, "request-cancel-rq_1")) === 0);
  check("rq_1 sits in incoming-list", (await page.locator(T("incoming-list") + " " + T("request-item-rq_1")).count()) === 1);
  check("outgoing rq_2 has cancel only", (await count(page, "request-cancel-rq_2")) === 1 && (await count(page, "request-pay-rq_2")) === 0);
  check("request-amount exact", (await text(page, "request-amount-rq_1")) === "12.00 EUR");
  check("empty-requests absent with requests", (await count(page, "empty-requests")) === 0);
  // stale pay button: bob cancels rq_1 elsewhere
  await call("POST", "/requests/rq_1/cancel", {}, bobTok);
  await page.click(T("request-pay-rq_1"));
  check("paying a cancelled request shows request-error", await waitPresent(page, "request-error"));
  check("stale pay button disappears", await waitGone(page, "request-pay-rq_1"));
  check("rq_1 now shows cancelled", (await attr(page, "request-item-rq_1", "data-status")) === "cancelled");
  // fresh request from bob, paid privately from the page
  const rq3 = (await call("POST", "/requests", { payer_handle: "ada", amount: 250, note: "bus" }, bobTok, "k-rq3")).data.request_id;
  await page.reload();
  await waitPresent(page, "request-pay-" + rq3);
  await page.selectOption(T("request-visibility-" + rq3), "private");
  await page.click(T("request-pay-" + rq3));
  check("paying a request marks it paid", await page.waitForFunction((s) => document.querySelector(s)?.getAttribute("data-status") === "paid", T("request-item-" + rq3), { timeout: 4000 * S }).then(() => true, () => false));
  check("paid request has no buttons", (await count(page, "request-pay-" + rq3)) === 0 && (await count(page, "request-decline-" + rq3)) === 0);
  const rq4 = (await call("POST", "/requests", { payer_handle: "ada", amount: 99999, note: "rent" }, bobTok, "k-rq4")).data.request_id;
  await page.reload();
  await waitPresent(page, "request-pay-" + rq4);
  await page.click(T("request-pay-" + rq4));
  check("request larger than balance: request-error", await waitPresent(page, "request-error"));
  check("short request stays pending and payable", (await attr(page, "request-item-" + rq4, "data-status")) === "pending" && (await count(page, "request-pay-" + rq4)) === 1);
  await page.click(T("request-decline-" + rq4));
  check("decline marks it declined", await page.waitForFunction((s) => document.querySelector(s)?.getAttribute("data-status") === "declined", T("request-item-" + rq4), { timeout: 4000 * S }).then(() => true, () => false));
  check("request-error cleared after a success", (await count(page, "request-error")) === 0);
  await page.click(T("request-cancel-rq_2"));
  check("cancel marks rq_2 cancelled", await page.waitForFunction((s) => document.querySelector(s)?.getAttribute("data-status") === "cancelled", T("request-item-rq_2"), { timeout: 4000 * S }).then(() => true, () => false));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "desktop-requests.png"), fullPage: true });

  // ------------------------------------------------------------ split --
  await page.goto(BASE + "/split");
  await page.fill(T("split-amount"), "0.10");
  await page.fill(T("split-handles"), "bob, ada,cy");
  check("preview before posting: bob 0.04", await waitText(page, "split-share-bob", "0.04 EUR"));
  check("preview: ada 0.03, cy 0.03", (await text(page, "split-share-ada")) === "0.03 EUR" && (await text(page, "split-share-cy")) === "0.03 EUR");
  check("preview sends nothing", !posts.some((p) => p === "/splits"));
  await page.fill(T("split-note"), "pizza");
  await page.click(T("split-submit"));
  await page.waitForTimeout(500 * S);
  check("split succeeded without split-error", (await count(page, "split-error")) === 0);
  const ada = await login("ada@example.com");
  const outgoing = (await call("GET", "/requests?direction=outgoing", undefined, ada)).data.requests.filter((r) => r.note === "pizza");
  check("split created requests for bob 4 and cy 3", outgoing.length === 2
    && outgoing.find((r) => r.payer_handle === "bob").amount === 4 && outgoing.find((r) => r.payer_handle === "cy").amount === 3);
  await page.fill(T("split-amount"), "1");
  await page.fill(T("split-handles"), "bob,ghost");
  await page.click(T("split-submit"));
  check("split with unknown handle shows split-error", await waitPresent(page, "split-error"));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "desktop-split.png"), fullPage: true });

  // ------------------------------------------------------ authorizations --
  await page.goto(BASE + "/authorizations");
  await waitPresent(page, "authorization-item-a_1");
  check("seeded a_1 open, outgoing: void button, no capture", (await attr(page, "authorization-item-a_1", "data-status")) === "open"
    && (await count(page, "authorization-void-a_1")) === 1 && (await count(page, "authorization-capture-a_1")) === 0);
  check("authorization-amount exact", (await text(page, "authorization-amount-a_1")) === "20.00 EUR");
  check("authorization-expires is RFC 3339", /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?([+-]\d\d:\d\d|Z)$/.test(await text(page, "authorization-expires-a_1")));
  check("authorization-captured absent while open", (await count(page, "authorization-captured-a_1")) === 0);
  { const r = await availableIsLargest(page); check("/authorizations: available is the largest money figure", r.ok, r); }
  const avail0 = await attr(page, "wallet-available", "data-amount");
  await page.fill(T("authorize-handle"), "cy");
  await page.fill(T("authorize-amount"), "5");
  await page.fill(T("authorize-note"), "tickets");
  await page.click(T("authorize-submit"));
  {
    const lowered = await page.waitForFunction(([s, v]) => document.querySelector(s)?.getAttribute("data-amount") === v, [T("wallet-available"), String(Number(avail0) - 500)], { timeout: 4000 * S }).then(() => true, () => false);
    check("authorize lowers available by 5.00", lowered, lowered ? undefined : { avail0, now: await attr(page, "wallet-available", "data-amount"), messages: await page.locator("#authorize-messages").innerText() });
  }
  const newAuth = await page.locator('[data-testid="authorization-list"] > li').first().getAttribute("data-testid");
  const newAuthId = newAuth.replace("authorization-item-", "");
  check("new hold first in the list, open", (await attr(page, newAuth, "data-status")) === "open");
  await page.click(T("authorization-void-" + newAuthId));
  check("void marks it voided", await page.waitForFunction((s) => document.querySelector(s)?.getAttribute("data-status") === "voided", T(newAuth), { timeout: 4000 * S }).then(() => true, () => false));
  check("void restores available", await page.waitForFunction(([s, v]) => document.querySelector(s)?.getAttribute("data-amount") === v, [T("wallet-available"), avail0], { timeout: 4000 * S }).then(() => true, () => false));
  await page.fill(T("authorize-amount"), "99999");
  await page.click(T("authorize-submit"));
  check("authorize beyond available shows authorize-error", await waitPresent(page, "authorize-error"));
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "desktop-authorizations.png"), fullPage: true });

  // bob collects part of a_1, then the rest
  const bctx = await newCtx({ viewport: { width: 1280, height: 900 } });
  const bpage = await bctx.newPage();
  await signIn(bpage, "bob@example.com");
  await bpage.goto(BASE + "/authorizations");
  await waitPresent(bpage, "authorization-capture-a_1");
  check("receiver sees capture input pre-filled with remaining", (await bpage.inputValue(T("authorization-capture-amount-a_1"))) === "20.00");
  check("receiver has no void button", (await count(bpage, "authorization-void-a_1")) === 0);
  check("'Keep the rest held' is unchecked by default", !(await bpage.isChecked(T("authorization-keep-open-a_1"))));
  await bpage.fill(T("authorization-capture-amount-a_1"), "25.00");
  await bpage.click(T("authorization-capture-a_1"));
  check("capture over remainder shows authorization-error", await waitPresent(bpage, "authorization-error"));
  await bpage.fill(T("authorization-capture-amount-a_1"), "7.00");
  await bpage.check(T("authorization-keep-open-a_1"));
  await bpage.click(T("authorization-capture-a_1"));
  check("partial capture keeps it open with 13.00 pre-filled", await bpage.waitForFunction((s) => document.querySelector(s)?.value === "13.00", T("authorization-capture-amount-a_1"), { timeout: 4000 * S }).then(() => true, () => false));
  await bpage.click(T("authorization-capture-a_1"));
  check("final capture marks it captured", await bpage.waitForFunction((s) => document.querySelector(s)?.getAttribute("data-status") === "captured", T("authorization-item-a_1"), { timeout: 4000 * S }).then(() => true, () => false));
  check("authorization-captured shows 20.00 EUR", (await text(bpage, "authorization-captured-a_1")) === "20.00 EUR");
  check("captured hold has no capture button", (await count(bpage, "authorization-capture-a_1")) === 0);
  await page.goto(BASE + "/");
  await waitPresent(page, "wallet-available");
  check("ada: wallet-held absent at zero", (await count(page, "wallet-held")) === 0);
  check("ada: available equals total with no holds", (await attr(page, "wallet-available", "data-amount")) === (await attr(page, "wallet-balance", "data-amount")));

  // ------------------------------------------------- upgrade (export/import) --
  await page.fill(T("pay-handle"), "cy");
  await page.fill(T("pay-amount"), "1.00");
  await page.fill(T("pay-note"), "upgrade");
  await faults([{ method: "POST", path: "/payments", action: "drop_after_commit", times: 1 }]);
  await page.click(T("pay-submit"));
  await waitPresent(page, "pay-uncertain");
  const totalBefore = Number(await attr(page, "wallet-balance", "data-amount"));
  const exported = (await call("GET", "/_test/export")).data;
  await call("POST", "/_test/reset", fixture());                  // the destination starts different
  await call("POST", "/_test/import", exported);
  await page.click(T("pay-submit"));
  check("after import: retry recovers, pay-uncertain gone", await waitGone(page, "pay-uncertain"));
  check("after import: still signed in", (await text(page, "current-handle")) === "ada");
  check("after import: balance refreshed, moved once", await waitText(page, "wallet-balance", P2(totalBefore - 100)));

  // ------------------------------------------------------- signup, logout --
  const cctx = await newCtx({ viewport: { width: 375, height: 800 } });
  const cpage = await cctx.newPage();
  await cpage.goto(BASE + "/signup");
  await cpage.fill(T("signup-email"), "x@example.com");
  await cpage.fill(T("signup-password"), "short");
  await cpage.fill(T("signup-display-name"), "X");
  await cpage.click(T("signup-submit"));
  check("short password shows auth-error", await waitPresent(cpage, "auth-error"));
  await cpage.fill(T("signup-email"), "Dee.Dee@example.com");
  await cpage.fill(T("signup-password"), "correct horse");
  await cpage.fill(T("signup-display-name"), "Dee");
  await cpage.click(T("signup-submit"));
  await cpage.waitForURL(BASE + "/");
  await waitPresent(cpage, "wallet-available");
  check("signup lands on / with derived handle", (await text(cpage, "current-handle")) === "dee_dee");
  check("new user balance 0.00 EUR", (await text(cpage, "wallet-available")) === "0.00 EUR");

  // ------------------------------------------------------------ 375 px --
  for (const route of ["/", "/requests", "/split", "/authorizations"]) {
    await cpage.goto(BASE + route);
    await cpage.waitForTimeout(400 * S);
    check("375px " + route + ": no horizontal scroll", await noHorizontalScroll(cpage));
    check("375px " + route + ": current-user visible", await cpage.locator(T("current-user")).isVisible());
    if (SHOTS) await cpage.screenshot({ path: path.join(SHOTS, "m375" + (route === "/" ? "-wallet" : route.replace("/", "-")) + ".png"), fullPage: true });
  }
  await cpage.click(T("logout-button"));
  await cpage.waitForURL(BASE + "/login");
  check("logout returns to /login", cpage.url() === BASE + "/login");
  check("375px /login: no horizontal scroll", await noHorizontalScroll(cpage));
  if (SHOTS) await cpage.screenshot({ path: path.join(SHOTS, "m375-login.png"), fullPage: true });
  await cpage.goto(BASE + "/");
  await cpage.waitForURL(BASE + "/login");
  check("after logout / requires sign-in", cpage.url() === BASE + "/login");
  for (const route of ["/requests", "/split", "/authorizations", "/login", "/signup"]) {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(BASE + route);
    await page.waitForTimeout(300 * S);
    check("desktop " + route + ": no horizontal scroll", await noHorizontalScroll(page));
  }

  // empty states for a fresh user
  await call("POST", "/_test/reset", { currency: "JPY", minor_units: 0, users: [
    { id: "u_z", email: "z@example.com", password: "correct horse", display_name: "Zed", handle: "zed", balance: 1200 }] });
  const zctx = await newCtx({ viewport: { width: 375, height: 800 } });
  const zpage = await zctx.newPage();
  await signIn(zpage, "z@example.com");
  check("JPY: wallet-balance 1200 JPY", (await text(zpage, "wallet-balance")) === "1200 JPY");
  check("empty-activity shown, activity-list absent", (await count(zpage, "empty-activity")) === 1 && (await count(zpage, "activity-list")) === 0);
  await zpage.goto(BASE + "/requests");
  const emptyShown = await waitPresent(zpage, "empty-requests");
  check("empty-requests shown", emptyShown, emptyShown ? undefined : { url: zpage.url(), main: (await zpage.locator("main").innerText()).slice(0, 300) });
  await zpage.goto(BASE + "/authorizations");
  check("empty-authorizations shown", await waitPresent(zpage, "empty-authorizations"));
  if (SHOTS) await zpage.screenshot({ path: path.join(SHOTS, "m375-empty-holds.png"), fullPage: true });

  // Largest legal balances (ledger 80, 9011, 9012): exact text, no horizontal scroll at 375 px.
  for (const [balance, expected] of [[9007199254740991, "90071992547409.91 EUR"], [9007199254740992, "90071992547409.92 EUR"]]) {
    await call("POST", "/_test/reset", { currency: "EUR", minor_units: 2, users: [
      { id: "u_big", email: "big@example.com", password: "correct horse", display_name: "Big", handle: "big", balance }] });
    for (const width of [375, 1280]) {
      const bctx2 = await newCtx({ viewport: { width, height: 800 } });
      bctx2.setDefaultTimeout(10000 * S);
      const bp = await bctx2.newPage();
      await signIn(bp, "big@example.com");
      check(width + "px balance " + balance + ": wallet-balance exact", (await text(bp, "wallet-balance")) === expected && (await attr(bp, "wallet-balance", "data-amount")) === String(balance));
      check(width + "px balance " + balance + ": wallet-available exact", (await text(bp, "wallet-available")) === expected);
      { const r = await availableIsLargest(bp); check(width + "px balance " + balance + ": available still the largest figure", r.ok, r); }
      check(width + "px balance " + balance + ": / has no horizontal scroll", await noHorizontalScroll(bp),
        await bp.evaluate(() => document.documentElement.scrollWidth));
      await bp.goto(BASE + "/authorizations");
      await waitPresent(bp, "wallet-available");
      check(width + "px balance " + balance + ": /authorizations has no horizontal scroll", await noHorizontalScroll(bp),
        await bp.evaluate(() => document.documentElement.scrollWidth));
      if (SHOTS && width === 375) await bp.screenshot({ path: path.join(SHOTS, "m375-max-balance-" + balance + ".png"), fullPage: true });
      await bctx2.close();
    }
  }

  await browser.close();
  console.log(passed + "/" + (passed + failed) + " checks passed");
  process.exitCode = failed ? 1 : 0;
}
function P2(minor) { return (minor / 100).toFixed(2) + " EUR"; }

run().catch((e) => { console.error(e); process.exitCode = 2; }).finally(() => browser && browser.close());
