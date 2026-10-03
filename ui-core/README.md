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
