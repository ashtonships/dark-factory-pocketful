"use strict";
const assert = require("node:assert/strict");
const { chromium } = require("playwright-core");
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || "")) throw new Error("Pass an isolated loopback devstub URL");
const selector = id => '[data-testid="' + id + '"]';
let failed = 0;
let passed = 0;
async function call(path, body) {
  const response = await fetch(base + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  assert.ok(response.ok, "control call failed: " + path);
}
function fixture() {
  return { currency: "EUR", minor_units: 2, users: [
    { id: "u_ada", handle: "ada", email: "ada@example.com", password: "correct horse", display_name: "<img src=x onerror=window.XSS=1> Ada", balance: 10000 },
    { id: "u_bob", handle: "bob", email: "bob@example.com", password: "correct horse", display_name: "Bob", balance: 2500 }
  ], requests: [], payments: [], authorizations: [] };
}
async function signIn(page) {
  await page.goto(base + "/login", { waitUntil: "domcontentloaded", timeout: 10000 });
  await page.locator(selector("login-email")).fill("ada@example.com");
  await page.locator(selector("login-password")).fill("correct horse");
  await page.locator(selector("login-submit")).click();
  await page.waitForURL(base + "/");
  await page.locator(selector("wallet-balance")).waitFor();
}
async function balance(page, amount) {
  await page.waitForFunction(([target, value]) => document.querySelector(target)?.getAttribute("data-amount") === value, [selector("wallet-balance"), String(amount)]);
}
async function settle(page) {
  await page.waitForFunction(() => !document.querySelector("#pay-messages .notice-pending") && !document.querySelector("#refresh-status .notice-pending"));
}
async function run() {
  const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
  try {
    for (const width of [1280, 375]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      await context.route("**/*", route => {
        const url = new URL(route.request().url());
        return url.origin === base ? route.continue() : route.abort();
      });
      const page = await context.newPage();
      page.setDefaultTimeout(5000);
      const errors = [];
      page.on("pageerror", error => errors.push(error.message));
      const writes = [];
      page.on("request", request => { if (request.method() === "POST" && request.url() === base + "/payments") writes.push({ key: request.headers()["idempotency-key"], body: request.postData() }); });
      async function check(name, operation) {
        try { await operation(); passed++; console.log("PASS " + width + " " + name); }
        catch (error) { failed++; console.log("FAIL " + width + " " + name + ": " + error.message); }
      }
      await call("/_test/reset", fixture());
      await signIn(page);
      await page.locator(selector("pay-handle")).fill("bob");
      await page.locator(selector("pay-amount")).fill("15");
      await page.locator(selector("pay-note")).fill("  <img src=x onerror=window.XSS=2> e\u0301 😀");
      await page.locator(selector("pay-submit")).click();
      await balance(page, 8500);
      await settle(page);
      await check("names and notes remain inert verbatim text", async () => {
        assert.equal(await page.evaluate(() => window.XSS), undefined);
        assert.equal(await page.locator(selector("current-user")).textContent(), fixture().users[0].display_name);
        assert.equal(await page.locator('[data-testid^="activity-note-"]').textContent(), "  <img src=x onerror=window.XSS=2> e\u0301 😀");
      });
      await check("unchanged resubmit replays one payment", async () => {
        await page.locator(selector("pay-submit")).click();
        await page.waitForResponse(response => response.url() === base + "/me");
        await settle(page);
        assert.equal(writes.at(-1).key, writes.at(-2).key);
        assert.equal(await page.locator('[data-testid^="activity-item-"]').count(), 1);
      });
      await page.locator(selector("pay-amount")).fill("15.00");
      await page.locator(selector("pay-submit")).click();
      await page.waitForResponse(response => response.url() === base + "/me");
      await settle(page);
      await check("edited amount text creates a new payment identity", async () => {
        assert.notEqual(writes.at(-1).key, writes.at(-2).key);
        assert.equal(await page.locator(selector("wallet-balance")).getAttribute("data-amount"), "7000");
      });
      await check("viewport has no horizontal scrolling", async () => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)));
      await call("/_test/reset", fixture());
      await signIn(page);
      writes.length = 0;
      await page.locator(selector("pay-handle")).fill("bob");
      await page.locator(selector("pay-amount")).fill("1");
      await check("simultaneous unchanged submits debit once", async () => {
        await page.evaluate(target => {
          const form = document.querySelector(target).form;
          form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
          form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        }, selector("pay-submit"));
        await balance(page, 9900);
        await settle(page);
        assert.equal(writes.length, 2);
        assert.equal(writes[0].key, writes[1].key);
        assert.equal(await page.locator('[data-testid^="activity-item-"]').count(), 1);
      });
      await call("/_test/reset", fixture());
      await signIn(page);
      await page.locator(selector("pay-handle")).fill("bob");
      await page.locator(selector("pay-amount")).fill("1");
      const before = writes.length;
      await page.route(base + "/payments", async route => {
        const response = await route.fetch();
        await route.fulfill({ response, body: "", headers: { "Content-Type": "application/json", "Content-Length": "0" } });
      }, { times: 1 });
      await page.locator(selector("pay-submit")).click();
      await check("empty receipt after commit shows pay-uncertain", async () => {
        await page.locator(selector("pay-uncertain")).waitFor();
        assert.equal(await page.locator(selector("pay-error")).count(), 0);
      });
      console.log("OBSERVE empty receipt browser errors: " + JSON.stringify(errors));
      await page.locator(selector("pay-submit")).click();
      await check("empty-receipt manual retry still moves money once", async () => {
        await balance(page, 9900);
        await settle(page);
        assert.equal(writes[before].key, writes[before + 1].key);
        assert.equal(await page.locator('[data-testid^="activity-item-"]').count(), 1);
      });
      await context.close();
    }
  } finally { await browser.close(); }
  console.log(passed + "/" + (passed + failed) + " independent checks passed");
  process.exitCode = failed ? 1 : 0;
}
run().catch(error => { console.error(error); process.exitCode = 2; });
