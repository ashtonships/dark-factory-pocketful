/*
 * Pocketful screens: behaviour for every stage-2 route. Each HTML page sets
 * <body data-page="..."> and carries its static forms; this file fills in the
 * data-dependent parts and wires the forms. Structure only: the look lives in
 * theme.css.
 */
(function () {
  "use strict";
  var P = window.PocketfulCore;
  var api = new P.ApiClient({
    onUnauthenticated: function () { api.logout(); location.assign("/login"); }
  });
  var page = document.body.getAttribute("data-page");
  var ctx = { me: null };
  var seq = new P.LatestWins();

  // ------------------------------------------------------------ helpers --

  function $(sel, root) { return (root || document).querySelector(sel); }
  function tid(id, root) { return $('[data-testid="' + id + '"]', root); }

  // h("p", {class: "x", "data-testid": "y"}, "text", child, ...)
  function h(tag, attrs) {
    var el = document.createElement(tag);
    var a = attrs || {};
    Object.keys(a).forEach(function (k) {
      var v = a[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "on") Object.keys(v).forEach(function (ev) { el.addEventListener(ev, v[ev]); });
      else if (k === "text") el.textContent = v;
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : v);
    });
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(el, c); }); return; }
    el.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  function replace(el, children) {
    while (el.firstChild) el.removeChild(el.firstChild);
    append(el, children);
  }

  function money(minor) { return P.formatAmount(minor, ctx.me.minor_units, ctx.me.currency); }
  function decimal(minor) { return P.formatAmount(minor, ctx.me.minor_units, ""); }

  var dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  function when(iso) {
    var d = new Date(iso);
    return isNaN(d) ? iso : dateFmt.format(d);
  }
  function relative(iso) {
    var ms = new Date(iso).getTime() - Date.now();
    if (isNaN(ms)) return "";
    var mins = Math.round(Math.abs(ms) / 60000);
    var span = mins < 1 ? "under a minute" : mins < 90 ? mins + " min" : Math.round(mins / 60) + " h";
    return ms > 0 ? "in " + span : span + " ago";
  }

  function available(me) { return typeof me.available === "number" ? me.available : me.balance; }
  function heldOf(me) { return typeof me.held === "number" ? me.held : 0; }

  // ------------------------------------------------------- form outcomes --

  // Renders a Submission into its message slot: "<prefix>-error" only while
  // refused, "<prefix>-uncertain" only while uncertain, plus a quiet pending or
  // success line. `success` returns the confirmation text.
  function showOutcome(slot, sub, prefix, success) {
    var nodes = [];
    if (sub.state === "pending") nodes.push(h("p", { class: "notice notice-pending", role: "status", text: "Sending…" }));
    if (sub.error) nodes.push(h("p", { class: "notice notice-error", role: "alert", "data-testid": prefix + "-error", text: sub.error.message }));
    if (sub.uncertain) nodes.push(h("p", { class: "notice notice-uncertain", role: "status", "data-testid": prefix + "-uncertain", text: sub.uncertain }));
    if (sub.state === "done" && success) {
      var line = null;
      try { line = success(sub.result); } catch (e) { line = "Done."; }
      nodes.push(h("p", { class: "notice notice-success", role: "status", text: line }));
    }
    replace(slot, nodes);
  }

  function handleMessages(field) {
    return {
      not_found: function () { return "No one on Pocketful has that handle."; },
      validation_failed: "Check the " + field + ", amount and note (notes are up to 200 characters)."
    };
  }

  // ------------------------------------------------------------- shell --

  function renderShell() {
    var shell = $("#shell");
    if (!shell) return;
    var links = ctx.me
      ? [["/", "Wallet", "index"], ["/requests", "Requests", "requests"], ["/split", "Split", "split"], ["/authorizations", "Holds", "authorizations"]]
      : [["/login", "Sign in", "login"], ["/signup", "Create account", "signup"]];
    var nav = h("nav", { class: "nav", "aria-label": "Main" }, links.map(function (l) {
      return h("a", { href: l[0], "aria-current": page === l[2] ? "page" : null, text: l[1] });
    }));
    var user = ctx.me ? h("div", { class: "user" },
      h("span", { class: "user-name", "data-testid": "current-user", text: ctx.me.display_name }),
      h("span", { class: "user-handle" }, "@", h("span", { "data-testid": "current-handle", text: ctx.me.handle })),
      h("button", { type: "button", class: "button button-quiet", "data-testid": "logout-button", text: "Sign out",
        on: { click: function () { api.logout(); location.assign("/login"); } } })) : null;
    replace(shell, h("div", { class: "shell" },
      h("a", { class: "brand", href: ctx.me ? "/" : "/login", text: "Pocketful" }), nav, user));
  }

  function setCurrencyLabels() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-currency-label]"), function (el) {
      el.textContent = "Amount (" + ctx.me.currency + ")";
    });
    Array.prototype.forEach.call(document.querySelectorAll("input[data-amount-input]"), function (el) {
      el.placeholder = ctx.me.minor_units === 0 ? "0" : "0." + new Array(ctx.me.minor_units + 1).join("0");
    });
  }

  // ------------------------------------------------------------ wallet --

  function renderWallet(me) {
    var slot = $("#wallet");
    if (!slot) return;
    var held = heldOf(me);
    replace(slot, [
      h("div", { class: "wallet-main" },
        h("p", { class: "label", text: "Available to spend" }),
        h("p", { class: "amount amount-hero", "data-testid": "wallet-available", "data-amount": String(available(me)), text: money(available(me)) })),
      h("dl", { class: "wallet-sub" },
        h("div", null, h("dt", { text: "Total" }),
          h("dd", { "data-testid": "wallet-balance", "data-amount": String(me.balance), text: money(me.balance) })),
        held > 0 ? h("div", { class: "is-held" }, h("dt", { text: "Held for collection" }),
          h("dd", { "data-testid": "wallet-held", "data-amount": String(held), text: money(held) })) : null)
    ]);
  }

  // ----------------------------------------------------------- refresh --

  // One refresh per page: it loads /me plus the page's lists as a unit and
  // renders them, latest-started wins (pocketful-core LatestWins).
  var loaders = {};
  var renderers = [];
  function refresh() {
    var status = $("#refresh-status");
    if (status) replace(status, h("span", { class: "notice notice-pending", text: "Updating…" }));
    return seq.run(function () {
      return P.loadAll(api, Object.assign({ me: ["/me", "user_id"] }, loaders));
    }, function (data) {
      var first = !ctx.me;
      ctx.me = data.me;
      if (first) setCurrencyLabels();
      renderShell();
      renderers.forEach(function (r) { r(data); });
      if (status && !seq.pending()) replace(status, []);
    }, function () {
      if (status) replace(status, h("span", { class: "notice notice-error", role: "status", text: "Couldn't refresh. Check your connection and try again." }));
    });
  }

  // -------------------------------------------------- amount + handle forms --

  // Wires a pay-like form: "<prefix>-handle", "-amount", "-note", optional
  // "-visibility", "-submit". `keep` keeps the values (and the idempotency key)
  // after success so an unchanged resubmit replays instead of paying again.
  function moneyForm(opts) {
    var prefix = opts.prefix;
    var form = tid(prefix + "-submit").form;
    var slot = $("#" + prefix + "-messages");
    var sub = new P.Submission(opts.messages);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!ctx.me) return;
      var parsed = P.parseAmount(tid(prefix + "-amount").value, ctx.me.minor_units);
      if (!parsed.ok) { sub.reject(parsed.reason); showOutcome(slot, sub, prefix); return; }
      var body = {};
      body[opts.handleField] = P.normalizeHandle(tid(prefix + "-handle").value);
      body.amount = parsed.minor;
      body.note = tid(prefix + "-note").value;
      var vis = tid(prefix + "-visibility");
      if (vis) body.visibility = vis.value;
      // The key follows the raw text of every field: "15" -> "15.00" is a new submission.
      var identity = rawFields(form);
      var ticket = sub.begin();
      showOutcome(slot, sub, prefix);
      api.write(prefix, "POST", opts.path, body, { expect: opts.expect, identity: identity }).then(function (outcome) {
        if (sub.settle(ticket, outcome)) {
          if (outcome.kind === "ok" && !opts.keep) { form.reset(); api.keys.forget(prefix); }
          showOutcome(slot, sub, prefix, opts.success);
        }
        if (outcome.kind !== "uncertain") refresh();
      });
    });
  }

  // Raw text of every field in a form, by test id (or id), in DOM order.
  function rawFields(root) {
    var out = {};
    Array.prototype.forEach.call(root.querySelectorAll("input, select, textarea"), function (el) {
      var name = el.getAttribute("data-testid") || el.id || el.name;
      if (!name) return;
      out[name] = el.type === "checkbox" ? (el.checked ? "on" : "off") : el.value;
    });
    return out;
  }

  // ------------------------------------------------------------ pages --

  function initWalletPage() {
    var refreshBtn = tid("wallet-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", refresh);
    renderers.push(function (d) { renderWallet(d.me); });
  }

  function initAuthorizeForm() {
    if (!tid("authorize-submit")) return;
    moneyForm({
      prefix: "authorize", path: "/authorizations", handleField: "to_handle", keep: true, expect: "authorization_id",
      messages: Object.assign(handleMessages("handle"), {
        insufficient_funds: "Not enough available funds to hold this amount.",
        self_payment: "You can't hold money for yourself."
      }),
      success: function (a) { return "Holding " + money(a.amount) + " for @" + a.to_handle + " until " + when(a.expires_at) + "."; }
    });
  }

  function initIndex() {
    initWalletPage();
    loaders.activity = ["/activity?limit=200", "payments"];
    moneyForm({
      prefix: "pay", path: "/payments", handleField: "to_handle", keep: true, expect: "payment_id",
      messages: Object.assign(handleMessages("handle"), { insufficient_funds: "Not enough available funds for this payment." }),
      success: function (p) { return "Sent " + money(p.amount) + " to @" + p.to_handle + "."; }
    });
    moneyForm({
      prefix: "request", path: "/requests", handleField: "payer_handle", keep: false, expect: "request_id",
      messages: handleMessages("handle"),
      success: function (r) { return "Asked @" + r.payer_handle + " for " + money(r.amount) + "."; }
    });
    initAuthorizeForm();
    renderers.push(function (d) { renderActivity(d.activity); });
  }

  function renderActivity(feed) {
    var slot = $("#activity");
    var items = feed.payments || [];
    if (!items.length) {
      replace(slot, h("p", { class: "empty", "data-testid": "empty-activity", text: "No payments yet. Money you send or receive, and public payments, show up here." }));
      return;
    }
    replace(slot, [
      h("ul", { class: "list", "data-testid": "activity-list" }, items.map(function (p) {
        var dir = p.from_user_id === ctx.me.user_id ? "out" : p.to_user_id === ctx.me.user_id ? "in" : "other";
        return h("li", { class: "item item-" + dir, "data-testid": "activity-item-" + p.payment_id, "data-visibility": p.visibility },
          h("div", { class: "item-main" },
            h("p", { class: "parties", "data-testid": "activity-parties-" + p.payment_id }, "@" + p.from_handle + " → @" + p.to_handle),
            h("p", { class: "note", "data-testid": "activity-note-" + p.payment_id, text: p.note }),
            h("p", { class: "meta" },
              h("span", { class: "badge badge-" + dir, text: dir === "out" ? "Sent" : dir === "in" ? "Received" : "Between others" }),
              h("span", { class: "badge badge-" + p.visibility, text: p.visibility === "private" ? "Private" : "Public" }),
              h("time", { datetime: p.created_at, text: when(p.created_at) }))),
          h("p", { class: "amount amount-" + dir, "data-testid": "activity-amount-" + p.payment_id, text: money(p.amount) }));
      })),
      feed.has_more ? h("p", { class: "meta", text: "Showing the latest " + items.length + " payments." }) : null
    ]);
  }

  // -------------------------------------------------------- requests --

  function initRequests() {
    loaders.incoming = ["/requests?direction=incoming&limit=200", "requests"];
    loaders.outgoing = ["/requests?direction=outgoing&limit=200", "requests"];
    var slot = $("#request-messages");
    var sub = new P.Submission({
      request_not_pending: "That request was already settled or withdrawn. The list is up to date now.",
      insufficient_funds: "Not enough available funds to pay this request.",
      forbidden: "Only the person asked can pay or decline; only the requester can cancel."
    });
    var keepVisibility = {};

    function act(kind, r) {
      var ticket = sub.begin();
      showOutcome(slot, sub, "request");
      var call;
      if (kind === "pay") {
        var sel = tid("request-visibility-" + r.request_id);
        var vis = sel ? sel.value : "public";
        call = api.write("reqpay:" + r.request_id, "POST", "/requests/" + encodeURIComponent(r.request_id) + "/pay",
          { visibility: vis }, { expect: "payment_id", identity: { visibility: vis } });
      } else {
        call = api.post("/requests/" + encodeURIComponent(r.request_id) + "/" + kind, {}, "request_id");
      }
      call.then(function (outcome) {
        if (sub.settle(ticket, outcome)) {
          showOutcome(slot, sub, "request", function () {
            return kind === "pay" ? "Paid " + money(r.amount) + " to @" + r.requester_handle + "."
              : kind === "decline" ? "Declined @" + r.requester_handle + "'s request."
                : "Cancelled your request to @" + r.payer_handle + ".";
          });
        }
        if (outcome.kind !== "uncertain") refresh();
      });
    }

    function item(r, incoming) {
      var pending = r.status === "pending";
      var who = incoming ? "@" + r.requester_handle + " asked you" : "You asked @" + r.payer_handle;
      var actions = null;
      if (pending && incoming) {
        var id = "request-visibility-" + r.request_id;
        actions = h("div", { class: "actions" },
          h("label", { class: "inline-label", for: id, text: "Show payment as" }),
          h("select", { id: id, "data-testid": id, on: { change: function (e) { keepVisibility[r.request_id] = e.target.value; } } },
            h("option", { value: "public", text: "Public", selected: keepVisibility[r.request_id] !== "private" }),
            h("option", { value: "private", text: "Private", selected: keepVisibility[r.request_id] === "private" })),
          h("button", { type: "button", class: "button button-primary", "data-testid": "request-pay-" + r.request_id,
            text: "Pay " + money(r.amount), on: { click: function () { act("pay", r); } } }),
          h("button", { type: "button", class: "button button-quiet", "data-testid": "request-decline-" + r.request_id,
            text: "Decline", on: { click: function () { act("decline", r); } } }));
      } else if (pending) {
        actions = h("div", { class: "actions" },
          h("button", { type: "button", class: "button button-quiet", "data-testid": "request-cancel-" + r.request_id,
            text: "Cancel request", on: { click: function () { act("cancel", r); } } }));
      }
      return h("li", { class: "item status-" + r.status, "data-testid": "request-item-" + r.request_id, "data-status": r.status },
        h("div", { class: "item-main" },
          h("p", { class: "parties", text: who }),
          h("p", { class: "note", text: r.note }),
          h("p", { class: "meta" },
            h("span", { class: "badge badge-" + r.status, text: r.status.charAt(0).toUpperCase() + r.status.slice(1) }),
            h("time", { datetime: r.created_at, text: when(r.created_at) }))),
        h("p", { class: "amount", "data-testid": "request-amount-" + r.request_id, text: money(r.amount) }),
        actions);
    }

    renderers.push(function (d) {
      var inc = d.incoming.requests || [], out = d.outgoing.requests || [];
      replace(tid("incoming-list"), inc.length ? inc.map(function (r) { return item(r, true); })
        : h("li", { class: "empty-row", text: "No one has asked you for money." }));
      replace(tid("outgoing-list"), out.length ? out.map(function (r) { return item(r, false); })
        : h("li", { class: "empty-row", text: "You haven't asked anyone for money." }));
      var empty = $("#requests-empty");
      replace(empty, !inc.length && !out.length
        ? h("p", { class: "empty", "data-testid": "empty-requests", text: "No requests yet. Ask someone for money from your wallet, or split a bill." })
        : []);
    });
  }

  // ------------------------------------------------------------ split --

  function initSplit() {
    var amount = tid("split-amount"), handles = tid("split-handles"), note = tid("split-note");
    var slot = $("#split-messages");
    var sub = new P.Submission({
      not_found: "One of those handles doesn't exist.",
      validation_failed: "Check the amount, the handles (each person once) and the note."
    });

    function current() {
      if (!ctx.me) return null;
      var parsed = P.parseAmount(amount.value, ctx.me.minor_units);
      var list = P.parseHandles(handles.value);
      return { parsed: parsed, handles: list };
    }

    function preview() {
      var box = tid("split-preview");
      var c = current();
      if (!c) return;
      if (!c.handles.length || !c.parsed.ok || c.parsed.minor < 1) {
        replace(box, h("p", { class: "meta", text: "Enter an amount and the people sharing it to see each share." }));
        return;
      }
      replace(box, h("ul", { class: "shares" }, P.splitPreview(c.parsed.minor, c.handles).map(function (s) {
        return h("li", null,
          h("span", { class: "share-who" }, "@" + s.handle, s.handle === ctx.me.handle ? " (you)" : ""),
          h("span", { class: "amount", "data-testid": "split-share-" + s.handle, text: money(s.amount) }));
      })));
    }
    amount.addEventListener("input", preview);
    handles.addEventListener("input", preview);

    tid("split-submit").form.addEventListener("submit", function (e) {
      e.preventDefault();
      var c = current();
      if (!c) return;
      if (!c.parsed.ok) { sub.reject(c.parsed.reason); showOutcome(slot, sub, "split"); return; }
      if (!c.handles.length) { sub.reject("Add at least one handle."); showOutcome(slot, sub, "split"); return; }
      var dup = c.handles.filter(function (x, i) { return c.handles.indexOf(x) !== i; });
      if (dup.length) { sub.reject("@" + dup[0] + " is listed twice. Each person can appear once."); showOutcome(slot, sub, "split"); return; }
      var body = { amount: c.parsed.minor, participant_handles: c.handles, note: note.value };
      var identity = rawFields(tid("split-submit").form);
      var ticket = sub.begin();
      showOutcome(slot, sub, "split");
      api.write("split", "POST", "/splits", body, { expect: "split_id", identity: identity }).then(function (outcome) {
        if (sub.settle(ticket, outcome)) {
          if (outcome.kind === "ok") { tid("split-submit").form.reset(); api.keys.forget("split"); preview(); }
          showOutcome(slot, sub, "split", function (s) {
            var n = s.requests.length;
            return n ? "Split " + money(s.amount) + ". Sent " + n + " request" + (n === 1 ? "" : "s") + "."
              : "Split " + money(s.amount) + ". Nobody else to ask.";
          });
        }
        if (outcome.kind !== "uncertain") refresh();
      });
    });
    renderers.push(function () { preview(); });
  }

  // --------------------------------------------------- authorizations --

  function initAuthorizations() {
    initWalletPage();
    initAuthorizeForm();
    loaders.auths = ["/authorizations?limit=200", "authorizations"];
    var slot = $("#authorization-messages");
    var sub = new P.Submission({
      authorization_not_open: "This hold is already closed. The list is up to date now.",
      authorization_expired: "This hold has expired.",
      capture_exceeds_authorization: "That is more than remains on this hold.",
      validation_failed: "Enter an amount of at least the smallest unit.",
      forbidden: "Only the recipient can collect; only the payer can release."
    });
    var typed = {};

    function act(kind, a) {
      var ticket;
      if (kind === "capture") {
        var parsed = P.parseAmount(tid("authorization-capture-amount-" + a.authorization_id).value, ctx.me.minor_units);
        if (!parsed.ok) { sub.reject(parsed.reason); showOutcome(slot, sub, "authorization"); return; }
        var body = { amount: parsed.minor };
        var keep = tid("authorization-keep-open-" + a.authorization_id);
        if (keep && keep.checked) body.final = false;
        var slotName = "capture:" + a.authorization_id;
        var identity = { amount: tid("authorization-capture-amount-" + a.authorization_id).value, keep: keep && keep.checked ? "on" : "off" };
        ticket = sub.begin();
        showOutcome(slot, sub, "authorization");
        api.write(slotName, "POST", "/authorizations/" + encodeURIComponent(a.authorization_id) + "/capture", body,
          { expect: "payment_id", identity: identity })
          .then(function (o) {
            // A confirmed capture closes that intent: the next capture is a new one.
            if (o.kind === "ok") api.keys.forget(slotName);
            done(ticket, o, function (p) { return "Collected " + money(p.amount) + " from @" + a.from_handle + "."; }); });
      } else {
        ticket = sub.begin();
        showOutcome(slot, sub, "authorization");
        api.post("/authorizations/" + encodeURIComponent(a.authorization_id) + "/void", {}, "authorization_id")
          .then(function (o) { done(ticket, o, function () { return "Released the hold for @" + a.to_handle + "."; }); });
      }
    }
    function done(ticket, outcome, success) {
      if (sub.settle(ticket, outcome)) {
        if (outcome.kind === "ok") typed = {};
        showOutcome(slot, sub, "authorization", success);
      }
      if (outcome.kind !== "uncertain") refresh();
    }

    function item(a) {
      var id = a.authorization_id;
      var outgoing = a.from_user_id === ctx.me.user_id;
      var open = a.status === "open";
      var remaining = typeof a.remaining_amount === "number" ? a.remaining_amount : (open ? a.amount - (a.captured_amount || 0) : 0);
      var actions = null;
      if (open && !outgoing) {
        var inputId = "authorization-capture-amount-" + id, keepId = "authorization-keep-open-" + id;
        actions = h("div", { class: "actions" },
          h("div", { class: "field field-inline" },
            h("label", { for: inputId, text: "Collect (" + ctx.me.currency + ")" }),
            h("input", { id: inputId, "data-testid": inputId, inputmode: "decimal", autocomplete: "off",
              value: typed[id] !== undefined ? typed[id] : decimal(remaining),
              on: { input: function (e) { typed[id] = e.target.value; } } })),
          h("label", { class: "check" }, h("input", { type: "checkbox", id: keepId, "data-testid": keepId }), " Keep the rest held"),
          h("button", { type: "button", class: "button button-primary", "data-testid": "authorization-capture-" + id,
            text: "Collect", on: { click: function () { act("capture", a); } } }));
      } else if (open) {
        actions = h("div", { class: "actions" },
          h("button", { type: "button", class: "button button-quiet", "data-testid": "authorization-void-" + id,
            text: "Release hold", on: { click: function () { act("void", a); } } }));
      }
      var captured = a.captured_amount || 0;
      return h("li", { class: "item status-" + a.status, "data-testid": "authorization-item-" + id, "data-status": a.status },
        h("div", { class: "item-main" },
          h("p", { class: "parties", text: outgoing ? "You → @" + a.to_handle : "@" + a.from_handle + " → you" }),
          h("p", { class: "note", text: a.note }),
          h("p", { class: "meta" },
            h("span", { class: "badge badge-" + a.status, text: a.status.charAt(0).toUpperCase() + a.status.slice(1) }),
            h("span", { class: "badge badge-" + a.visibility, text: a.visibility === "private" ? "Private" : "Public" }),
            open && captured > 0 ? h("span", { text: "Collected so far " + money(captured) + ", " + money(remaining) + " still held" }) : null),
          h("p", { class: "meta" }, open ? "Expires " : "Expiry ",
            h("time", { "data-testid": "authorization-expires-" + id, datetime: a.expires_at, text: a.expires_at }),
            open ? " (" + relative(a.expires_at) + ")" : "")),
        h("div", { class: "item-amounts" },
          h("p", { class: "amount", "data-testid": "authorization-amount-" + id, text: money(a.amount) }),
          a.status === "captured" ? h("p", { class: "meta" }, "Collected ",
            h("span", { "data-testid": "authorization-captured-" + id, text: money(captured) })) : null),
        actions);
    }

    renderers.push(function (d) {
      var list = d.auths.authorizations || [];
      var box = $("#authorizations");
      replace(box, list.length
        ? h("ul", { class: "list", "data-testid": "authorization-list" }, list.map(item))
        : h("p", { class: "empty", "data-testid": "empty-authorizations", text: "No holds yet. Hold money for someone and they can collect it later." }));
    });
  }

  // ----------------------------------------------------------- auth pages --

  function initAuthPage(kind) {
    var form = tid(kind + "-submit").form;
    var slot = $("#auth-messages");
    var sub = new P.Submission({
      unauthenticated: "That email and password don't match an account.",
      validation_failed: kind === "signup" ? "Use a valid email and a password of at least 8 characters." : "Enter your email and password.",
      handle_taken: "An account already uses the handle made from that email. Try a different email."
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ticket = sub.begin();
      replace(slot, h("p", { class: "notice notice-pending", role: "status", text: kind === "signup" ? "Creating your account…" : "Signing in…" }));
      var call = kind === "signup"
        ? api.signup(tid("signup-email").value.trim(), tid("signup-password").value, tid("signup-display-name").value.trim())
        : api.login(tid("login-email").value.trim(), tid("login-password").value);
      call.then(function (outcome) {
        if (!sub.settle(ticket, outcome)) return;
        if (outcome.kind === "ok") { location.assign("/"); return; }
        var text = sub.error ? sub.error.message : "We couldn't reach Pocketful. Check your connection and try again.";
        replace(slot, h("p", { class: "notice notice-error", role: "alert", "data-testid": "auth-error", text: text }));
      });
    });
  }

  // -------------------------------------------------------------- boot --

  var protectedPages = { index: initIndex, requests: initRequests, split: initSplit, authorizations: initAuthorizations };
  if (protectedPages[page]) {
    if (!api.isSignedIn()) { location.replace("/login"); return; }
    protectedPages[page]();
    renderShell();
    refresh();
  } else {
    // A stale token on the sign-in screens just signs out; no redirect loop.
    api.onUnauthenticated = function () { api.logout(); };
    initAuthPage(page);
    renderShell();
    if (api.isSignedIn()) {
      api.get("/me").then(function (o) { if (o.kind === "ok") { ctx.me = o.data; renderShell(); } });
    }
  }
})();
