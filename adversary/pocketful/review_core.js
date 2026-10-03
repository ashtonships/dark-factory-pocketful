"use strict";
const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const vm = require("node:vm");
const repo = process.argv[2];
const revision = process.argv[3] || "77595cc";
if (!repo) throw new Error("Usage: node review_core.js <repository> [revision]");
const source = childProcess.execFileSync("git", ["-C", repo, "show", revision + ":ui-core/pocketful-core.js"], { encoding: "utf8" });
const sandbox = { module: { exports: {} }, setTimeout, clearTimeout, AbortController };
vm.runInNewContext(source, sandbox);
const core = sandbox.module.exports;
let failures = 0;
async function check(name, operation) {
  try { await operation(); process.stdout.write("PASS " + name + "\n"); }
  catch (error) { failures++; process.stdout.write("FAIL " + name + ": " + error.message + "\n"); }
}
async function run() {
  await check("exact decimal arithmetic across supported currencies", () => {
    for (const units of [0, 2, 3]) {
      for (let minor = 0; minor <= 100000; minor += 137) {
        const decimal = core.formatAmount(minor, units, "");
        assert.equal(core.parseAmount(decimal, units).minor, minor);
      }
    }
    assert.equal(core.parseAmount("15.005", 2).ok, false);
    assert.equal(core.parseAmount("1e3", 2).ok, false);
    assert.equal(core.formatAmount(1200, 0, "JPY"), "1200 JPY");
  });
  await check("split shares preserve conservation and input order", () => {
    for (const amount of [1, 5, 10, 999, 1000, 1000000000]) {
      for (let count = 1; count <= 50; count++) {
        const shares = Array.from(core.splitShares(amount, count));
        assert.equal(shares.reduce((sum, value) => sum + value, 0), amount);
        assert.ok(Math.max(...shares) - Math.min(...shares) <= 1);
        assert.deepEqual(shares, shares.slice().sort((first, second) => second - first));
      }
    }
  });
  await check("latest refresh remains newer after reverse-order resolution", async () => {
    let firstResolve;
    let secondResolve;
    const reads = new core.LatestWins();
    const applied = [];
    const first = reads.run(() => new Promise(resolve => { firstResolve = resolve; }), value => applied.push(value));
    const second = reads.run(() => new Promise(resolve => { secondResolve = resolve; }), value => applied.push(value));
    await Promise.resolve();
    secondResolve(1);
    await second;
    firstResolve(100);
    await first;
    assert.deepEqual(applied, [1]);
  });
  await check("409 insufficient_funds is refused and a 4xx key is reusable", async () => {
    let calls = 0;
    const keys = [];
    const client = new core.ApiClient({ tokens: new core.TokenStore(null), fetch: async (url, init) => {
      keys.push(init.headers["Idempotency-Key"]);
      calls++;
      return { status: calls === 1 ? 409 : 201, text: async () => JSON.stringify(calls === 1 ? { error: { code: "insufficient_funds", message: "short" } } : { payment_id: "p_one" }) };
    }});
    const first = await client.write("pay", "POST", "/payments", { to_handle: "bob", amount: 100 });
    assert.equal(first.kind, "refused");
    assert.equal(first.code, "insufficient_funds");
    assert.equal((await client.write("pay", "POST", "/payments", { to_handle: "bob", amount: 100 })).kind, "ok");
    assert.equal(keys[0], keys[1]);
  });
  await check("lost response preserves original key/body and retry clears uncertainty", async () => {
    const submissions = [];
    const client = new core.ApiClient({ tokens: new core.TokenStore(null), fetch: async (url, init) => {
      submissions.push([init.body, init.headers["Idempotency-Key"]]);
      if (submissions.length === 1) throw new Error("lost after commit");
      return { status: 200, text: async () => JSON.stringify({ payment_id: "p_one" }) };
    }});
    const form = new core.Submission();
    const body = { to_handle: "bob", amount: 100 };
    form.settle(form.begin(), await client.write("pay", "POST", "/payments", body));
    assert.equal(form.state, "uncertain");
    assert.equal(form.error, null);
    form.settle(form.begin(), await client.write("pay", "POST", "/payments", body));
    assert.equal(form.state, "done");
    assert.equal(form.uncertain, null);
    assert.deepEqual(submissions[0], submissions[1]);
  });
  await check("Web Crypto fallback preserves distinct entropy inputs", () => {
    let byte = 0;
    const cryptoSandbox = { module: { exports: {} }, crypto: { getRandomValues: bytes => { bytes.fill(byte); return bytes; } } };
    vm.runInNewContext(source, cryptoSandbox);
    const first = cryptoSandbox.module.exports.newKey();
    byte = 17;
    assert.notEqual(first, cryptoSandbox.module.exports.newKey());
  });
  await check("empty committed-payment receipt is uncertain", () => assert.equal(core.classify(201, "").kind, "uncertain"));
  await check("upper inclusive wallet balance formats exactly", () => assert.equal(core.formatAmount(2 ** 53, 2, "EUR"), "90071992547409.92 EUR"));
  await check("null committed-payment receipt is uncertain", () => assert.equal(core.classify(201, "null").kind, "uncertain"));
  await check("raw pay amount edit mints a new identity", () => {
    let serial = 0;
    const keys = new core.KeyRing(() => "key-" + ++serial);
    const first = keys.keyFor("pay", "POST", "/payments", { to_handle: "bob", amount: core.parseAmount("15", 2).minor });
    const second = keys.keyFor("pay", "POST", "/payments", { to_handle: "bob", amount: core.parseAmount("15.00", 2).minor });
    assert.notEqual(first, second);
  });
  process.stdout.write("Revision " + revision + "; " + failures + " required-behavior failures\n");
  process.exitCode = failures ? 1 : 0;
}
run().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 2; });
