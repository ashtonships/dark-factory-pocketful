/*
 * Pocketful screens: behaviour for every stage-2 route. Each HTML page sets
 * <body data-page="..."> and carries its static forms; this file fills in the
 * data-dependent parts and wires the forms. The look lives in theme.css.
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

  // Small stroke icons, drawn inline (no icon font, nothing fetched).
  var ICONS = {
    wallet: "M3 7.5A2.5 2.5 0 0 1 5.5 5H18v3M3 7.5V17a2 2 0 0 0 2 2h14a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1H5.5A2.5 2.5 0 0 1 3 7.5ZM16 13.5h.01",
    requests: "M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm2 8h6m-6 4h6m-6-8h3",
    split: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-6 9a6 6 0 0 1 12 0M17 11a2.5 2.5 0 1 0 0-5M21 20a5 5 0 0 0-4-4.9",
    lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
    refresh: "M20 11a8 8 0 0 0-14.3-4.9L4 8m0-4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16m0 4v-4h-4",
    out: "M7 17 17 7M9 7h8v8",
    in: "M17 7 7 17m8 0H7V9",
    across: "M4 12h16m-4-4 4 4-4 4",
    up: "M12 19V5m-6 6 6-6 6 6",
    down: "M12 5v14m6-6-6 6-6-6",
    check: "M5 12.5 10 17l9-10",
    alert: "M12 8v5m0 3.5h.01M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z",
    error: "M12 7.5v5.5m0 3.5h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
    info: "M12 11v5.5m0-9h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
    ban: "M5.6 5.6l12.8 12.8M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
    doc: "M7 3h7l4 4v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm2 9h6m-6 4h4",
    eye: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Zm9.5 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"
  };
  function icon(name, cls) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("class", "icon" + (cls ? " " + cls : ""));
    var path = document.createElementNS(ns, "path");
    path.setAttribute("d", ICONS[name]);
    svg.appendChild(path);
    return svg;
  }

  function money(minor) { return P.formatAmount(minor, ctx.me.minor_units, ctx.me.currency); }
  function decimal(minor) { return P.formatAmount(minor, ctx.me.minor_units, ""); }

  var dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  function when(iso) {
    var d = new Date(iso);
    return isNaN(d) ? iso : dateFmt.format(d);
  }
  function relative(iso) {
    var ms = new Date(iso).getTime() - Date.now();
    if (isNaN(ms)) return "";
    var mins = Math.round(Math.abs(ms) / 60000);
    var span = mins < 1 ? "under a minute"
      : mins < 60 ? mins + " min"
        : mins < 36 * 60 ? Math.round(mins / 60) + (Math.round(mins / 60) === 1 ? " hour" : " hours")
          : Math.round(mins / 1440) + " days";
    return ms > 0 ? "in " + span : span === "under a minute" ? "just now" : span + " ago";
  }
  function initial(name) { return (String(name || "?").trim().charAt(0) || "?").toUpperCase(); }
  function avatar(name) { return h("span", { class: "avatar", "aria-hidden": "true", text: initial(name) }); }
  function pill(kind, label) { return h("span", { class: "pill pill-" + kind, text: label }); }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  function available(me) { return typeof me.available === "number" ? me.available : me.balance; }
  function heldOf(me) { return typeof me.held === "number" ? me.held : 0; }

  // Considered empty state: icon, title, one line.
  function emptyState(testid, iconName, title, text, tag) {
    return h(tag || "div", { class: "empty", "data-testid": testid },
      h("span", { class: "empty-icon" }, icon(iconName)),
      h("p", { class: "empty-title", text: title }),
      h("p", { class: "empty-text", text: text }));
  }

  // ------------------------------------------------------- form outcomes --

  var UNCERTAIN = {
    pay: "Payment result unknown. Retry with the same details.",
    request: "Result unknown. Retry with the same details.",
    authorize: "Hold result unknown. Retry with the same details.",
    split: "Split result unknown. Retry with the same details.",
    authorization: "Result unknown. Retry with the same details."
  };

  function notice(kind, testid, title, detail, role) {
    var iconName = kind === "success" ? "check" : kind === "error" ? "error" : kind === "uncertain" ? "alert" : "info";
    return h("div", { class: "notice notice-" + kind, role: role || "status", "data-testid": testid || null },
      icon(iconName, "notice-icon"),
      h("div", { class: "notice-body" },
        h("p", { class: "notice-title", text: title }),
        detail ? h("p", { class: "notice-detail", text: detail }) : null));
  }

  // Renders a Submission into its message slot: "<prefix>-error" only while
  // refused, "<prefix>-uncertain" only while uncertain, plus a quiet pending or
  // success line. `success` returns [title, detail] or a string.
  function showOutcome(slot, sub, prefix, success) {
    var nodes = [];
    var form = slot.closest("form");
    if (form) form.classList.toggle("is-busy", sub.state === "pending");
    if (sub.state === "pending") nodes.push(h("p", { class: "pending-line", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Sending…"));
    if (sub.error) {
      var parts = String(sub.error.message).split("\n");
      nodes.push(notice("error", prefix + "-error", parts[0], parts[1], "alert"));
    }
    if (sub.uncertain) nodes.push(notice("uncertain", prefix + "-uncertain", UNCERTAIN[prefix] || sub.uncertain));
    if (sub.state === "done" && success) {
      var line;
      try { line = success(sub.result); } catch (e) { line = "Done."; }
      if (!Array.isArray(line)) line = [line];
      nodes.push(notice("success", null, line[0], line[1]));
    }
    replace(slot, nodes);
  }

  function handleMessages() {
    return {
      not_found: "No one on Pocketful has that handle.",
      validation_failed: "Check the handle, amount and note.\nNotes can be up to 200 characters.",
      insufficient_funds: function () {
        return "Not enough available funds.\nYou have " + money(available(ctx.me)) + " available. Enter a smaller amount.";
      }
    };
  }

  // ------------------------------------------------------------- shell --

  var NAV = [["/", "Wallet", "index", "wallet"], ["/requests", "Requests", "requests", "requests"],
    ["/split", "Split", "split", "split"], ["/authorizations", "Holds", "authorizations", "lock"]];

  function renderShell() {
    var shell = $("#shell");
    if (!shell) return;
    if (!ctx.me) { shell.hidden = !protectedPages[page]; if (!protectedPages[page]) return; }
    shell.hidden = false;
    var nav = h("nav", { class: "nav", "aria-label": "Main" }, NAV.map(function (l) {
      return h("a", { href: l[0], class: "nav-link", "aria-current": page === l[2] ? "page" : null }, icon(l[3]), h("span", { text: l[1] }));
    }));
    var user = ctx.me ? h("div", { class: "user" },
      avatar(ctx.me.display_name),
      h("div", { class: "user-text" },
        h("span", { class: "user-name", "data-testid": "current-user", text: ctx.me.display_name }),
        h("span", { class: "user-handle" }, "@", h("span", { "data-testid": "current-handle", text: ctx.me.handle }))),
      h("button", { type: "button", class: "button button-secondary button-small", "data-testid": "logout-button", text: "Sign out",
        on: { click: function () { api.logout(); location.assign("/login"); } } })) : h("div", { class: "user user-loading", "aria-hidden": "true" });
    replace(shell, h("div", { class: "shell" },
      h("a", { class: "brand", href: "/", text: "Pocketful" }), user, nav));
  }

  function setCurrencyLabels() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-currency-label]"), function (el) {
      el.textContent = (el.getAttribute("data-currency-label") || "Amount") + " (" + ctx.me.currency + ")";
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
        h("p", { class: "wallet-label", text: "Available to spend" }),
        h("p", { class: "amount-hero", "data-testid": "wallet-available", "data-amount": String(available(me)), text: money(available(me)) })),
      h("dl", { class: "wallet-sub" },
        h("div", { class: "wallet-total" }, h("dt", { text: "Total" }),
          h("dd", { "data-testid": "wallet-balance", "data-amount": String(me.balance), text: money(me.balance) })),
        held > 0 ? h("div", { class: "wallet-held" }, h("dt", null, h("span", { class: "held-dot", "aria-hidden": "true" }), "Held"),
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
    var btn = tid("wallet-refresh");
    if (btn) btn.classList.add("is-spinning");
    if (status) replace(status, []);
    return seq.run(function () {
      return P.loadAll(api, Object.assign({ me: ["/me", "user_id"] }, loaders));
    }, function (data) {
      var first = !ctx.me;
      ctx.me = data.me;
      if (first) setCurrencyLabels();
      renderShell();
      renderers.forEach(function (r) { r(data); });
      if (btn && !seq.pending()) btn.classList.remove("is-spinning");
    }, function () {
      if (btn && !seq.pending()) btn.classList.remove("is-spinning");
      if (status) replace(status, h("p", { class: "refresh-error", role: "status", text: "Couldn't refresh. Check your connection and try again." }));
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
          if (outcome.kind === "ok" && !opts.keep) { form.reset(); api.keys.forget(prefix, outcome.idempotencyKey); }
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
    if (refreshBtn) {
      refreshBtn.insertBefore(icon("refresh"), refreshBtn.firstChild);
      refreshBtn.addEventListener("click", refresh);
    }
    renderers.push(function (d) { renderWallet(d.me); });
  }

  function initAuthorizeForm() {
    if (!tid("authorize-submit")) return;
    moneyForm({
      prefix: "authorize", path: "/authorizations", handleField: "to_handle", keep: true, expect: "authorization_id",
      messages: Object.assign(handleMessages(), {
        insufficient_funds: function () {
          return "Not enough available funds to hold this.\nYou have " + money(available(ctx.me)) + " available.";
        },
        self_payment: "You can't hold money for yourself."
      }),
      success: function (a) { return ["Money held", money(a.amount) + " held for @" + a.to_handle + " until " + when(a.expires_at) + "."]; }
    });
  }

  function initIndex() {
    initWalletPage();
    loaders.activity = ["/activity?limit=200", "payments"];
    moneyForm({
      prefix: "pay", path: "/payments", handleField: "to_handle", keep: true, expect: "payment_id",
      messages: Object.assign(handleMessages(), { self_payment: "You can't send money to yourself." }),
      success: function (p) { return ["Payment sent", money(p.amount) + " sent to @" + p.to_handle + (p.visibility === "private" ? " (private)." : ".")]; }
    });
    moneyForm({
      prefix: "request", path: "/requests", handleField: "payer_handle", keep: false, expect: "request_id",
      messages: Object.assign(handleMessages(), { self_request: "You can't request money from yourself." }),
      success: function (r) { return ["Request sent", "You asked @" + r.payer_handle + " for " + money(r.amount) + "."]; }
    });
    initAuthorizeForm();
    renderers.push(function (d) { renderActivity(d.activity); });
  }

  function direction(fromId, toId) {
    return fromId === ctx.me.user_id ? "out" : toId === ctx.me.user_id ? "in" : "other";
  }

  function renderActivity(feed) {
    var slot = $("#activity");
    var items = feed.payments || [];
    if (!items.length) {
      replace(slot, emptyState("empty-activity", "doc", "No payments yet", "Payments you send or receive, and public payments, will appear here."));
      return;
    }
    replace(slot, [
      h("ul", { class: "feed", "data-testid": "activity-list" }, items.map(function (p) {
        var dir = direction(p.from_user_id, p.to_user_id);
        var label = dir === "out" ? "You sent" : dir === "in" ? "You received" : "Between others";
        return h("li", { class: "feed-item feed-" + dir, "data-testid": "activity-item-" + p.payment_id, "data-visibility": p.visibility },
          h("span", { class: "dir-icon dir-" + dir, title: label }, icon(dir === "out" ? "out" : dir === "in" ? "in" : "across"), h("span", { class: "sr-only", text: label })),
          h("div", { class: "feed-main" },
            h("p", { class: "parties", "data-testid": "activity-parties-" + p.payment_id },
              h("span", { text: p.from_handle }), h("span", { class: "arrow", "aria-label": "to", text: " → " }), h("span", { text: p.to_handle })),
            h("p", { class: "note", "data-testid": "activity-note-" + p.payment_id, text: p.note }),
            h("p", { class: "meta" },
              p.visibility === "private"
                ? h("span", { class: "vis vis-private" }, icon("lock"), "Private")
                : h("span", { class: "vis vis-public", text: "Public" }))),
          h("div", { class: "feed-side" },
            h("p", { class: "amount", "data-testid": "activity-amount-" + p.payment_id, text: money(p.amount) }),
            h("time", { class: "meta", datetime: p.created_at, text: when(p.created_at) })));
      })),
      feed.has_more ? h("p", { class: "meta list-foot", text: "Showing your latest " + items.length + " payments." }) : null
    ]);
  }

  // -------------------------------------------------------- requests --

  function initRequests() {
    loaders.incoming = ["/requests?direction=incoming&limit=200", "requests"];
    loaders.outgoing = ["/requests?direction=outgoing&limit=200", "requests"];
    var slot = $("#request-messages");
    var sub = new P.Submission({
      request_not_pending: "This request is no longer pending.\nIt was paid, declined or cancelled elsewhere. The list is up to date now.",
      insufficient_funds: function () {
        return "Not enough available funds to pay this request.\nYou have " + money(available(ctx.me)) + " available.";
      },
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
            return kind === "pay" ? ["Request paid", "You paid " + money(r.amount) + " to @" + r.requester_handle + (r.note ? " for " + r.note : "") + "."]
              : kind === "decline" ? ["Request declined", "You declined @" + r.requester_handle + "'s request."]
                : ["Request cancelled", "Your request to @" + r.payer_handle + " is cancelled."];
          });
        }
        if (outcome.kind !== "uncertain") refresh();
      });
    }

    function item(r, incoming) {
      var pending = r.status === "pending";
      var other = incoming ? r.requester_handle : r.payer_handle;
      var actions = null;
      if (pending && incoming) {
        var id = "request-visibility-" + r.request_id;
        actions = h("div", { class: "row-actions" },
          h("label", { class: "sr-only", for: id, text: "Show the payment as" }),
          h("select", { id: id, class: "select-compact", "data-testid": id, title: "Who can see the payment",
            on: { change: function (e) { keepVisibility[r.request_id] = e.target.value; } } },
            h("option", { value: "public", text: "Public", selected: keepVisibility[r.request_id] !== "private" }),
            h("option", { value: "private", text: "Private", selected: keepVisibility[r.request_id] === "private" })),
          h("button", { type: "button", class: "button button-primary", "data-testid": "request-pay-" + r.request_id,
            text: "Pay", "aria-label": "Pay " + money(r.amount) + " to " + r.requester_handle, on: { click: function () { act("pay", r); } } }),
          h("button", { type: "button", class: "button button-secondary", "data-testid": "request-decline-" + r.request_id,
            text: "Decline", on: { click: function () { act("decline", r); } } }));
      } else if (pending) {
        actions = h("div", { class: "row-actions" },
          h("button", { type: "button", class: "button button-secondary", "data-testid": "request-cancel-" + r.request_id,
            text: "Cancel", "aria-label": "Cancel request to " + r.payer_handle, on: { click: function () { act("cancel", r); } } }));
      }
      return h("li", { class: "row status-" + r.status, "data-testid": "request-item-" + r.request_id, "data-status": r.status },
        avatar(other),
        h("div", { class: "row-main" },
          h("p", { class: "parties" }, h("span", { text: r.requester_handle }), h("span", { class: "arrow", "aria-label": "asks", text: " → " }), h("span", { text: r.payer_handle })),
          r.note ? h("p", { class: "note", text: r.note }) : null,
          h("time", { class: "meta", datetime: r.created_at, title: when(r.created_at), text: relative(r.created_at) })),
        h("div", { class: "row-side" },
          h("div", { class: "row-figure" },
            h("p", { class: "amount", "data-testid": "request-amount-" + r.request_id, text: money(r.amount) }),
            pill(r.status === "paid" ? "success" : r.status === "pending" ? "neutral" : "muted", cap(r.status))),
          actions));
    }

    renderers.push(function (d) {
      var inc = d.incoming.requests || [], out = d.outgoing.requests || [];
      $("#incoming-count").textContent = inc.length ? "(" + inc.length + ")" : "";
      $("#outgoing-count").textContent = out.length ? "(" + out.length + ")" : "";
      replace(tid("incoming-list"), inc.length ? inc.map(function (r) { return item(r, true); })
        : emptyState(null, "doc", "Nothing to pay", "When someone requests money from you, it will appear here.", "li"));
      replace(tid("outgoing-list"), out.length ? out.map(function (r) { return item(r, false); })
        : emptyState(null, "doc", "No requests sent", "Ask for money from your wallet, or split a bill.", "li"));
      replace($("#requests-empty"), !inc.length && !out.length
        ? notice("info", "empty-requests", "No requests yet", "Requests you send or receive will appear here. Ask from your wallet, or split a bill.")
        : []);
    });
  }

  // ------------------------------------------------------------ split --

  function initSplit() {
    var amount = tid("split-amount"), handles = tid("split-handles"), note = tid("split-note");
    var slot = $("#split-messages");
    var sub = new P.Submission({
      not_found: "One of those handles doesn't exist.\nCheck the spelling of each handle.",
      validation_failed: "Check the amount, the handles and the note.\nEach person can appear once."
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
        replace(box, h("div", { class: "empty empty-quiet" },
          h("span", { class: "empty-icon" }, icon("split")),
          h("p", { class: "empty-text", text: amount.value.trim() && !c.parsed.ok ? c.parsed.reason : "Add an amount and participants to see each share." })));
        return;
      }
      var shares = P.splitPreview(c.parsed.minor, c.handles);
      replace(box, [
        h("ul", { class: "shares" }, shares.map(function (s) {
          return h("li", null,
            h("span", { class: "share-who" }, s.handle, s.handle === ctx.me.handle ? h("span", { class: "you", text: " (you)" }) : null),
            h("span", { class: "amount", "data-testid": "split-share-" + s.handle, text: money(s.amount) }));
        })),
        h("p", { class: "meta preview-foot", text: shares.length > 1 && shares[0].amount !== shares[shares.length - 1].amount
          ? "The first participants in the list receive the remaining minor units, so the shares add up to the amount."
          : "Everyone pays the same share." })
      ]);
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
      if (dup.length) { sub.reject(dup[0] + " is listed twice.\nEach person can appear once."); showOutcome(slot, sub, "split"); return; }
      var body = { amount: c.parsed.minor, participant_handles: c.handles, note: note.value };
      var identity = rawFields(tid("split-submit").form);
      var ticket = sub.begin();
      showOutcome(slot, sub, "split");
      api.write("split", "POST", "/splits", body, { expect: "split_id", identity: identity }).then(function (outcome) {
        if (sub.settle(ticket, outcome)) {
          if (outcome.kind === "ok") { tid("split-submit").form.reset(); api.keys.forget("split", outcome.idempotencyKey); preview(); }
          showOutcome(slot, sub, "split", function (s) {
            var n = s.requests.length;
            return ["Requests created", n ? "Split " + money(s.amount) + ": " + n + " request" + (n === 1 ? "" : "s") + " sent. See them under Requests."
              : "Split " + money(s.amount) + ". Nobody else to ask."];
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
      authorization_not_open: "This hold is no longer open.\nIt may have been fully captured, released or expired. The list is up to date now.",
      authorization_expired: "This hold has expired.\nThe remaining money went back to the payer.",
      capture_exceeds_authorization: "That is more than remains on this hold.",
      validation_failed: "Enter an amount of at least the smallest unit.",
      forbidden: "Only the recipient can collect; only the payer can release."
    });
    // What the person has typed or ticked per hold, kept across list re-renders
    // so an unchanged retry sends the same body and identity.
    var typed = {}, keepOpen = {};

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
            // A confirmed capture closes that intent, and only that one: a late
            // success must not discard the key of a newer pending or uncertain capture.
            if (o.kind === "ok") api.keys.forget(slotName, o.idempotencyKey);
            done(ticket, o, a.authorization_id, function (p) { return ["Capture complete", "You collected " + money(p.amount) + " from @" + a.from_handle + "."]; });
          });
      } else {
        ticket = sub.begin();
        showOutcome(slot, sub, "authorization");
        api.post("/authorizations/" + encodeURIComponent(a.authorization_id) + "/void", {}, "authorization_id")
          .then(function (o) { done(ticket, o, a.authorization_id, function () { return ["Hold released", "The money held for @" + a.to_handle + " is available again."]; }); });
      }
    }
    function done(ticket, outcome, id, success) {
      if (sub.settle(ticket, outcome)) {
        if (outcome.kind === "ok") { delete typed[id]; delete keepOpen[id]; }
        showOutcome(slot, sub, "authorization", success);
      }
      if (outcome.kind !== "uncertain") refresh();
    }

    function item(a) {
      var id = a.authorization_id;
      var outgoing = a.from_user_id === ctx.me.user_id;
      var open = a.status === "open";
      var remaining = typeof a.remaining_amount === "number" ? a.remaining_amount : (open ? a.amount - (a.captured_amount || 0) : 0);
      var captured = a.captured_amount || 0;
      var actions = null;
      if (open && !outgoing) {
        var inputId = "authorization-capture-amount-" + id, keepId = "authorization-keep-open-" + id;
        actions = h("div", { class: "hold-action" },
          h("div", { class: "field" },
            h("label", { for: inputId, text: "Capture amount (" + ctx.me.currency + ")" }),
            h("input", { id: inputId, "data-testid": inputId, inputmode: "decimal", autocomplete: "off",
              value: typed[id] !== undefined ? typed[id] : decimal(remaining),
              on: { input: function (e) { typed[id] = e.target.value; } } })),
          h("label", { class: "check", for: keepId },
            h("input", { type: "checkbox", id: keepId, "data-testid": keepId, checked: keepOpen[id] ? true : null,
              on: { change: function (e) { keepOpen[id] = e.target.checked; } } }),
            h("span", null, "Keep the rest held", h("span", { class: "check-hint", text: "Leave it unticked to collect and close the hold." }))),
          h("button", { type: "button", class: "button button-primary button-block", "data-testid": "authorization-capture-" + id,
            text: "Collect", on: { click: function () { act("capture", a); } } }));
      } else if (open) {
        actions = h("div", { class: "hold-action hold-action-end" },
          h("button", { type: "button", class: "button button-secondary button-block", "data-testid": "authorization-void-" + id,
            text: "Release hold", on: { click: function () { act("void", a); } } }));
      }
      var statusPill = open ? pill("held", "Open · held") : a.status === "captured" ? pill("success", "Captured") : pill("muted", cap(a.status));
      var iconName = open ? (outgoing ? "up" : "down") : a.status === "captured" ? "check" : "ban";
      return h("li", { class: "hold " + (open ? "hold-open" : "hold-closed") + (actions ? " hold-has-action" : "") + " status-" + a.status, "data-testid": "authorization-item-" + id, "data-status": a.status },
        h("span", { class: "dir-icon dir-" + (open ? "held" : a.status) }, icon(iconName)),
        h("div", { class: "hold-main" },
          h("p", { class: "hold-title" },
            h("span", { class: "parties" }, h("span", { text: a.from_handle }), h("span", { class: "arrow", "aria-label": "to", text: " → " }), h("span", { text: a.to_handle })),
            pill("neutral", outgoing ? "Outgoing" : "Incoming"), statusPill),
          h("p", { class: "hold-amount", "data-testid": "authorization-amount-" + id, text: money(a.amount) }),
          h("p", { class: "meta" },
            open ? h("span", { class: "held-text", text: "Remaining " + money(remaining) }) : null,
            captured > 0 && a.status !== "captured" ? h("span", { text: "Captured " + money(captured) }) : null,
            a.status === "captured" ? h("span", null, "Captured ", h("span", { "data-testid": "authorization-captured-" + id, text: money(captured) })) : null,
            a.note ? h("span", { text: a.note }) : null,
            h("span", { text: a.visibility === "private" ? "Private" : "Public" })),
          h("p", { class: "meta expiry" },
            h("span", { text: (open ? "Expires " + relative(a.expires_at) : a.status === "expired" ? "Expired" : "Expiry") + " (" + when(a.expires_at) + ")" }),
            h("time", { class: "rfc", "data-testid": "authorization-expires-" + id, datetime: a.expires_at, text: a.expires_at }))),
        actions);
    }

    renderers.push(function (d) {
      var list = d.auths.authorizations || [];
      var openCount = list.filter(function (a) { return a.status === "open"; }).length;
      $("#holds-summary").textContent = list.length ? openCount + " open · " + (list.length - openCount) + " closed" : "";
      replace($("#authorizations"), list.length
        ? h("ul", { class: "holds", "data-testid": "authorization-list" }, list.map(item))
        : emptyState("empty-authorizations", "lock", "No holds yet", "Holds you create or receive will appear here."));
    });
  }

  // ----------------------------------------------------------- auth pages --

  function initAuthPage(kind) {
    var form = tid(kind + "-submit").form;
    var slot = $("#auth-messages");
    var sub = new P.Submission({
      unauthenticated: "Email or password is incorrect.",
      validation_failed: kind === "signup" ? "Use a valid email and a password of at least 8 characters." : "Enter your email and password.",
      handle_taken: "An account already uses the handle made from that email.\nTry a different email.",
      email_taken: "That email is already registered.\nSign in instead."
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-password-toggle]"), function (btn) {
      var input = document.getElementById(btn.getAttribute("data-password-toggle"));
      btn.appendChild(icon("eye"));
      btn.addEventListener("click", function () {
        var show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.setAttribute("aria-pressed", String(show));
        btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      });
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ticket = sub.begin();
      form.classList.add("is-busy");
      replace(slot, h("p", { class: "pending-line", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), kind === "signup" ? "Creating your account…" : "Signing in…"));
      var call = kind === "signup"
        ? api.signup(tid("signup-email").value.trim(), tid("signup-password").value, tid("signup-display-name").value.trim())
        : api.login(tid("login-email").value.trim(), tid("login-password").value);
      call.then(function (outcome) {
        if (!sub.settle(ticket, outcome)) return;
        form.classList.remove("is-busy");
        if (outcome.kind === "ok") {
          replace(slot, notice("success", null, kind === "signup" ? "Account created" : "Signed in"));
          location.assign("/");
          return;
        }
        var text = sub.error ? sub.error.message : "We couldn't reach Pocketful.\nCheck your connection and try again.";
        var parts = text.split("\n");
        replace(slot, notice("error", "auth-error", parts[0], parts[1], "alert"));
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
      api.get("/me", "user_id").then(function (o) { if (o.kind === "ok") { ctx.me = o.data; renderShell(); } });
    }
  }
})();
