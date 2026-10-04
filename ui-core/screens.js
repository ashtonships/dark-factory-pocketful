/*
 * Screenshots of every route in its main states, desktop (1280) and phone (375),
 * for comparison with the picked design. Dev tooling only.
 *   NODE_PATH=<playwright-core modules> node ui-core/screens.js <base-url> <out-dir>
 * <base-url> should be a faultproxy in front of the service (uncertain state).
 */
"use strict";
const { chromium } = require("playwright-core");
const path = require("path");
const BASE = process.argv[2];
const OUT = process.argv[3];
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const T = (id) => `[data-testid="${id}"]`;

async function call(method, p, body, token, key) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  if (key) headers["Idempotency-Key"] = key;
  const res = await fetch(BASE + p, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}
const iso = (ms) => new Date(Date.now() + ms).toISOString().replace(/\.\d+Z$/, "+00:00");

async function seed() {
  await call("POST", "/_test/reset", {
    currency: "EUR", minor_units: 2,
    users: [
      { id: "u_ada", email: "ada@example.com", password: "correct horse", display_name: "Ada Lovelace", handle: "ada", balance: 10000 },
      { id: "u_bob", email: "bob@example.com", password: "correct horse", display_name: "Bob", handle: "bob", balance: 4000 },
      { id: "u_cy", email: "cy@example.com", password: "correct horse", display_name: "Cy", handle: "cy", balance: 2500 },
      { id: "u_new", email: "new@example.com", password: "correct horse", display_name: "Noor", handle: "noor", balance: 0 }
    ],
    payments: [
      { id: "p_1", from_user_id: "u_bob", to_user_id: "u_ada", amount: 2500, note: "Dinner", visibility: "public" },
      { id: "p_2", from_user_id: "u_ada", to_user_id: "u_bob", amount: 1500, note: "Lunch", visibility: "private" },
      { id: "p_3", from_user_id: "u_cy", to_user_id: "u_bob", amount: 800, note: "Cinema 🎬", visibility: "public" }
    ],
    requests: [
      { id: "rq_1", requester_id: "u_bob", payer_id: "u_ada", amount: 1200, note: "Taxi", status: "pending" },
      { id: "rq_2", requester_id: "u_cy", payer_id: "u_ada", amount: 900, note: "Lunch", status: "paid" },
      { id: "rq_3", requester_id: "u_ada", payer_id: "u_cy", amount: 2000, note: "Dinner", status: "pending" },
      { id: "rq_4", requester_id: "u_ada", payer_id: "u_bob", amount: 1500, note: "Concert tickets", status: "cancelled" }
    ],
    authorizations: [
      { id: "a_1", from_user_id: "u_bob", to_user_id: "u_ada", amount: 2000, note: "Deposit", visibility: "public", status: "open", expires_at: iso(5 * 864e5) },
      { id: "a_2", from_user_id: "u_ada", to_user_id: "u_cy", amount: 3000, note: "For our trip", visibility: "private", status: "open", expires_at: iso(3 * 864e5) },
      { id: "a_3", from_user_id: "u_cy", to_user_id: "u_ada", amount: 1500, note: "Books", visibility: "public", status: "captured", expires_at: iso(-2 * 864e5) },
      { id: "a_4", from_user_id: "u_ada", to_user_id: "u_bob", amount: 1200, note: "Bike", visibility: "public", status: "expired", expires_at: iso(-5 * 864e5) }
    ]
  });
}

async function shot(page, name) {
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: true, animations: "disabled", timeout: 180000 });
  console.log("saved " + name);
}
async function signIn(page, email) {
  await page.goto(BASE + "/login");
  await page.fill(T("login-email"), email);
  await page.fill(T("login-password"), "correct horse");
  await page.click(T("login-submit"));
  await page.waitForURL(BASE + "/");
  await page.locator(T("wallet-available")).waitFor();
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  for (const [label, viewport] of [["desktop", { width: 1280, height: 860 }], ["phone", { width: 375, height: 812 }]]) {
    await seed();
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: label === "phone" ? 2 : 1 });
    ctx.setDefaultTimeout(180000);
    const page = await ctx.newPage();
    await page.goto(BASE + "/login");
    await shot(page, label + "-login");
    await page.fill(T("login-email"), "ada@example.com");
    await page.fill(T("login-password"), "wrong");
    await page.click(T("login-submit"));
    await page.locator(T("auth-error")).waitFor();
    await shot(page, label + "-login-error");
    await page.goto(BASE + "/signup");
    await shot(page, label + "-signup");
    await signIn(page, "ada@example.com");
    await page.locator(T("activity-list")).waitFor();
    await shot(page, label + "-home");
    // success, refused, uncertain on the pay form
    await page.fill(T("pay-handle"), "bob");
    await page.fill(T("pay-amount"), "15.00");
    await page.fill(T("pay-note"), "Lunch");
    await page.selectOption(T("pay-visibility"), "private");
    await page.click(T("pay-submit"));
    await page.locator(".notice-success").first().waitFor();
    await shot(page, label + "-home-pay-success");
    await page.fill(T("pay-amount"), "1000.00");
    await page.click(T("pay-submit"));
    await page.locator(T("pay-error")).waitFor();
    await shot(page, label + "-home-pay-refused");
    await call("POST", "/_dev/faults", { rules: [{ method: "POST", path: "/payments", action: "drop_after_commit", times: 1 }] });
    await page.fill(T("pay-amount"), "5.00");
    await page.click(T("pay-submit"));
    await page.locator(T("pay-uncertain")).waitFor();
    await shot(page, label + "-home-pay-uncertain");
    await page.goto(BASE + "/requests");
    await page.locator(T("request-item-rq_1")).waitFor();
    await shot(page, label + "-requests");
    await page.goto(BASE + "/split");
    await page.locator(T("split-preview")).waitFor();
    await shot(page, label + "-split-empty");
    await page.fill(T("split-amount"), "10.00");
    await page.fill(T("split-handles"), "ada, bob, cy");
    await page.fill(T("split-note"), "Lunch");
    await page.locator(T("split-share-cy")).waitFor();
    await shot(page, label + "-split-preview");
    await page.goto(BASE + "/authorizations");
    await page.locator(T("authorization-list")).waitFor();
    await shot(page, label + "-holds");
    // empty states and the largest legal balance for a fresh user
    const nctx = await browser.newContext({ viewport, deviceScaleFactor: label === "phone" ? 2 : 1 });
    nctx.setDefaultTimeout(180000);
    const np = await nctx.newPage();
    await call("POST", "/_test/reset", { currency: "EUR", minor_units: 2, users: [
      { id: "u_new", email: "new@example.com", password: "correct horse", display_name: "Noor", handle: "noor", balance: 9007199254740992 }] });
    await signIn(np, "new@example.com");
    await np.locator(T("empty-activity")).waitFor();
    await shot(np, label + "-home-empty-max-balance");
    await np.goto(BASE + "/requests");
    await np.locator(T("empty-requests")).waitFor();
    await shot(np, label + "-requests-empty");
    await np.goto(BASE + "/authorizations");
    await np.locator(T("empty-authorizations")).waitFor();
    await shot(np, label + "-holds-empty");
    // loading skeleton: hold the first /me
    await call("POST", "/_dev/faults", { rules: [{ method: "GET", path: "/me", action: "delay", ms: 4000, times: 1 }] });
    await np.goto(BASE + "/requests");
    await shot(np, label + "-requests-loading");
    await nctx.close();
    await ctx.close();
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exitCode = 1; });
