/*
 * Pocketful client core: screen-independent logic shared by every page.
 * Plain JavaScript, no dependencies, no build step. Exposes `PocketfulCore`
 * on the global object (and as a CommonJS module when one is available).
 */
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- money --

  // Formats an integer count of minor units as "<decimal> <CODE>":
  // 10000 / 2 / EUR -> "100.00 EUR"; 1200 / 0 / JPY -> "1200 JPY".
  function formatAmount(minor, minorUnits, currency) {
    var digits = minorDigits(minor);
    var negative = digits.charAt(0) === "-";
    if (negative) digits = digits.slice(1);
    var mu = checkMinorUnits(minorUnits);
    var text = digits;
    if (mu > 0) {
      while (digits.length <= mu) digits = "0" + digits;
      text = digits.slice(0, digits.length - mu) + "." + digits.slice(digits.length - mu);
    }
    return (negative ? "-" : "") + text + (currency ? " " + currency : "");
  }

  // Parses a decimal typed by a person into exact minor units, without floats.
  // Returns {ok: true, minor} or {ok: false, reason}. Never rounds: input with
  // more than `minorUnits` decimal places is rejected.
  function parseAmount(text, minorUnits) {
    var mu = checkMinorUnits(minorUnits);
    if (typeof text !== "string") return { ok: false, reason: "Enter an amount." };
    var s = text.trim();
    if (s === "") return { ok: false, reason: "Enter an amount." };
    var m = /^(\d*)(?:\.(\d*))?$/.exec(s);
    if (!m || (m[1] === "" && !m[2])) {
      return { ok: false, reason: "Enter the amount as a number, for example " + exampleAmount(mu) + "." };
    }
    var whole = m[1] || "0";
    var frac = m[2] || "";
    if (frac.length > mu) {
      return {
        ok: false,
        reason: mu === 0
          ? "This currency has no decimal places."
          : "Use at most " + mu + " decimal place" + (mu === 1 ? "" : "s") + "."
      };
    }
    while (frac.length < mu) frac += "0";
    var digits = (whole + frac).replace(/^0+(?=\d)/, "");
    // 16 digits can exceed 2^53; anything that long is far beyond any valid amount.
    if (digits.length > 15) return { ok: false, reason: "That amount is too large." };
    return { ok: true, minor: Number(digits) };
  }

  function exampleAmount(mu) {
    return mu === 0 ? "15" : "15." + new Array(mu + 1).join("0");
  }

  var MAX_MINOR = 9007199254740992; // 2^53

  function minorDigits(minor) {
    if (typeof minor === "bigint") return minor.toString();
    // Balances may reach ±2^53 inclusive (stage-1 §4); every integer up to
    // that bound is exact in a double and String() prints it exactly.
    if (typeof minor === "number" && Number.isInteger(minor) && Math.abs(minor) <= MAX_MINOR) return String(minor);
    if (typeof minor === "string" && /^-?\d+$/.test(minor)) return minor.replace(/^(-?)0+(?=\d)/, "$1");
    throw new TypeError("amount must be an integer count of minor units");
  }

  function checkMinorUnits(mu) {
    if (!Number.isInteger(mu) || mu < 0 || mu > 18) throw new TypeError("minor_units must be a small non-negative integer");
    return mu;
  }

  // ---------------------------------------------------------------- split --

  // Equal split (stage-1 §9): whole units, exact sum, shares differ by at most
  // one, and the larger shares go to the first participants in order.
  function splitShares(amount, count) {
    if (!Number.isSafeInteger(amount) || amount < 0) throw new TypeError("amount must be a non-negative integer");
    if (!Number.isInteger(count) || count < 1) throw new TypeError("count must be a positive integer");
    var base = Math.floor(amount / count);
    var extra = amount - base * count;
    var shares = [];
    for (var i = 0; i < count; i++) shares.push(base + (i < extra ? 1 : 0));
    return shares;
  }

  // Normalises one typed handle: surrounding space and a leading "@" are not
  // part of a handle.
  function normalizeHandle(text) {
    return String(text == null ? "" : text).trim().replace(/^@/, "");
  }

  // "ada, bob,cy" -> ["ada", "bob", "cy"], in the order given. Empty entries
  // (a trailing comma, a doubled comma) are dropped; duplicates are kept so
  // the server can refuse them.
  function parseHandles(text) {
    return String(text == null ? "" : text)
      .split(",")
      .map(normalizeHandle)
      .filter(function (h) { return h !== ""; });
  }

  // The preview the split form shows before posting: one share per handle, in
  // order, exactly as the server computes them.
  function splitPreview(amountMinor, handles) {
    var shares = splitShares(amountMinor, handles.length);
    return handles.map(function (h, i) { return { handle: h, amount: shares[i] }; });
  }

  // ------------------------------------------------------ canonical bodies --

  // Same JSON value -> same string, whatever the key order.
  function canonicalJson(value) {
    if (value === null || typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
    return "{" + Object.keys(value).sort().filter(function (k) {
      return value[k] !== undefined;
    }).map(function (k) {
      return JSON.stringify(k) + ":" + canonicalJson(value[k]);
    }).join(",") + "}";
  }

  // `cryptoImpl` defaults to the platform's Web Crypto; tests inject one.
  function newKey(cryptoImpl) {
    var c = cryptoImpl || root.crypto;
    if (c && typeof c.randomUUID === "function") return c.randomUUID();
    if (c && typeof c.getRandomValues === "function") {
      var bytes = new Uint8Array(16);
      c.getRandomValues(bytes);
      return Array.prototype.map.call(bytes, function (b) { return (b + 256).toString(16).slice(1); }).join("");
    }
    // Last resort for environments without Web Crypto (never a modern browser).
    return Date.now().toString(36) + "-" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
  }

  // ------------------------------------------------------- idempotency keys --

  // One slot per form. A submission whose method, path, body and raw form
  // text (`identity`) equal the previous submission from the same slot reuses
  // its key, so a resubmit of an unchanged form (or a retry after a lost
  // response) replays instead of moving money again. Any change mints a new
  // key, including a raw edit that normalises to the same body ("15" ->
  // "15.00", "bob" -> "@bob").
  function KeyRing(keyFactory) {
    this._slots = Object.create(null);
    this._newKey = keyFactory || newKey;
  }
  KeyRing.prototype.keyFor = function (slot, method, path, body, identity) {
    var fingerprint = method + " " + path + " " + canonicalJson(body === undefined ? null : body) +
      " " + canonicalJson(identity === undefined ? null : identity);
    var current = this._slots[slot];
    if (current && current.fingerprint === fingerprint) return current.key;
    var key = this._newKey();
    this._slots[slot] = { fingerprint: fingerprint, key: key };
    return key;
  };
  KeyRing.prototype.forget = function (slot) { delete this._slots[slot]; };
  KeyRing.prototype.clear = function () { this._slots = Object.create(null); };

  // ----------------------------------------------------------- token store --

  var TOKEN_KEY = "pocketful.token";

  // Bearer token in localStorage: it survives reloads and a server-side
  // export/import upgrade (the token itself is preserved by import).
  function TokenStore(storage) {
    this._storage = storage !== undefined ? storage : safeLocalStorage();
    this._memory = null;
  }
  TokenStore.prototype.get = function () {
    if (this._storage) {
      try { return this._storage.getItem(TOKEN_KEY); } catch (e) { /* fall through */ }
    }
    return this._memory;
  };
  TokenStore.prototype.set = function (token) {
    this._memory = token;
    if (this._storage) {
      try { this._storage.setItem(TOKEN_KEY, token); } catch (e) { /* memory only */ }
    }
  };
  TokenStore.prototype.clear = function () {
    this._memory = null;
    if (this._storage) {
      try { this._storage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ }
    }
  };

  function safeLocalStorage() {
    try { return root.localStorage || null; } catch (e) { return null; }
  }

  // ------------------------------------------------------------ API client --

  // Every call resolves (never rejects) to one of three outcomes:
  //   {kind: "ok", status, data}            2xx whose body is a JSON object
  //                                          (carrying `expect`, when given)
  //   {kind: "refused", status, code, message, data}
  //                                          4xx: the server definitely said no
  //   {kind: "uncertain", status, reason}   network error, timeout, 5xx, or a
  //                                          2xx whose body is empty, null, not
  //                                          JSON or not the expected object: the
  //                                          write may or may not have happened
  // A refused write can be corrected and resubmitted; an uncertain one must be
  // retried with the same key and body.
  function ApiClient(options) {
    options = options || {};
    this.baseUrl = options.baseUrl || "";
    this.tokens = options.tokens || new TokenStore();
    this.keys = options.keys || new KeyRing();
    this.timeoutMs = options.timeoutMs || 10000;
    this._fetch = options.fetch || (root.fetch ? root.fetch.bind(root) : null);
    this.onUnauthenticated = options.onUnauthenticated || null;
  }

  ApiClient.prototype.request = function (method, path, opts) {
    opts = opts || {};
    var self = this;
    var headers = { "Accept": "application/json" };
    var token = this.tokens.get();
    if (token && !opts.anonymous) headers["Authorization"] = "Bearer " + token;
    var init = { method: method, headers: headers, cache: "no-store" };
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json; charset=utf-8";
      init.body = JSON.stringify(opts.body);
    }
    if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

    var controller = typeof AbortController === "function" ? new AbortController() : null;
    if (controller) init.signal = controller.signal;
    var timer = null;
    var timedOut = false;
    var timeout = new Promise(function (resolve) {
      timer = setTimeout(function () {
        timedOut = true;
        if (controller) controller.abort();
        resolve({ kind: "uncertain", status: 0, reason: "timeout" });
      }, self.timeoutMs);
    });

    var call = Promise.resolve()
      .then(function () {
        if (!self._fetch) throw new Error("fetch unavailable");
        return self._fetch(self.baseUrl + path, init);
      })
      .then(function (res) {
        return res.text().then(function (text) { return classify(res.status, text, opts.expect); },
          function () { return res.status >= 400 && res.status < 500 ? classify(res.status, "") : { kind: "uncertain", status: res.status, reason: "unreadable response" }; });
      }, function (err) {
        return { kind: "uncertain", status: 0, reason: timedOut ? "timeout" : "network: " + (err && err.message || err) };
      });

    return Promise.race([call, timeout]).then(function (outcome) {
      clearTimeout(timer);
      if (outcome.kind === "refused" && outcome.status === 401 && !opts.anonymous && self.onUnauthenticated) {
        self.onUnauthenticated(outcome);
      }
      return outcome;
    });
  };

  // `expect` names a field the success body must carry (e.g. "payment_id").
  function classify(status, text, expect) {
    var data = null;
    var parsed = false;
    if (text) {
      try { data = JSON.parse(text); parsed = true; } catch (e) { data = null; }
    }
    if (status >= 200 && status < 300) {
      // A success we cannot read is not a confirmed outcome: an empty, null,
      // non-JSON or non-object body, or one missing the expected field, leaves
      // the write's result unknown.
      if (!parsed) return { kind: "uncertain", status: status, reason: "unreadable response" };
      if (data === null || typeof data !== "object" || Array.isArray(data)) {
        return { kind: "uncertain", status: status, reason: "unexpected response" };
      }
      if (expect && (data[expect] === undefined || data[expect] === null)) {
        return { kind: "uncertain", status: status, reason: "unexpected response" };
      }
      return { kind: "ok", status: status, data: data };
    }
    if (status >= 400 && status < 500) {
      var err = data && data.error ? data.error : {};
      return {
        kind: "refused",
        status: status,
        code: typeof err.code === "string" ? err.code : "http_" + status,
        message: typeof err.message === "string" ? err.message : "",
        data: data
      };
    }
    return { kind: "uncertain", status: status, reason: "server error " + status };
  }

  ApiClient.prototype.get = function (path, expect) { return this.request("GET", path, { expect: expect }); };

  // An idempotent write. `slot` names the form the write comes from; the key is
  // reused while method, path and body stay the same.
  // options.expect names the field a successful response must carry;
  // options.identity is the raw text of the form's fields (see KeyRing).
  ApiClient.prototype.write = function (slot, method, path, body, options) {
    options = options || {};
    var key = this.keys.keyFor(slot, method, path, body, options.identity);
    return this.request(method, path, { body: body, idempotencyKey: key, expect: options.expect }).then(function (outcome) {
      outcome.idempotencyKey = key;
      return outcome;
    });
  };

  // A write with no idempotency key (decline, cancel, void).
  ApiClient.prototype.post = function (path, body, expect) {
    return this.request("POST", path, { body: body === undefined ? {} : body, expect: expect });
  };

  ApiClient.prototype.signup = function (email, password, displayName) {
    return this._session(this.request("POST", "/auth/signup", {
      anonymous: true, expect: "token", body: { email: email, password: password, display_name: displayName }
    }));
  };
  ApiClient.prototype.login = function (email, password) {
    return this._session(this.request("POST", "/auth/login", {
      anonymous: true, expect: "token", body: { email: email, password: password }
    }));
  };
  ApiClient.prototype._session = function (promise) {
    var self = this;
    return promise.then(function (outcome) {
      if (outcome.kind === "ok" && outcome.data && typeof outcome.data.token === "string") {
        self.keys.clear();
        self.tokens.set(outcome.data.token);
      }
      return outcome;
    });
  };
  ApiClient.prototype.logout = function () {
    this.keys.clear();
    this.tokens.clear();
  };
  ApiClient.prototype.isSignedIn = function () { return !!this.tokens.get(); };

  // ----------------------------------------------- submission state machine --

  // Tracks what a form should show after each submission:
  //   "idle" | "pending" | "done" | "refused" | "uncertain"
  // `error` is set only for "refused", `uncertain` only for "uncertain"; a later
  // success clears both. Only the latest submission from the form updates it.
  function Submission(messages) {
    this.messages = messages || {};
    this.state = "idle";
    this.error = null;
    this.uncertain = null;
    this.result = null;
    this._ticket = 0;
  }
  Submission.prototype.begin = function () {
    this.state = "pending";
    return ++this._ticket;
  };
  Submission.prototype.settle = function (ticket, outcome) {
    if (ticket !== this._ticket) return false;
    if (outcome.kind === "ok") {
      this.state = "done"; this.error = null; this.uncertain = null; this.result = outcome.data;
    } else if (outcome.kind === "refused") {
      this.state = "refused"; this.uncertain = null; this.result = null;
      this.error = { code: outcome.code, message: describeRefusal(outcome, this.messages) };
    } else {
      this.state = "uncertain"; this.error = null; this.result = null;
      this.uncertain = "We couldn't confirm whether this went through. Submit again to retry safely — it will not be sent twice.";
    }
    return true;
  };
  // A local validation failure (e.g. "15.005") never reaches the server.
  Submission.prototype.reject = function (message) {
    ++this._ticket;
    this.state = "refused"; this.uncertain = null; this.result = null;
    this.error = { code: "local_validation", message: message };
  };

  var REFUSAL_TEXT = {
    insufficient_funds: "Not enough available funds for this.",
    not_found: "We couldn't find that.",
    self_payment: "You can't send money to yourself.",
    self_request: "You can't request money from yourself.",
    request_not_pending: "This request is no longer pending.",
    authorization_not_open: "This authorisation is no longer open.",
    authorization_expired: "This authorisation has expired.",
    capture_exceeds_authorization: "That is more than remains on this authorisation.",
    forbidden: "You're not allowed to do that.",
    unauthenticated: "Please sign in again.",
    email_taken: "That email is already registered.",
    handle_taken: "The handle from that email is already taken.",
    idempotency_key_reuse: "This conflicts with an earlier submission. Change a field and try again.",
    validation_failed: "Please check the details and try again."
  };
  // `messages` lets a form phrase a code for its own context.
  function describeRefusal(outcome, messages) {
    var own = messages && messages[outcome.code];
    if (typeof own === "function") own = own(outcome);
    return own || REFUSAL_TEXT[outcome.code] || outcome.message || "That didn't go through.";
  }

  // ---------------------------------------------------- latest refresh wins --

  // Orders reads by when they started. Each run() takes a ticket; a result is
  // applied only if no later-started run has already completed. A delayed
  // earlier response therefore never overwrites a later refresh, whatever the
  // order in which responses arrive. A failed later read still supersedes
  // earlier ones (their data is older than what the user asked for).
  function LatestWins() {
    this._issued = 0;
    this._completed = 0;
  }
  LatestWins.prototype.run = function (load, apply, fail) {
    var ticket = ++this._issued;
    var self = this;
    return Promise.resolve().then(load).then(function (value) {
      if (ticket <= self._completed) return false;
      self._completed = ticket;
      apply(value);
      return true;
    }, function (err) {
      if (ticket <= self._completed) return false;
      self._completed = ticket;
      if (fail) fail(err);
      return false;
    });
  };
  // True while a started read has not yet been superseded or applied.
  LatestWins.prototype.pending = function () { return this._issued > this._completed; };

  // Loads several endpoints as one refresh. `paths` maps a name to a path or
  // to [path, expectedField]. Resolves to {name: data}, or rejects with the
  // first outcome that was not ok.
  function loadAll(api, paths) {
    var names = Object.keys(paths);
    return Promise.all(names.map(function (n) {
      var p = paths[n];
      return Array.isArray(p) ? api.get(p[0], p[1]) : api.get(p);
    })).then(function (outcomes) {
      var out = {};
      for (var i = 0; i < names.length; i++) {
        if (outcomes[i].kind !== "ok") throw outcomes[i];
        out[names[i]] = outcomes[i].data;
      }
      return out;
    });
  }

  var api = {
    formatAmount: formatAmount,
    parseAmount: parseAmount,
    splitShares: splitShares,
    splitPreview: splitPreview,
    parseHandles: parseHandles,
    normalizeHandle: normalizeHandle,
    canonicalJson: canonicalJson,
    newKey: newKey,
    KeyRing: KeyRing,
    TokenStore: TokenStore,
    ApiClient: ApiClient,
    classify: classify,
    Submission: Submission,
    describeRefusal: describeRefusal,
    LatestWins: LatestWins,
    loadAll: loadAll
  };
  root.PocketfulCore = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
