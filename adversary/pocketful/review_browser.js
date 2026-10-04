"use strict";
const assert = require("node:assert/strict");
const { chromium } = require("playwright-core");
const base = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || "")) throw new Error("Pass an isolated loopback HTTP service URL");
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
  await page.waitForFunction(() => !document.querySelector("#pay-messages .notice-pending, #pay-messages .pending-line, #refresh-status .notice-pending, #refresh-status .pending-line"));
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
      if (process.argv.includes("--presence")) {
        await check("binding controls are at least 44px high", async () => {
          const height = await page.locator(selector("logout-button")).evaluate(element => element.getBoundingClientRect().height);
          assert.ok(height >= 44, "logout-button height=" + height);
        });
        await check("zero holds omit wallet-held and available is headline", async () => {
          assert.equal(await page.locator(selector("wallet-held")).count(), 0);
          const sizes = await page.evaluate(() => ["wallet-available", "wallet-balance"].map(id => parseFloat(getComputedStyle(document.querySelector('[data-testid="' + id + '"]')).fontSize)));
          assert.ok(sizes[0] > sizes[1]);
        });
        const seeded = fixture();
        seeded.requests = [
          { id: "rq_in", requester_id: "u_bob", payer_id: "u_ada", amount: 500, note: "incoming", status: "pending" },
          { id: "rq_out", requester_id: "u_ada", payer_id: "u_bob", amount: 250, note: "outgoing", status: "pending" }
        ];
        await call("/_test/reset", seeded);
        await signIn(page);
        await page.goto(base + "/requests", { waitUntil: "domcontentloaded" });
        await page.locator(selector("request-pay-rq_in")).waitFor();
        await check("request buttons belong only to pending permitted direction", async () => {
          assert.equal(await page.locator(selector("request-decline-rq_in")).count(), 1);
          assert.equal(await page.locator(selector("request-cancel-rq_in")).count(), 0);
          assert.equal(await page.locator(selector("request-cancel-rq_out")).count(), 1);
          assert.equal(await page.locator(selector("request-pay-rq_out")).count(), 0);
        });
        const sessionResponse = await fetch(base + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "bob@example.com", password: "correct horse" }) });
        const session = await sessionResponse.json();
        const cancellation = await fetch(base + "/requests/rq_in/cancel", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + session.token }, body: "{}" });
        assert.equal(cancellation.status, 200);
        await page.locator(selector("request-pay-rq_in")).click();
        await check("stale cancelled request shows refusal and refresh removes pay", async () => {
          await page.locator(selector("request-error")).waitFor();
          await page.waitForFunction(target => document.querySelector(target)?.getAttribute("data-status") === "cancelled", selector("request-item-rq_in"));
          assert.equal(await page.locator(selector("request-pay-rq_in")).count(), 0);
        });
        await page.locator(selector("request-cancel-rq_out")).click();
        await check("successful cancel refreshes row and removes its action", async () => {
          await page.waitForFunction(target => document.querySelector(target)?.getAttribute("data-status") === "cancelled", selector("request-item-rq_out"));
          assert.equal(await page.locator(selector("request-cancel-rq_out")).count(), 0);
        });
        const heldFixture = fixture();
        heldFixture.authorizations = [{ id: "a_in", from_user_id: "u_bob", to_user_id: "u_ada", amount: 1000, note: "capture retry", visibility: "private", status: "open", expires_at: new Date(Date.now() + 7200000).toISOString() }];
        await call("/_test/reset", heldFixture);
        await signIn(page);
        await page.goto(base + "/authorizations", { waitUntil: "domcontentloaded" });
        await page.locator(selector("authorization-capture-a_in")).waitFor();
        await check("incoming open hold has capture only, default amount and final mode", async () => {
          assert.equal(await page.locator(selector("authorization-capture-amount-a_in")).inputValue(), "10.00");
          assert.equal(await page.locator(selector("authorization-keep-open-a_in")).isChecked(), false);
          assert.equal(await page.locator(selector("authorization-void-a_in")).count(), 0);
          assert.equal(await page.locator(selector("authorization-captured-a_in")).count(), 0);
        });
        const captures = [];
        const captureUrl = base + "/authorizations/a_in/capture";
        page.on("request", request => { if (request.url() === captureUrl) captures.push({ key: request.headers()["idempotency-key"], body: request.postData() }); });
        let releaseFirst;
        let markCommitted;
        let markRead;
        let captureCount = 0;
        const firstReleased = new Promise(resolve => { releaseFirst = resolve; });
        const firstCommitted = new Promise(resolve => { markCommitted = resolve; });
        const readStarted = new Promise(resolve => { markRead = resolve; });
        const delayedReads = [];
        await page.route(captureUrl, async route => {
          captureCount++;
          if (captureCount === 1) {
            const response = await route.fetch();
            markCommitted();
            await firstReleased;
            await route.fulfill({ response });
          } else if (captureCount === 2) {
            await route.fetch();
            await route.abort("failed");
          } else await route.continue();
        });
        await page.locator(selector("authorization-keep-open-a_in")).check();
        await page.locator(selector("authorization-capture-amount-a_in")).fill("3");
        await page.locator(selector("authorization-capture-a_in")).click();
        await firstCommitted;
        await page.locator(selector("authorization-capture-amount-a_in")).fill("2");
        await page.locator(selector("authorization-capture-a_in")).click();
        await page.locator(selector("authorization-uncertain")).waitFor();
        await page.route(base + "/authorizations?limit=200", route => { delayedReads.push(route); markRead(); });
        releaseFirst();
        await readStarted;
        const retryResponse = page.waitForResponse(response => response.url() === captureUrl && response.request().postData() === captures[1].body);
        await page.locator(selector("authorization-capture-a_in")).click();
        await retryResponse;
        const token = await page.evaluate(() => localStorage.getItem("pocketful.token"));
        const captureState = await fetch(base + "/authorizations", { headers: { Accept: "application/json", Authorization: "Bearer " + token } });
        const afterRetry = (await captureState.json()).authorizations.find(authorization => authorization.authorization_id === "a_in");
        await check("late earlier capture does not erase uncertain newer retry identity", async () => {
          assert.equal(captures[2].body, captures[1].body);
          assert.equal(captures[2].key, captures[1].key, "late earlier success discarded the newer capture key; captured_amount=" + afterRetry.captured_amount + ", expected500");
          assert.equal(afterRetry.captured_amount, 500, "unchanged retry must not capture again");
        });
        await page.unroute(captureUrl);
        await page.unroute(base + "/authorizations?limit=200");
        for (const route of delayedReads) await route.continue().catch(() => {});
        await call("/_test/reset", fixture());
        await signIn(page);
      }
      if (process.argv.includes("--d11")) {
        const authorizations = [];
        page.on("request", request => {
          if (request.method() === "POST" && request.url() === base + "/authorizations") authorizations.push({ key: request.headers()["idempotency-key"], body: request.postData() });
        });
        await check("D-11 home authorize form has labeled required fields", async () => {
          for (const field of ["handle", "amount", "note", "visibility", "submit"]) assert.equal(await page.locator(selector("authorize-" + field)).count(), 1);
          for (const field of ["handle", "amount", "note", "visibility"]) assert.equal(await page.locator('label[for="authorize-' + field + '"]').count(), 1);
        });
        await page.locator(selector("authorize-handle")).fill("bob");
        await page.locator(selector("authorize-amount")).fill("2.505");
        await page.locator(selector("authorize-submit")).click();
        await check("D-11 invalid precision never posts a hold", async () => {
          await page.locator(selector("authorize-error")).waitFor();
          assert.equal(authorizations.length, 0);
        });
        await page.locator(selector("authorize-amount")).fill("2.50");
        await page.locator(selector("authorize-note")).fill("Home hold e\u0301 😀");
        await page.locator(selector("authorize-visibility")).selectOption("private");
        await page.locator(selector("authorize-submit")).click();
        await check("D-11 home hold refreshes available and held, not total", async () => {
          await page.waitForFunction(target => document.querySelector(target)?.getAttribute("data-amount") === "9750", selector("wallet-available"));
          assert.equal(await page.locator(selector("wallet-held")).getAttribute("data-amount"), "250");
          assert.equal(await page.locator(selector("wallet-balance")).getAttribute("data-amount"), "10000");
          assert.equal(await page.locator(selector("authorize-error")).count(), 0);
        });
        const readHolds = () => page.evaluate(async () => {
          const response = await fetch("/authorizations", { headers: { Accept: "application/json", Authorization: "Bearer " + localStorage.getItem("pocketful.token") } });
          return (await response.json()).authorizations;
        });
        const holds = await readHolds();
        await check("D-11 private hold receipt preserves note and stays out of feed", async () => {
          assert.equal(holds.length, 1);
          assert.equal(holds[0].amount, 250);
          assert.equal(holds[0].visibility, "private");
          assert.equal(holds[0].to_handle, "bob");
          assert.equal(holds[0].note, "Home hold e\u0301 😀");
          assert.equal(await page.locator(selector("empty-activity")).count(), 1);
        });
        await check("D-11 unchanged home resubmit reserves once", async () => {
          await Promise.all([
            page.waitForResponse(response => response.url() === base + "/authorizations" && response.request().method() === "POST"),
            page.locator(selector("authorize-submit")).click()
          ]);
          assert.equal(authorizations.length, 2);
          assert.equal(authorizations[0].key, authorizations[1].key);
          assert.equal((await readHolds()).length, 1);
        });
        await page.locator(selector("authorize-amount")).fill("99999");
        await page.locator(selector("authorize-submit")).click();
        await check("D-11 refused home hold preserves fields and wallet", async () => {
          await page.locator(selector("authorize-error")).waitFor();
          assert.equal(await page.locator(selector("authorize-amount")).inputValue(), "99999");
          assert.equal(await page.locator(selector("authorize-note")).inputValue(), "Home hold e\u0301 😀");
          assert.equal(await page.locator(selector("authorize-visibility")).inputValue(), "private");
          assert.equal(await page.locator(selector("wallet-available")).getAttribute("data-amount"), "9750");
        });
        await page.goto(base + "/authorizations", { waitUntil: "domcontentloaded", timeout: 10000 });
        await page.locator(selector("authorization-void-" + holds[0].authorization_id)).waitFor();
        await check("D-11 authorize form remains on authorizations route", async () => assert.equal(await page.locator(selector("authorize-submit")).count(), 1));
        await page.locator(selector("authorization-void-" + holds[0].authorization_id)).click();
        await page.waitForFunction(target => document.querySelector(target)?.getAttribute("data-amount") === "10000", selector("wallet-available"));
        await page.goto(base + "/", { waitUntil: "domcontentloaded", timeout: 10000 });
        await page.locator(selector("wallet-balance")).waitFor();
      }
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
        await Promise.all([
          page.waitForResponse(response => response.url() === base + "/me"),
          page.locator(selector("pay-submit")).click()
        ]);
        await settle(page);
        assert.equal(writes.at(-1).key, writes.at(-2).key);
        assert.equal(await page.locator('[data-testid^="activity-item-"]').count(), 1);
      });
      await page.locator(selector("pay-amount")).fill("15.00");
      await Promise.all([
        page.waitForResponse(response => response.url() === base + "/me"),
        page.locator(selector("pay-submit")).click()
      ]);
      await settle(page);
      await check("edited amount text creates a new payment identity", async () => {
        await balance(page, 7000);
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
      const large = fixture();
      large.users[0].balance = 2 ** 53 - 1;
      await call("/_test/reset", large);
      await signIn(page);
      await check("maximum safe wallet amount fits the viewport", async () => {
        const sizes = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
        assert.ok(sizes.content <= sizes.viewport, JSON.stringify(sizes));
      });
      await page.close();
      const boundaryPage = await context.newPage();
      boundaryPage.setDefaultTimeout(5000);
      large.users[0].balance = 2 ** 53;
      await call("/_test/reset", large);
      await check("inclusive 2^53 wallet balance renders", async () => {
        await signIn(boundaryPage);
        assert.equal(await boundaryPage.locator(selector("wallet-balance")).textContent(), "90071992547409.92 EUR");
      });
      await context.close();
    }
  } finally { await browser.close(); }
  console.log(passed + "/" + (passed + failed) + " independent checks passed");
  process.exitCode = failed ? 1 : 0;
}
run().catch(error => { console.error(error); process.exitCode = 2; });
