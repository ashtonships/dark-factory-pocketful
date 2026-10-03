# ui-core — Pocketful client core (W-5)

Screen-independent browser logic. Plain JavaScript, no dependencies, no build step, no network fetches beyond
the service's own API. Pages load `pocketful-core.js`, which exposes `window.PocketfulCore`.

Self-test: `python3 -m http.server <port>` in this folder, then open `/selftest.html`, or run
`node ui-core/selftest.js`.

| Function | Serves |
|---|---|
| `formatAmount(minor, minor_units, currency)` | stage-2 "Formatted amount" (`wallet-balance`, `wallet-available`, `wallet-held`, `activity-amount-*`, `request-amount-*`, `split-share-*`, `authorization-*` amounts) |
| `parseAmount(text, minor_units)` | stage-2 "The form accepts decimal amounts and submits minor units … `15.005` is rejected rather than rounded" (pay, request, split, authorize and capture inputs) |
| `splitShares`, `splitPreview`, `parseHandles` | stage-1 §9; stage-2 "`split-preview` must show the shares the server would compute … identical shares"; "`split-handles`: handles separated by commas, in order" |
| `KeyRing`, `canonicalJson`, `ApiClient.write` | stage-2 "Submitting it again without changing a field must not send another payment … Changing a field makes the next submission a new payment request"; "Keep the unchanged form retryable with the same key and body"; stage-1 §7 |
| `classify`, `Submission` | stage-2 "show `pay-uncertain` … not `pay-error`"; "Successful retry removes both error/uncertainty elements"; "Unknown outcomes are not confirmed rejections"; "A refused payment shows `pay-error`" |
| `TokenStore` (localStorage) | stage-2 "A browser signed in before that export/import upgrade must remain signed in afterwards" |
| `KeyRing` held in page memory | stage-2 "The form and pending retry identity must survive the upgrade" (no reload required) |
| `LatestWins`, `loadAll` | stage-2 "Latest refresh wins: a delayed earlier read must not overwrite a later refresh, including when responses arrive out of order"; "Navigation must wait for the write to succeed before it refreshes the data" |

Readings taken:
- A refresh's order is the order it **started**, never the value it returns (a later, lower balance wins).
  A later refresh that fails still discards an earlier one that answers after it.
- Network error, timeout, 5xx, or a 2xx whose body cannot be read are **uncertain**; any 4xx is a refusal.
- Changing a field and then changing it back is a new submission with a new key; only the immediately
  previous submission from the same form is replayed.
- Typed amounts tolerate surrounding spaces, `15.`, `.5` and leading zeros; signs, exponents, separators
  and currency text are rejected. A leading `@` on a typed handle is dropped.

## W-6: screens (structure and behaviour, unstyled)

| File | Role |
|---|---|
| `index.html`, `requests.html`, `split.html`, `signup.html`, `login.html`, `authorizations.html` | One page per stage-2 route; static forms with every `data-testid` |
| `app.js` | Page behaviour (shell, wallet, forms, lists, refresh), built on `pocketful-core.js` |
| `theme.css` | The single replaceable stylesheet (layout and look). System fonts only |
| `devstub.py` | Dev-only in-memory API stand-in with fault injection. Not part of any stage |
| `browser-drill.js`, `run-drill.sh` | Browser drill (Playwright + system Chrome) against the stub, desktop and 375 px |

### What the stage-2 service must serve (Builder's routing item)

| Request | Response |
|---|---|
| `GET /` with `Accept` containing `text/html` | `index.html` |
| `GET /requests` with `Accept` containing `text/html` | `requests.html` (JSON API otherwise) |
| `GET /authorizations` with `Accept` containing `text/html` | `authorizations.html` (JSON API otherwise) |
| `GET /split`, `GET /signup`, `GET /login` with `Accept` containing `text/html` | `split.html`, `signup.html`, `login.html` |
| `GET /ui/pocketful-core.js`, `GET /ui/app.js` | `text/javascript; charset=utf-8` |
| `GET /ui/theme.css` | `text/css; charset=utf-8` |

Pages call the API with `Accept: application/json`, so the shared paths never return HTML to the client
code. `selftest.html`, `selftest.js`, `devstub.py` and the drill files need not be shipped.

### Behaviour readings
- The pay and authorize forms keep their values (and their idempotency key) after success, so an unchanged
  resubmit replays. The request and split forms clear after success and start a new key.
- A refused or successful write refreshes the page's data; an uncertain one does not (the server may be
  unreachable) and keeps the form for a same-key retry.
- `empty-activity` and `empty-authorizations` replace their list. `incoming-list` and `outgoing-list`
  stay as containers, and `empty-requests` is added when both are empty.
- `authorization-captured-{id}` appears only for `captured`. A partly collected open hold shows its
  progress in plain text. The capture form has a "Keep the rest held" box that sends `final: false`.
- On `/requests` the payer picks the payment's visibility next to the pay button (`request-visibility-{id}`).
