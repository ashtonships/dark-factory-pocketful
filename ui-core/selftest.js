/*
 * Self-test for pocketful-core.js. Runs in a browser (selftest.html) and in
 * Node (`node ui-core/selftest.js`). Each case names the requirement it serves.
 */
(function (root) {
  "use strict";
  var C = root.PocketfulCore || (typeof require === "function" ? require("./pocketful-core.js") : null);

  var cases = [];
  function test(group, name, ref, fn) { cases.push({ group: group, name: name, ref: ref, fn: fn }); }

  function eq(actual, expected, label) {
    var a = JSON.stringify(actual), e = JSON.stringify(expected);
    if (a !== e) throw new Error((label ? label + ": " : "") + "expected " + e + ", got " + a);
  }
  function ok(cond, label) { if (!cond) throw new Error(label || "assertion failed"); }
  function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  // ------------------------------------------------------------ money --
  var FMT = "stage-2 'Formatted amount'";
  test("money", "formats 2-decimal currency", FMT, function () {
    eq(C.formatAmount(10000, 2, "EUR"), "100.00 EUR");
    eq(C.formatAmount(1, 2, "EUR"), "0.01 EUR");
    eq(C.formatAmount(0, 2, "EUR"), "0.00 EUR");
    eq(C.formatAmount(1550, 2, "EUR"), "15.50 EUR");
  });
  test("money", "formats 0-decimal currency without a point", FMT, function () {
    eq(C.formatAmount(1200, 0, "JPY"), "1200 JPY");
    eq(C.formatAmount(0, 0, "JPY"), "0 JPY");
  });
  test("money", "formats 3-decimal currency", FMT, function () {
    eq(C.formatAmount(5, 3, "BHD"), "0.005 BHD");
    eq(C.formatAmount(1234567, 3, "BHD"), "1234.567 BHD");
  });
  test("money", "formats the largest exact amounts without float error", "stage-1 §4 'Arithmetic range'", function () {
    eq(C.formatAmount(9007199254740991, 2, "EUR"), "90071992547409.91 EUR");
    eq(C.formatAmount(1000000000, 3, "BHD"), "1000000.000 BHD");
  });
  test("money", "rejects non-integer and out-of-range amounts for formatting", FMT, function () {
    [1.5, NaN, Infinity, 9007199254740994, -9007199254740994, "1.5", null].forEach(function (v) {
      var threw = false;
      try { C.formatAmount(v, 2, "EUR"); } catch (e) { threw = true; }
      ok(threw, String(v) + " must not format");
    });
  });
  test("money", "the inclusive 2^53 boundary formats exactly (PF-A3)", "stage-1 §4 'no operation produces a balance outside ±2⁵³'; ledger 9011", function () {
    eq(C.formatAmount(9007199254740992, 2, "EUR"), "90071992547409.92 EUR");
    eq(C.formatAmount(9007199254740992, 0, "JPY"), "9007199254740992 JPY");
    eq(C.formatAmount(9007199254740992, 3, "BHD"), "9007199254740.992 BHD");
    eq(C.formatAmount(-9007199254740992, 2, "EUR"), "-90071992547409.92 EUR");
    eq(C.formatAmount(9007199254740991, 2, "EUR"), "90071992547409.91 EUR");
  });

  var PARSE = "stage-2 'The form accepts decimal amounts and submits minor units'";
  function parsed(text, mu) { var r = C.parseAmount(text, mu); return r.ok ? r.minor : "REJECT"; }
  test("money", "15.00 and 15 submit 1500; 15.5 submits 1550", PARSE, function () {
    eq(parsed("15.00", 2), 1500);
    eq(parsed("15", 2), 1500);
    eq(parsed("15.5", 2), 1550);
  });
  test("money", "15.005 is rejected, never rounded", PARSE, function () {
    eq(parsed("15.005", 2), "REJECT");
    eq(parsed("15.0", 0), "REJECT");
    eq(parsed("1.2345", 3), "REJECT");
  });
  test("money", "nonnumeric input is rejected", PARSE, function () {
    ["", "  ", "abc", "1e3", "-5", "+5", "1,000", "15.5.0", "0x10", ".", "Infinity", "NaN", "15 EUR"].forEach(function (t) {
      eq(parsed(t, 2), "REJECT", JSON.stringify(t));
    });
    eq(C.parseAmount(undefined, 2).ok, false);
  });
  test("money", "exact string arithmetic (no float drift)", PARSE, function () {
    eq(parsed("0.29", 2), 29);      // 0.29 * 100 = 28.999999999999996 in floats
    eq(parsed("1.15", 2), 115);     // 1.15 * 100 = 114.99999999999999
    eq(parsed("4.35", 2), 435);
    eq(parsed("10000000.00", 2), 1000000000);
    eq(parsed("0.001", 3), 1);
    eq(parsed("1200", 0), 1200);
  });
  test("money", "forgiving forms a person types", PARSE, function () {
    eq(parsed(" 15.50 ", 2), 1550);
    eq(parsed(".5", 2), 50);
    eq(parsed("15.", 2), 1500);
    eq(parsed("007.10", 2), 710);
  });
  test("money", "absurdly long input is rejected, not approximated", PARSE, function () {
    eq(parsed("99999999999999999999", 2), "REJECT");
  });
  test("money", "parse then format round-trips", FMT, function () {
    [["15.00", 2, "EUR"], ["1200", 0, "JPY"], ["0.005", 3, "BHD"]].forEach(function (c) {
      eq(C.formatAmount(C.parseAmount(c[0], c[1]).minor, c[1], c[2]), c[0] + " " + c[2]);
    });
  });

  // ------------------------------------------------------------ split --
  var SPLIT = "stage-1 §9; stage-2 'split-preview must show the shares the server would compute'";
  test("split", "the §9 table", SPLIT, function () {
    eq(C.splitShares(1000, 3), [334, 333, 333]);
    eq(C.splitShares(1, 3), [1, 0, 0]);
    eq(C.splitShares(10, 3), [4, 3, 3]);
    eq(C.splitShares(999, 3), [333, 333, 333]);
    eq(C.splitShares(5, 5), [1, 1, 1, 1, 1]);
    eq(C.splitShares(3000, 1), [3000]);
  });
  test("split", "shares sum exactly, differ by at most one, larger first", SPLIT, function () {
    for (var i = 0; i < 2000; i++) {
      var amount = 1 + Math.floor(Math.random() * 1000000000);
      var n = 1 + Math.floor(Math.random() * 40);
      var s = C.splitShares(amount, n);
      var sum = s.reduce(function (a, b) { return a + b; }, 0);
      ok(sum === amount, "sum " + amount + "/" + n);
      for (var j = 1; j < n; j++) ok(s[j] <= s[j - 1] && s[0] - s[j] <= 1, "shape " + amount + "/" + n);
    }
  });
  test("split", "order of handles decides who gets the extra unit", SPLIT, function () {
    eq(C.splitPreview(10, ["ada", "bob", "cy"]), [{ handle: "ada", amount: 4 }, { handle: "bob", amount: 3 }, { handle: "cy", amount: 3 }]);
    eq(C.splitPreview(10, ["cy", "ada", "bob"]), [{ handle: "cy", amount: 4 }, { handle: "ada", amount: 3 }, { handle: "bob", amount: 3 }]);
  });
  test("split", "comma-separated handles parse in order", "stage-2 'split-handles: handles separated by commas, in order'", function () {
    eq(C.parseHandles("ada,bob,cy"), ["ada", "bob", "cy"]);
    eq(C.parseHandles(" ada , @bob,cy, "), ["ada", "bob", "cy"]);
    eq(C.parseHandles(""), []);
    eq(C.parseHandles("ada,ada"), ["ada", "ada"]);
  });

  // ------------------------------------------------------- idempotency --
  var IDEM = "stage-2 'Submitting it again without changing a field must not send another payment'";
  test("keys", "same JSON value -> same canonical form", "stage-1 §7 'Same body means the same JSON value'", function () {
    eq(C.canonicalJson({ b: 1, a: [1, { y: 2, x: 1 }] }), C.canonicalJson({ a: [1, { x: 1, y: 2 }], b: 1 }));
    ok(C.canonicalJson({}) !== C.canonicalJson({ visibility: "public" }), "{} differs from {visibility: public}");
  });
  test("keys", "unchanged resubmit reuses the key; any change mints a new one", IDEM, function () {
    var n = 0;
    var ring = new C.KeyRing(function () { return "k" + (++n); });
    var body = { to_handle: "bob", amount: 1500, note: "", visibility: "public" };
    var k1 = ring.keyFor("pay", "POST", "/payments", body);
    eq(ring.keyFor("pay", "POST", "/payments", { visibility: "public", note: "", amount: 1500, to_handle: "bob" }), k1, "reordered");
    var k2 = ring.keyFor("pay", "POST", "/payments", { to_handle: "bob", amount: 1501, note: "", visibility: "public" });
    ok(k2 !== k1, "changed amount gets a new key");
    var k3 = ring.keyFor("pay", "POST", "/payments", body);
    ok(k3 !== k1 && k3 !== k2, "changing back is a new submission, not the first one");
    var k4 = ring.keyFor("pay", "POST", "/requests/rq_1/pay", body);
    ok(k4 !== k3, "different path is a different request");
    ok(ring.keyFor("request", "POST", "/payments", body) !== k3, "slots are independent");
  });
  test("keys", "a raw edit is a new intent even when the body normalises the same (PF-A2)", "ledger 1045, 9010", function () {
    var n = 0;
    var ring = new C.KeyRing(function () { return "k" + (++n); });
    var body = { to_handle: "bob", amount: 1500, note: "", visibility: "public" };
    var raw = { "pay-handle": "bob", "pay-amount": "15", "pay-note": "", "pay-visibility": "public" };
    var k1 = ring.keyFor("pay", "POST", "/payments", body, raw);
    eq(ring.keyFor("pay", "POST", "/payments", body, Object.assign({}, raw)), k1, "unchanged raw form keeps the key");
    var k2 = ring.keyFor("pay", "POST", "/payments", body, Object.assign({}, raw, { "pay-amount": "15.00" }));
    ok(k2 !== k1, "15 -> 15.00 is new");
    var k3 = ring.keyFor("pay", "POST", "/payments", body, Object.assign({}, raw, { "pay-amount": "15.00", "pay-handle": "@bob" }));
    ok(k3 !== k2, "bob -> @bob is new");
    var k4 = ring.keyFor("pay", "POST", "/payments", body, Object.assign({}, raw, { "pay-amount": "15.00", "pay-handle": "@bob " }));
    ok(k4 !== k3, "trailing space is new");
    eq(ring.keyFor("pay", "POST", "/payments", body, Object.assign({}, raw, { "pay-amount": "15.00", "pay-handle": "@bob " })), k4, "and stable once unchanged");
  });
  test("keys", "getRandomValues fallback: distinct entropy gives distinct, well-formed keys", "stage-1 §5 'Idempotency-Key 1 to 255 characters'; mutation survivor 11", function () {
    function filled(byte) {
      return { getRandomValues: function (bytes) { bytes.fill(byte); return bytes; } };   // no randomUUID
    }
    var seen = {};
    [0, 1, 15, 16, 17, 127, 128, 254, 255].forEach(function (b) {
      var k = C.newKey(filled(b));
      var hex = (b + 256).toString(16).slice(1);
      eq(k, new Array(17).join(hex), "byte " + b);
      ok(/^[0-9a-f]{32}$/.test(k), "32 lowercase hex characters");
      ok(!seen[k], "distinct for byte " + b);
      seen[k] = true;
    });
    var bytes = 0;
    var counting = { getRandomValues: function (a) { for (var i = 0; i < a.length; i++) a[i] = (bytes++) & 255; return a; } };
    ok(C.newKey(counting) !== C.newKey(counting), "successive draws differ");
  });
  test("keys", "generated keys are 1..255 characters and unique", "stage-1 §5 'Idempotency-Key 1 to 255 characters'", function () {
    var seen = {};
    for (var i = 0; i < 500; i++) {
      var k = C.newKey();
      ok(k.length >= 1 && k.length <= 255, "length");
      ok(!seen[k], "unique"); seen[k] = true;
    }
  });

  // ------------------------------------------------------- client --
  var OUTCOME = "stage-2 'Unknown outcomes are not confirmed rejections'";
  test("client", "classifies 2xx / 4xx / 5xx", OUTCOME, function () {
    eq(C.classify(201, '{"payment_id":"p_1"}').kind, "ok");
    eq(C.classify(200, '{"payment_id":"p_1"}').kind, "ok");
    var r = C.classify(409, '{"error":{"code":"insufficient_funds","message":"x"}}');
    eq([r.kind, r.code], ["refused", "insufficient_funds"]);
    eq(C.classify(404, "not json").code, "http_404");
    eq(C.classify(500, "").kind, "uncertain");
    eq(C.classify(503, '{"error":{"code":"x"}}').kind, "uncertain");
    eq(C.classify(201, "<html>").kind, "uncertain");
  });
  test("client", "a 2xx that is not the expected JSON object is uncertain (PF-A1)", "ledger 9009; stage-2 'Unknown outcomes are not confirmed rejections'", function () {
    ["", "null", "[]", "\"ok\"", "42", "true", "{", "  "].forEach(function (t) {
      eq(C.classify(201, t).kind, "uncertain", JSON.stringify(t));
      eq(C.classify(200, t).kind, "uncertain", JSON.stringify(t));
    });
    eq(C.classify(204, "").kind, "uncertain");
    eq(C.classify(201, "{}", "payment_id").kind, "uncertain", "missing expected field");
    eq(C.classify(201, '{"payment_id":null}', "payment_id").kind, "uncertain", "null expected field");
    eq(C.classify(201, '{"payment_id":"p_1"}', "payment_id").kind, "ok");
    eq(C.classify(200, "{}").kind, "ok", "object without expectation");
  });
  test("client", "empty 201 after commit: uncertain, same-key retry moves money once (PF-A1)", "ledger 1088-1092, 9009", function () {
    var srv = fakeServer();
    var inner = srv.fetch, emptyNext = true;
    srv.fetch = function (url, init) {
      return inner(url, init).then(function (res) {
        if (url === "/payments" && emptyNext) { emptyNext = false; return response(201, ""); }
        return res;
      });
    };
    var client = new C.ApiClient({ fetch: srv.fetch, tokens: new C.TokenStore(memoryStorage()) });
    var form = new C.Submission();
    var body = { to_handle: "bob", amount: 400 };
    var t1 = form.begin();
    return client.write("pay", "POST", "/payments", body, { expect: "payment_id" }).then(function (o) {
      form.settle(t1, o);
      eq([form.state, !!form.uncertain, form.error], ["uncertain", true, null]);
      var t2 = form.begin();
      return client.write("pay", "POST", "/payments", body, { expect: "payment_id" }).then(function (o2) {
        form.settle(t2, o2);
        eq([o2.status, form.state, form.uncertain, form.error], [200, "done", null, null]);
        eq([srv.payments.length, srv.balance], [1, 9600]);
      });
    });
  });

  function memoryStorage() {
    var m = {};
    return {
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(m, k) ? m[k] : null; },
      setItem: function (k, v) { m[k] = String(v); },
      removeItem: function (k) { delete m[k]; }
    };
  }
  function response(status, body) {
    var text = body === undefined ? "" : (typeof body === "string" ? body : JSON.stringify(body));
    return { status: status, text: function () { return Promise.resolve(text); } };
  }

  // A tiny in-memory stand-in for the stage-1 payment endpoint with §7 replay
  // semantics, plus switches to lose the response after commit.
  function fakeServer() {
    var s = { balance: 10000, payments: [], keys: {}, loseNextResponse: false, failNextBeforeCommit: false, calls: [] };
    s.fetch = function (url, init) {
      s.calls.push({ url: url, init: init });
      if (s.failNextBeforeCommit) { s.failNextBeforeCommit = false; return Promise.reject(new TypeError("Failed to fetch")); }
      if (init.method === "GET" && url === "/me") return Promise.resolve(response(200, { balance: s.balance }));
      if (init.method === "POST" && url === "/payments") {
        var key = init.headers["Idempotency-Key"];
        if (!key) return Promise.resolve(response(400, { error: { code: "missing_idempotency_key", message: "" } }));
        var body = JSON.parse(init.body);
        var canon = C.canonicalJson(body);
        var prior = s.keys[key];
        var res;
        if (prior && prior.canon !== canon) res = response(409, { error: { code: "idempotency_key_reuse", message: "" } });
        else if (prior) res = response(200, prior.payment);
        else if (body.amount > s.balance) res = response(409, { error: { code: "insufficient_funds", message: "" } });
        else {
          s.balance -= body.amount;
          var p = { payment_id: "p_" + (s.payments.length + 1), amount: body.amount };
          s.payments.push(p);
          s.keys[key] = { canon: canon, payment: p };
          res = response(201, p);
        }
        if (s.loseNextResponse) { s.loseNextResponse = false; return Promise.reject(new TypeError("connection reset")); }
        return Promise.resolve(res);
      }
      return Promise.resolve(response(404, { error: { code: "not_found", message: "" } }));
    };
    return s;
  }

  test("client", "sends bearer token, JSON body and Idempotency-Key", "stage-1 §6, §7", function () {
    var srv = fakeServer();
    var tokens = new C.TokenStore(memoryStorage());
    tokens.set("tok-1");
    var client = new C.ApiClient({ fetch: srv.fetch, tokens: tokens });
    return client.write("pay", "POST", "/payments", { to_handle: "bob", amount: 100 }).then(function (o) {
      var h = srv.calls[0].init.headers;
      eq(h["Authorization"], "Bearer tok-1");
      eq(h["Content-Type"], "application/json; charset=utf-8");
      ok(h["Idempotency-Key"] && h["Idempotency-Key"] === o.idempotencyKey, "key sent");
      eq(o.kind, "ok");
    });
  });
  test("client", "unchanged pay form submitted twice moves money once", IDEM, function () {
    var srv = fakeServer();
    var client = new C.ApiClient({ fetch: srv.fetch, tokens: new C.TokenStore(memoryStorage()) });
    var body = { to_handle: "bob", amount: 1500, note: "", visibility: "public" };
    return client.write("pay", "POST", "/payments", body).then(function (a) {
      return client.write("pay", "POST", "/payments", body).then(function (b) {
        eq([a.status, b.status], [201, 200]);
        eq(srv.payments.length, 1);
        eq(srv.balance, 8500);
        return client.write("pay", "POST", "/payments", { to_handle: "bob", amount: 1500, note: "again", visibility: "public" });
      }).then(function (c) {
        eq(c.status, 201, "changed note is a new payment");
        eq(srv.payments.length, 2);
      });
    });
  });
  test("client", "lost response after commit -> uncertain; retry replays once and clears", "stage-2 'If a payment response is lost ... show pay-uncertain'", function () {
    var srv = fakeServer();
    var client = new C.ApiClient({ fetch: srv.fetch, tokens: new C.TokenStore(memoryStorage()) });
    var form = new C.Submission();
    var body = { to_handle: "bob", amount: 700, note: "", visibility: "private" };
    srv.loseNextResponse = true;
    var t1 = form.begin();
    return client.write("pay", "POST", "/payments", body).then(function (o) {
      form.settle(t1, o);
      eq(form.state, "uncertain");
      ok(form.uncertain && !form.error, "uncertain shown, error absent");
      eq(srv.payments.length, 1, "server did commit");
      var t2 = form.begin();
      return client.write("pay", "POST", "/payments", body).then(function (o2) {
        form.settle(t2, o2);
        eq(o2.status, 200, "replay");
        eq(form.state, "done");
        ok(!form.uncertain && !form.error, "both cleared");
        eq(srv.payments.length, 1, "moved exactly once");
        eq(srv.balance, 9300);
        eq(srv.calls[0].init.headers["Idempotency-Key"], srv.calls[1].init.headers["Idempotency-Key"]);
        eq(srv.calls[0].init.body, srv.calls[1].init.body, "same body");
      });
    });
  });
  test("client", "network failure before commit -> uncertain; retry commits once", OUTCOME, function () {
    var srv = fakeServer();
    var client = new C.ApiClient({ fetch: srv.fetch, tokens: new C.TokenStore(memoryStorage()) });
    var body = { to_handle: "bob", amount: 100 };
    srv.failNextBeforeCommit = true;
    return client.write("pay", "POST", "/payments", body).then(function (o) {
      eq(o.kind, "uncertain");
      return client.write("pay", "POST", "/payments", body);
    }).then(function (o2) {
      eq(o2.status, 201);
      eq(srv.payments.length, 1);
    });
  });
  test("client", "refusal shows the error, keeps no uncertainty", "stage-2 'A refused payment shows pay-error'", function () {
    var srv = fakeServer();
    var client = new C.ApiClient({ fetch: srv.fetch, tokens: new C.TokenStore(memoryStorage()) });
    var form = new C.Submission();
    var t = form.begin();
    return client.write("pay", "POST", "/payments", { to_handle: "bob", amount: 999999 }).then(function (o) {
      form.settle(t, o);
      eq(form.state, "refused");
      eq(form.error.code, "insufficient_funds");
      ok(!form.uncertain, "no uncertainty");
      eq(srv.payments.length, 0);
    });
  });
  test("client", "local validation never sends a request", PARSE, function () {
    var form = new C.Submission();
    var r = C.parseAmount("15.005", 2);
    ok(!r.ok, "rejected");
    form.reject(r.reason);
    eq(form.state, "refused");
    ok(form.error.message.length > 0, "message");
  });
  test("client", "timeout -> uncertain", OUTCOME, function () {
    var client = new C.ApiClient({
      fetch: function () { return new Promise(function () {}); },
      tokens: new C.TokenStore(memoryStorage()), timeoutMs: 30
    });
    return client.write("pay", "POST", "/payments", { amount: 1 }).then(function (o) {
      eq([o.kind, o.reason], ["uncertain", "timeout"]);
    });
  });
  test("client", "5xx -> uncertain", OUTCOME, function () {
    var client = new C.ApiClient({ fetch: function () { return Promise.resolve(response(502, "bad gateway")); }, tokens: new C.TokenStore(memoryStorage()) });
    return client.write("pay", "POST", "/payments", { amount: 1 }).then(function (o) { eq(o.kind, "uncertain"); });
  });
  test("client", "only the latest submission updates the form", OUTCOME, function () {
    var form = new C.Submission();
    var t1 = form.begin();
    var t2 = form.begin();
    ok(form.settle(t2, { kind: "ok", status: 201, data: {} }), "latest applies");
    ok(!form.settle(t1, { kind: "uncertain", status: 0 }), "stale ignored");
    eq(form.state, "done");
  });
  test("client", "token survives a new client (upgrade without reload)", "stage-2 'A browser signed in before that export/import upgrade must remain signed in'", function () {
    var storage = memoryStorage();
    var srv = { fetch: function () { return Promise.resolve(response(201, { user_id: "u_1", display_name: "Ada", token: "tok-9" })); } };
    var a = new C.ApiClient({ fetch: srv.fetch, tokens: new C.TokenStore(storage) });
    return a.signup("a@example.com", "correct horse", "Ada").then(function (o) {
      eq(o.kind, "ok");
      var b = new C.ApiClient({ tokens: new C.TokenStore(storage) });
      ok(b.isSignedIn(), "signed in");
      eq(b.tokens.get(), "tok-9");
      b.logout();
      ok(!a.isSignedIn(), "logout clears storage");
    });
  });
  test("client", "pending retry identity survives a server-side import", "stage-2 'The form and pending retry identity must survive the upgrade'", function () {
    var srv = fakeServer();
    var client = new C.ApiClient({ fetch: srv.fetch, tokens: new C.TokenStore(memoryStorage()) });
    var body = { to_handle: "bob", amount: 250 };
    srv.loseNextResponse = true;
    return client.write("pay", "POST", "/payments", body).then(function (o) {
      eq(o.kind, "uncertain");
      // Import restores the same state (same keys, same receipts) in a new process.
      var exported = JSON.parse(JSON.stringify({ balance: srv.balance, payments: srv.payments, keys: srv.keys }));
      var srv2 = fakeServer();
      srv2.balance = exported.balance; srv2.payments = exported.payments; srv2.keys = exported.keys;
      client._fetch = srv2.fetch;
      return client.write("pay", "POST", "/payments", body).then(function (o2) {
        eq(o2.status, 200, "original payment recovered");
        eq(o2.data.payment_id, "p_1");
        eq(srv2.balance, 9750);
      });
    });
  });
  test("client", "401 triggers the sign-out hook", "stage-1 §5 'unauthenticated'", function () {
    var hit = 0;
    var client = new C.ApiClient({
      fetch: function () { return Promise.resolve(response(401, { error: { code: "unauthenticated", message: "" } })); },
      tokens: new C.TokenStore(memoryStorage()), onUnauthenticated: function () { hit++; }
    });
    return client.get("/me").then(function (o) { eq([o.kind, o.code, hit], ["refused", "unauthenticated", 1]); });
  });

  // ------------------------------------------------------- latest wins --
  var LATEST = "stage-2 'Latest refresh wins: a delayed earlier read must not overwrite a later refresh'";
  test("refresh", "later refresh answering first is not overwritten by the earlier one", LATEST, function () {
    var seq = new C.LatestWins();
    var shown = null;
    var slow = seq.run(function () { return delay(40).then(function () { return "old"; }); }, function (v) { shown = v; });
    var fast = seq.run(function () { return delay(5).then(function () { return "new"; }); }, function (v) { shown = v; });
    return Promise.all([slow, fast]).then(function (applied) {
      eq(shown, "new");
      eq(applied, [false, true]);
      ok(!seq.pending(), "idle");
    });
  });
  test("refresh", "in-order responses both apply, last one stays", LATEST, function () {
    var seq = new C.LatestWins();
    var shown = [];
    var a = seq.run(function () { return delay(5).then(function () { return 1; }); }, function (v) { shown.push(v); });
    var b = seq.run(function () { return delay(20).then(function () { return 2; }); }, function (v) { shown.push(v); });
    return Promise.all([a, b]).then(function () { eq(shown, [1, 2]); });
  });
  test("refresh", "ordering is by start, not by value (a lower later balance wins)", LATEST, function () {
    var seq = new C.LatestWins();
    var shown = null;
    var a = seq.run(function () { return delay(30).then(function () { return 10000; }); }, function (v) { shown = v; });
    var b = seq.run(function () { return delay(5).then(function () { return 0; }); }, function (v) { shown = v; });
    return Promise.all([a, b]).then(function () { eq(shown, 0); });
  });
  test("refresh", "a failed later refresh still discards an earlier late answer", LATEST, function () {
    var seq = new C.LatestWins();
    var shown = "initial", failed = 0;
    var a = seq.run(function () { return delay(30).then(function () { return "stale"; }); }, function (v) { shown = v; });
    var b = seq.run(function () { return delay(5).then(function () { throw new Error("offline"); }); }, function (v) { shown = v; }, function () { failed++; });
    return Promise.all([a, b]).then(function () { eq([shown, failed], ["initial", 1]); });
  });
  test("refresh", "100 shuffled refreshes: the last started always wins", LATEST, function () {
    var seq = new C.LatestWins();
    var shown = -1;
    var runs = [];
    for (var i = 0; i < 100; i++) {
      (function (i) {
        runs.push(seq.run(function () { return delay(Math.floor(Math.random() * 25)).then(function () { return i; }); },
          function (v) { ok(v > shown, "monotonic"); shown = v; }));
      })(i);
    }
    return Promise.all(runs).then(function () { eq(shown, 99); });
  });
  test("refresh", "loadAll combines balance and feed into one refresh", "stage-2 'wallet-refresh refreshes the balance and feed'", function () {
    var srv = fakeServer();
    srv.fetch = (function (inner) {
      return function (url, init) {
        if (url === "/activity") return Promise.resolve(response(200, { payments: [], has_more: false }));
        return inner(url, init);
      };
    })(srv.fetch);
    var client = new C.ApiClient({ fetch: srv.fetch, tokens: new C.TokenStore(memoryStorage()) });
    return C.loadAll(client, { me: "/me", activity: "/activity" }).then(function (r) {
      eq(r.me.balance, 10000);
      eq(r.activity.has_more, false);
    });
  });

  // ------------------------------------------------------------ runner --
  function runAll() {
    var results = [];
    return cases.reduce(function (p, c) {
      return p.then(function () {
        return Promise.resolve().then(c.fn).then(
          function () { results.push({ group: c.group, name: c.name, ref: c.ref, pass: true }); },
          function (e) { results.push({ group: c.group, name: c.name, ref: c.ref, pass: false, error: String(e && e.message || e) }); });
      });
    }, Promise.resolve()).then(function () { return results; });
  }

  var exported = { runAll: runAll, count: function () { return cases.length; } };
  root.PocketfulSelftest = exported;

  if (typeof module === "object" && module.exports && typeof require === "function" && require.main === module) {
    runAll().then(function (results) {
      var failed = results.filter(function (r) { return !r.pass; });
      results.forEach(function (r) { console.log((r.pass ? "PASS " : "FAIL ") + r.group + ": " + r.name + (r.pass ? "" : " -- " + r.error)); });
      console.log((results.length - failed.length) + "/" + results.length + " passed");
      process.exitCode = failed.length ? 1 : 0;
    });
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
