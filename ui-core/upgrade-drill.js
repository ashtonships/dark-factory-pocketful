/*
 * Stage-1 -> stage-2 upgrade drill (stage-2 "Existing clients after an upgrade").
 * A browser signs in against the real stage-1 service, loses a payment response,
 * the stage-1 export is imported into stage-2, and the same page (no reload)
 * recovers the original payment, stays signed in and can pay an existing request.
 *
 *   python3 ui-core/faultproxy.py --port P --upstream <stage-1> --ui-upstream <stage-2> &
 *   NODE_PATH=<playwright-core> node ui-core/upgrade-drill.js http://127.0.0.1:P <stage-1> <stage-2>
 * Dev tooling only.
 */
"use strict";
const { chromium } = require("playwright-core");
const [BASE, STAGE1, STAGE2] = process.argv.slice(2);
const S = Number(process.env.DRILL_SCALE || 1);
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const T = (id) => `[data-testid="${id}"]`;
let passed = 0, failed = 0;
function check(name, cond, detail) {
  if (cond) { passed++; console.log("PASS " + name); }
  else { failed++; console.log("FAIL " + name + (detail !== undefined ? " -- " + JSON.stringify(detail) : "")); }
}
async function call(base, method, p, body) {
  const res = await fetch(base + p, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  return { status: res.status, data: text ? JSON.parse(text) : null };
}
const text = async (page, id) => (await page.locator(T(id)).textContent()).trim();

async function pass(browser, width) {
  const tag = width + "px ";
  await call(BASE, "POST", "/_dev/upstream", { api: STAGE1 });
  await call(BASE, "POST", "/_dev/faults", { rules: [] });
  const reset = await call(BASE, "POST", "/_test/reset", {
    currency: "EUR", minor_units: 2,
    users: [
      { id: "u_ada", email: "ada@example.com", password: "correct horse", display_name: "Ada", handle: "ada", balance: 10000 },
      { id: "u_bob", email: "bob@example.com", password: "correct horse", display_name: "Bob", handle: "bob", balance: 2500 }
    ],
    payments: [{ id: "p_1", from_user_id: "u_ada", to_user_id: "u_bob", amount: 500, note: "coffee", visibility: "public" }],
    requests: [{ id: "rq_1", requester_id: "u_bob", payer_id: "u_ada", amount: 1200, note: "taxi", status: "pending" }]
  });
  check(tag + "stage-1 reset accepted", reset.status === 204, reset);
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  ctx.setDefaultTimeout(15000 * S);
  const page = await ctx.newPage();
  await page.goto(BASE + "/login");
  await page.fill(T("login-email"), "ada@example.com");
  await page.fill(T("login-password"), "correct horse");
  await page.click(T("login-submit"));
  await page.waitForURL(BASE + "/");
  await page.locator(T("wallet-available")).waitFor();
  check(tag + "signed in on stage 1: available 100.00 EUR (no holds yet)", (await text(page, "wallet-available")) === "100.00 EUR", await text(page, "wallet-available"));
  check(tag + "stage 1 has no held figure", (await page.locator(T("wallet-held")).count()) === 0);

  await page.fill(T("pay-handle"), "bob");
  await page.fill(T("pay-amount"), "7.00");
  await page.fill(T("pay-note"), "before upgrade");
  await call(BASE, "POST", "/_dev/faults", { rules: [{ method: "POST", path: "/payments", action: "drop_after_commit", times: 1 }] });
  await page.click(T("pay-submit"));
  await page.locator(T("pay-uncertain")).waitFor();
  check(tag + "lost stage-1 response shows pay-uncertain", (await page.locator(T("pay-error")).count()) === 0);

  const exported = await call(STAGE1, "GET", "/_test/export");
  check(tag + "stage-1 export", exported.status === 200 && exported.data && exported.data.track === "pocketful", exported.status);
  const imported = await call(STAGE2, "POST", "/_test/import", exported.data);
  check(tag + "stage-2 imports the stage-1 export", imported.status === 204, imported);
  await call(BASE, "POST", "/_dev/upstream", { api: STAGE2 });

  await page.click(T("pay-submit"));            // same page, same form, same key
  const cleared = await page.locator(T("pay-uncertain")).waitFor({ state: "detached" }).then(() => true, () => false);
  check(tag + "after upgrade: retry recovers, pay-uncertain gone", cleared);
  check(tag + "after upgrade: no pay-error", (await page.locator(T("pay-error")).count()) === 0);
  const moved = await page.waitForFunction((s) => document.querySelector(s)?.textContent.trim() === "93.00 EUR", T("wallet-balance"), { timeout: 15000 * S }).then(() => true, () => false);
  check(tag + "after upgrade: imported balance refreshed, money moved once (93.00 EUR)", moved, await text(page, "wallet-balance"));
  check(tag + "after upgrade: still signed in", (await text(page, "current-handle")) === "ada");
  const lost = await page.locator('[data-testid^="activity-note-"]:text-is("before upgrade")').count();
  check(tag + "after upgrade: exactly one recovered payment in the feed", lost === 1, lost);

  await page.click('a[href="/requests"]');
  await page.locator(T("request-pay-rq_1")).waitFor();
  check(tag + "after upgrade: existing pending request is payable", (await page.locator(T("request-item-rq_1")).getAttribute("data-status")) === "pending");
  await page.click(T("request-pay-rq_1"));
  const paid = await page.waitForFunction((s) => document.querySelector(s)?.getAttribute("data-status") === "paid", T("request-item-rq_1"), { timeout: 15000 * S }).then(() => true, () => false);
  check(tag + "after upgrade: paying it marks it paid", paid);
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: CHROME });
  try {
    await pass(browser, 1280);
    await pass(browser, 375);
  } finally {
    await browser.close();
  }
  console.log(passed + "/" + (passed + failed) + " checks passed");
  process.exitCode = failed ? 1 : 0;
})().catch((e) => { console.error(e); process.exitCode = 2; });
