# Pocketful requirements ledger

Owner: Coordinator. One numbered entry per obligation of the specification, each quoting its sentence in “curly
quotes” (the quote is what `tools/spec_coverage.py` matches). `N/A:` lines are waivers with a reason.

**Entry ids.** Stage 1 sentence k is entry k (1–273). Stage 2 entries are 1000+k, stage 3 2000+k, stage 4 3000+k
(added when each stage starts). Findings, decisions and lessons are 9000+. Ids never change; checks reference them as
`ledger: <id>`.

**Specification:** /Users/ashton/DarkFactory/kickoff-specs/pocketful/spec/stage-N.md

## Decisions (ambiguities resolved from the requirements; each keeps every stated invariant)

- **D-1 Stack** (task brief): one container per stage folder; Python 3.12 standard library HTTP server
  (ThreadingHTTPServer); SQLite with every money movement in one `BEGIN IMMEDIATE` transaction; integer minor units
  only; plain HTML/CSS/JS served by the same process. No runtime dependency outside the image; no outbound network.
- **D-2 Error precedence** (from §5, §7 and entry 148): 401 auth → 400 body not a JSON object → 400 missing/empty
  `Idempotency-Key` → 422 key longer than 255 → claimed-key resolution (200 replay / 409 `idempotency_key_reuse`) →
  400 wrong JSON type → 422 field validation (incl. `self_payment`/`self_request`) → 404 unknown handle/resource →
  403 not permitted → 409 state (`request_not_pending`) → 409 `insufficient_funds`. Reason: §7 fixes key resolution
  before field validation; state and funds can only be judged on a valid, existing, permitted target.
- **D-3 Timestamps**: UTC with `+00:00`, second precision or finer, all from the server clock.
- **D-4 Amounts**: a JSON number whose value is integral is valid (`1000`, `1000.0`, `1e3`); booleans, strings,
  null, fractional values, < 1 or > 1000000000 are 422 `validation_failed`.
- **D-5 Ordering**: “newest first by created_at”, ties broken by insertion order (newest inserted first), so
  pagination is deterministic. Seeded payments and requests take the reset time as `created_at`, later array items
  counted as newer.
- **D-6 Email**: valid when it has exactly one `@` with non-empty text both sides; emails compare
  case-insensitively; `email_taken` is checked before `handle_taken`; a failed signup creates nothing.
- **D-7 Reset fixture**: any invalid fixture (negative balance, missing required fields, bad types, unknown user
  references, `minor_units` outside {0,2,3}) is 422 `validation_failed` and changes nothing; a body that is not
  JSON is 400 `malformed_request`. Optional arrays (`payments`, `requests`, `settlement_operator_ids`) default to [].
- **D-8 Routing**: unknown path → 404 `not_found`; known path with an unsupported method → 405
  `method_not_allowed`; both carry the §5 error body.
- **D-9 Settlement validation**: entries are validated in input order and the first failing entry decides the error
  (422 or 404); affordability (409) is evaluated only when every entry is valid; nothing of a failed settlement is
  stored, including its idempotency key.
- **D-10 Note length**: 200 characters means 200 Unicode code points.

- **D-11 Authorize form placement**: the spec ties the `authorize-*` testids to no route; the form appears on both
  `/` (where the money forms live) and `/authorizations`. Reason: either reading of the spec is then satisfied.
- **D-12 Upgrade format**: export keeps `format_version: 1`; a stage-2 import accepts a stage-1 export unchanged
  (absent authorisations mean none) and preserves tokens, keys and original responses.
- **D-13 Expiry**: an authorisation is expired when `expires_at` <= now, judged at every read and write; an
  authorisation expired by the clock is never shown as open and gets no capture or void button.
- **D-14 Capture precedence**: auth → body → key resolution → 422 amount type/range → 404 → 403 → 409
  `authorization_not_open` (status captured/voided/expired) → 409 `authorization_expired` (stored open, clock past
  expiry) → 422 `capture_exceeds_authorization`. Reason: the remainder only exists for an open authorisation.

- **D-15 Split participants**: when the caller omits their own handle, they are not a participant: the shares cover
  exactly the listed handles in the order given, and every listed handle gets a request. Reason: §8 fixes shares
  "in the order given" and §9 gives remainders "to the first participants in participant_handles order"; an
  implicit caller would need a position the request never states.

- **D-16 Time windows**: `as_of` is inclusive; statement windows are half-open `[from, to)`; both read instants
  may be in the future; one clock reading per request decides "now".
- **D-17 Statement ties**: equal effective times order by payment id ascending as the spec states; ids are opaque
  strings compared bytewise.
- **D-18 Recorded time**: `recorded_at` uses microsecond precision and strictly increases per payment (bumped by
  1 µs when the clock has not advanced), so revision order and known_at selection are unambiguous.

- **D-19 Legacy holds on upgrade**: a stage-3 import of an earlier export that carries no event time for a closed
  hold treats it like a seeded closed hold (2113: "seeded closed holds need not reconstruct a prior lifecycle")
  instead of inventing event times. To keep that case rare, stage 2 records the event time of every capture, void
  and expiry internally and includes it in its export. The time is not exposed in the stage-2 API.

## Work items (stage 1)

| Item | Seat | Entries | Scope |
|---|---|---|---|
| W-1 | Builder | 2–3, 9–12, 14–15, 18, 22–25, 27–32, 34–48, 50–55, 57–61, 80–89, 91–92, 95–103, 105–117, 119–130, 9001–9003 | Runtime contract and data model: container, RUN.md, health, reset/seed, conventions, errors, auth, `GET /me`, the SQLite schema for every stage-1 record |
| W-2 | Builder | 62–79, 131–204, 217–220 | Payments, requests (create, pay, decline, cancel, list), the activity feed, idempotency on every write path |
| W-3 | Builder | 205–216, 221–231 | Splits and the equal-split rule |
| W-4 | Builder | 232–273 | Export/import and atomic net settlements |
| W-5 | Builder-Two | stage-2 UI entries (added at stage 2) | Client core for the screens, outside stage folders until stage 2 opens |
| W-D | Builder | 1016–1027 | Three concepts per screen, picked by Checker; starts when W-1 is accepted |
| W-6 | Builder-Two | stage-2 UI entries (W-7 list) | Screen structure and behaviour, unstyled, in ui-core/ |
| W-7 | Builder-Two | 1005–1006, 1008–1012, 1015–1027, 1029–1101 (UI), 1203, 1205–1221 | Screens in stage-2/ styled to the pick |
| W-9 | Builder | stage-3 write side (W-9 entries in Stage 3) | Payment timestamps, revisions, corrections, overdraft checks, linked-payment immutability, stage-1/2 import |
| W-10 | Builder-Two | stage-3 read side (W-10 entries in Stage 3) | as_of/known_at views of /me, statements, snapshots, historical holds, in a separate module |
| W-8 | Builder | 1001–1002, 1013–1014, 1095, 1102–1202, 1204, 1222 | Stage-2 server: copy of frozen stage-1/, holds and captures, available-based funds, HTML routing, static UI, stage-1 import |

## Practice-run lessons (made entries so the same faults cannot recur)

9001. “Unparseable body, or a field of the wrong JSON type” — §5 · W-1 · Every rejected request (400/401/404/405/422) must read and discard its whole body so the next request on a keep-alive connection is parsed correctly.
9002. “Unparseable body, or a field of the wrong JSON type” — §5 · W-1 · A body sent with `Transfer-Encoding: chunked` must be decoded and read in full, not treated as empty.
9003. “Unparseable body, or a field of the wrong JSON type” — §5 · W-1 · `NaN`, `Infinity`, `-Infinity`, invalid UTF-8 and UTF-16/32 bodies are 400 `malformed_request`; duplicate keys follow the last value.

## Findings (added as they arrive)

Adversary pre-mortem for stage 1 (Sat 3 Oct). These five risks are entries; checks and attacks assert state after failed operations and across imports, not codes alone.

9004. “The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`.” — pre-mortem 1 · W-2, W-4 · Money writes, request-state changes and receipt inserts share one transaction under 50 competing calls (also entries 10, 11).
9005. “For concurrent identical requests with an unused key, exactly one returns 201.” — pre-mortem 2 · W-2 · Key scope, canonical JSON, replay precedence and no caching of failed keys, including simultaneous first use and retries after pay/cancel (entries 131–148).
9006. “Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type.” — pre-mortem 3 · W-1 · No float/bool coercion, note length in code points, strict query-integer grammar, keep-alive body consumption (9001–9003).
9007. “A share of `0` is legal and still produces a request for that participant.” — pre-mortem 4 · W-3 · Zero shares, caller omitted, remainder allocation by order; conservation holds after zero requests are paid.
9008. “Either all movements commit together or none do; failed validation claims no idempotency key and creates no payment or revision.” — pre-mortem 5 · W-4 · Settlements atomic, not sequential; export/import keeps tokens, operator permissions and original replay receipts.
9009. “Unknown outcomes are not confirmed rejections.” — finding PF-A1 (Adversary, W-5 77595cc / W-6 73beaa0) · W-5, W-6 · A 2xx with an empty, `null` or unparseable body is an uncertain outcome: pay-uncertain shows, the form and key are kept, nothing throws. Status: fixed in 93f3606; Adversary re-review 11/11 core, 32/32 browser; Checker verifies in W-7.
9010. “Changing a field makes the next submission a new payment request.” — finding PF-A2 (Adversary, W-5 77595cc / W-6 73beaa0) · W-5, W-6 · The intent identity is the raw text of every form field, not the normalised body: 15 → 15.00, bob → @bob or added spaces get a new key and a new payment; an unchanged form keeps its key. Status: fixed in 93f3606; Adversary re-review 11/11 core, 32/32 browser; Checker verifies in W-7.
9011. “`amount` is at most `1000000000` on any single request, and no operation produces a balance outside ±2⁵³.” — finding PF-A3 (Adversary, W-5 77595cc / W-6 73beaa0) · W-5, W-6, W-1 · The range is inclusive: a balance of exactly 2^53 (9007199254740992) is valid, the server stores and returns it exactly, and the UI formats it (90071992547409.92 EUR) instead of throwing. Status: UI fixed in 93f3606 (Adversary re-review); server covered by Checker d77128b.
9012. “The required flows must remain clear and usable at a 375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling.” — finding PF-A4 (Adversary, W-6 73beaa0) · W-6, W-7 · The largest legal amounts (balance 9007199254740991 or 2^53, amounts up to 1000000000) fit at 375 px without page overflow: the headline shrinks or wraps, never overflows. This binds every theme, including the restyle in W-7. Status: fixed in 93f3606; Adversary re-review 11/11 core, 32/32 browser; Checker verifies in W-7.

Adversary pre-mortem for W-8 (Sat 3 Oct evening):

9013. “Held funds cannot fund new payments,” — W-8 pre-mortem 1 · W-8 · Holds are subtracted from what payments, request pay and settlement net debits can spend.
9014. “Captures may spend the money reserved for them.” — W-8 pre-mortem 2 · W-8 · A partial capture spends only its own reservation, never available funds as well, and releases exactly the remainder.
9015. “Reads and writes must reflect expiry even if no request occurred at the deadline.” — W-8 pre-mortem 3 · W-8 · One clock reading per request; an expired capture gets the D-14 error for its party and status.
9016. “Each idempotent capture moves” — W-8 pre-mortem 4 · W-8 · The capture receipt, key claim and hold transition commit in one transaction.
9017. “A stage-2 service must accept an export produced by the same team's stage-1 service.” — W-8 pre-mortem 5 · W-8 · Reset and import derive available, keep stage-1 tokens and retry receipts, and validate before replacing anything.
9018. “Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type.” — finding PF-A5 (Adversary, uncommitted W-8 over cd4efc0) · W-8 · A capture `final` that is not a JSON boolean ("false", null, 0, []) is 400 malformed_request, not 422; a claimed key still resolves first (D-2). Status: open, with Builder (Adversary sent it to Builder directly).
9019. “Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2, or an equivalent.” — finding (Checker security review, accepted stage 1 57cc82e) · W-1 · New hashes use salted PBKDF2-SHA256 at 5000 iterations, tagged, with constant-time comparison. That meets the requirement, but it is below current OWASP guidance (600k). Decision (Coordinator, Sat 22:15): accepted risk, no change in this run. Reason: the stated obligations (entries 30-31: 50 in flight under 5 s on 2 vCPU) are measurable and were failing under this host load at 20000 iterations; the OWASP figure is not part of the specification. Revisit as stage-2 hardening (a tagged work factor that rehashes on login) only if the host load becomes normal and time remains after stage 2 is accepted.

## Stage 1 entries
N/A: “This stage defines the initial service and its API.” — stage-1.md line 3: stage introduction, no behaviour
2. “Build from the supplied requirements.” — stage-1.md:5 · W-1
3. “Source code, API documentation and schemas from existing products in this domain must not be used.” — stage-1.md:5 · W-1
N/A: “Users can send money by handle, request money and split bills.” — stage-1.md line 10: scope summary; each behaviour has its own entry
N/A: “Payments appear in an activity feed with public or private visibility.” — stage-1.md line 10: scope summary; see entries 72-79
N/A: “Authorized operators can submit groups of transfers as settlements.” — stage-1.md line 11: scope summary; see entries 252-273
N/A: “Only the HTTP API is required.” — stage-1.md line 12: scope statement, no behaviour
N/A: “The following apply to all operations, including concurrent requests and retries:” — stage-1.md line 14: introduces entries 9-11
9. “The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`.” — stage-1.md:16 · W-1 · Invariant, checked after every concurrency attack. Every money movement is one BEGIN IMMEDIATE transaction.
10. “No wallet balance may be negative, including transiently.” — stage-1.md:17 · W-1 · Invariant. Balance check and debit happen inside the same BEGIN IMMEDIATE transaction.
11. “A payment request may move money at most once.” — stage-1.md:18 · W-1 · Invariant. Paying a request is idempotent and guarded by status=pending inside the transaction.
12. “All amounts are exact integer counts of minor units.” — stage-1.md:20 · W-1
N/A: “Deposits, top-ups, withdrawals, cards and bank integrations are out of scope.” — stage-1.md line 20: out-of-scope statement, nothing to build
14. “Money moves only between existing wallets.” — stage-1.md:21 · W-1
15. “Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup.” — stage-1.md:25 · W-1
N/A: “Language, framework and storage are unrestricted.” — stage-1.md line 26: permission, no obligation
N/A: “A `docker-compose.yml` is optional.” — stage-1.md line 27: permission, no obligation
18. “The submission is a containerized HTTP service, not a Python package.” — stage-1.md:29 · W-1
N/A: “Python is not required in the implementation.” — stage-1.md line 29: permission, no obligation
N/A: “TypeScript/JavaScript, Go, Rust, Java, Python and any other language are equally valid.” — stage-1.md line 30: permission, no obligation
N/A: “The harness builds the submitted `Dockerfile`, starts the resulting image and tests only its HTTP behavior; it does not import or execute the submission's source files on the judge host.” — stage-1.md line 31: describes the harness, not the product
22. “The image must run on its own with `-e PORT=<port>` and a port mapping.” — stage-1.md:35 · W-1
23. “Runtime networking has no outbound access.” — stage-1.md:35 · W-1
24. “All runtime dependencies, initialization and seed data must work within that single container.” — stage-1.md:36 · W-1
25. “Compose configuration is not used to start the service.” — stage-1.md:37 · W-1
N/A: “The service must operate within these limits:” — stage-1.md line 41: introduces entries 27-33
27. “CPU | 2 vCPU” — stage-1.md:45 · W-1
28. “Memory | 2 GiB” — stage-1.md:46 · W-1
29. “Start to first healthy response | 60 s” — stage-1.md:47 · W-1
30. “Concurrent requests | up to 50 in flight” — stage-1.md:48 · W-1
31. “Per-request timeout | 5 s (10 s for `POST /_test/reset`)” — stage-1.md:49 · W-1
32. “Outbound network | available during `docker build`, **none at run time**” — stage-1.md:50 · W-1
N/A: “Disk | ephemeral; state need not survive a container restart” — stage-1.md line 51: permission: state need not persist
34. “Runtime assets and dependencies must be included in the image.” — stage-1.md:53 · W-1
35. “This includes fonts, scripts and stylesheets; external services are unavailable at runtime.” — stage-1.md:53 · W-1
36. “Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`.” — stage-1.md:60 · W-1
37. “Return 200 once the service and its data store can serve requests, within 60 seconds of container start.” — stage-1.md:68 · W-1
38. “Non-200 responses are permitted before the service is ready.” — stage-1.md:69 · W-1
39. “Replace all service state with the fixture in the request body (§4).” — stage-1.md:82 · W-1
40. “When reset returns 204, subsequent requests must see only that fixture.” — stage-1.md:82 · W-1
41. “Repeated resets are supported.” — stage-1.md:83 · W-1
42. “This test endpoint must be enabled in the delivered image and requires no authentication.” — stage-1.md:84 · W-1
43. “Requests and responses are `application/json; charset=utf-8`.” — stage-1.md:88 · W-1
44. “Timestamps in responses are RFC 3339 with an explicit offset, e.g.” — stage-1.md:89 · W-1 · Decision D-3: emit UTC as +00:00 (e.g. 2026-09-24T11:04:03+00:00); seconds precision is enough.
45. “`2026-09-24T19:00:00+02:00`.” — stage-1.md:89 · W-1
46. “Unknown fields in a request body are ignored, never an error.” — stage-1.md:90 · W-1
47. “Unknown query parameters are ignored.” — stage-1.md:91 · W-1
48. “IDs are opaque strings of at most 64 characters.” — stage-1.md:92 · W-1 · IDs are opaque; never parse them.
N/A: “Their format is yours.” — stage-1.md line 92: permission, no obligation
50. “The service has **one currency**, declared in the fixture.” — stage-1.md:96 · W-1
51. “Every amount in the API is an integer count of its minor units: `1000` in a `minor_units: 2` service is €10.00, and `1000` in a `minor_units: 0` service is ¥1000.” — stage-1.md:96 · W-1
52. “API amounts must have an integral numeric value: JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount.” — stage-1.md:100 · W-1 · Decision D-4: a JSON number with integral value is accepted (1000, 1000.0, 1e3); 1000.5 is 422.
53. “Booleans and strings are not numbers here.” — stage-1.md:101 · W-1 · true/false and "1000" as amount are 422 validation_failed (entry 105-106 precedence).
54. “Every user has a **handle**: unique across the service, matching `^[a-z0-9_]{1,20}$`, and never changing once set.” — stage-1.md:105 · W-1
55. “Users identify recipients by handle.” — stage-1.md:106 · W-1
N/A: “Directory and user-search endpoints are out of scope.” — stage-1.md line 106: out-of-scope statement
57. “Seeded users take their handle from the fixture.” — stage-1.md:109 · W-1
58. “A user created through `POST /auth/signup` (§6 — there is no `handle` field in the signup body) has one **derived** from their email: take the local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20 characters.” — stage-1.md:109 · W-1 · Decision D-6: the local part is the text before the @; a valid email has exactly one @ with non-empty text on both sides.
59. “If that handle is already taken the signup fails; see the signup table in §6.” — stage-1.md:112 · W-1 · See entry 124.
60. “New users start with a balance of `0`.” — stage-1.md:114 · W-1
61. “They can receive money and be asked for money immediately.” — stage-1.md:114 · W-1
62. “A **payment** moves money from one wallet to another, immediately and atomically.” — stage-1.md:118 · W-2
63. “It is either sent directly or created by paying a request.” — stage-1.md:118 · W-2
64. “A **request** asks someone for money.” — stage-1.md:121 · W-2
65. “The `requester` will receive; the `payer` is being asked.” — stage-1.md:121 · W-2
66. “A request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`.” — stage-1.md:121 · W-2
67. “Only the payer may pay or decline it; only the requester may cancel it.” — stage-1.md:122 · W-2
68. “**A request may exceed the payer's balance.** That is a legal state, not an error at creation time: the request stays `pending` until it is paid, declined or cancelled, and an attempt to pay it while short is `409 insufficient_funds` and changes nothing.” — stage-1.md:125 · W-2
69. “Money can arrive later and the same request then becomes payable.” — stage-1.md:127 · W-2
70. “**Visibility belongs to the payment, not the request.** The payer chooses it when the money moves.” — stage-1.md:130 · W-2
71. “A request carries no visibility of its own and never appears in anyone else's feed.” — stage-1.md:131 · W-2
72. “`GET /activity` returns payments only.” — stage-1.md:135 · W-2
73. “A payment appears for a caller **if and only if** its `visibility` is `public`, **or** the caller is its sender or its receiver.” — stage-1.md:135 · W-2 · Feed rule; there is no other rule.
74. “There is no other rule, no follow graph and no mute list.” — stage-1.md:136 · W-2
75. “Requests never appear in the activity feed; they are read through `GET /requests`, which returns only requests where the caller is the requester or the payer.” — stage-1.md:137 · W-2
76. “A split is not a feed item.” — stage-1.md:140 · W-2
77. “The requests it creates are visible to their own two parties, and the payments that eventually fulfil them follow the rule above.” — stage-1.md:140 · W-2
78. “Visibility is **one value on the payment**, seen identically by both parties and by everyone else.” — stage-1.md:143 · W-2
79. “A `private` payment is hidden from third parties, not from its own receiver.” — stage-1.md:144 · W-2
80. “`amount` is at most `1000000000` on any single request, and no operation produces a balance outside ±2⁵³.” — stage-1.md:148 · W-1
81. “Monetary arithmetic must preserve exact minor-unit values without rounding error.” — stage-1.md:149 · W-1
82. “Seeded users must be able to log in with the given password immediately.” — stage-1.md:174 · W-1
83. “`balance` is the wallet balance **after** every seeded payment has been applied.” — stage-1.md:175 · W-1
84. “Seeded” — stage-1.md:175 · W-1
85. “numbers are consistent; you do not replay seeded payments against balances.” — stage-1.md:176 · W-1
86. “A `balance` below zero in a fixture is a reset error: return `422 validation_failed` from” — stage-1.md:177 · W-1 · Decision D-7: any other invalid fixture (missing fields, wrong types, unknown references, bad minor_units) is also 422 validation_failed and changes nothing; a non-JSON body is 400.
87. “`POST /_test/reset` and change nothing.” — stage-1.md:178 · W-1
88. “`minor_units` is `0`, `2` or `3`.” — stage-1.md:179 · W-1
89. “Fixtures use `EUR` (2), `JPY` (0) and `BHD` (3).” — stage-1.md:179 · W-1
N/A: “An administrative balance endpoint is out of scope.” — stage-1.md line 181: out-of-scope statement
91. “Every 4xx and 5xx response carries this body:” — stage-1.md:185 · W-1
92. “Use the specified HTTP status and `code`.” — stage-1.md:191 · W-1
N/A: “The human-readable `message` may use any wording.” — stage-1.md line 191: permission: any message wording
N/A: “Endpoint-specific errors are listed with each endpoint.” — stage-1.md line 192: pointer to the endpoint tables
95. “400 | `malformed_request` | Unparseable body, or a field of the wrong JSON type” — stage-1.md:196 · W-1 · Includes a body that is not a JSON object, invalid UTF-8, NaN/Infinity literals (see 9003) and chunked bodies (see 9002).
96. “400 | `missing_idempotency_key` | Required `Idempotency-Key` header absent or empty” — stage-1.md:197 · W-1
97. “401 | `unauthenticated` | Missing, malformed or unknown bearer token” — stage-1.md:198 · W-1
98. “403 | `forbidden` | Authenticated, but not permitted to touch this resource” — stage-1.md:199 · W-1
99. “404 | `not_found` | No such resource, or not visible to this caller” — stage-1.md:200 · W-1
100. “409 | `idempotency_key_reuse` | Key already used by this caller with a different request body” — stage-1.md:201 · W-1
101. “422 | `validation_failed` | A required field or query parameter is missing, or a stated rule is violated with no more specific code” — stage-1.md:202 · W-1 · Decision D-2 fixes the order in which errors are evaluated.
102. “A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`, unless an endpoint specifies a different error.” — stage-1.md:204 · W-1
103. “This includes invalid dates, negative counts and values exceeding a stated maximum or length.” — stage-1.md:205 · W-1
N/A: “In addition:” — stage-1.md line 206: connective, introduces entries 105-110
105. “Endpoint-specific field rules take precedence: invalid `amount` values (including strings and” — stage-1.md:208 · W-1
106. “booleans), non-string `note` values (including `null`), and any `visibility` other than `public` or `private` are 422 `validation_failed`.” — stage-1.md:209 · W-1
107. “Omission alone selects the optional-field defaults.” — stage-1.md:210 · W-1
108. “Other wrong JSON types follow the rule below.” — stage-1.md:211 · W-1
109. “An integer-valued **query parameter** is written as plain decimal digits: `1e9`, `4.0` and `+4`” — stage-1.md:212 · W-1
110. “are 422 `validation_failed` whatever their numeric value.” — stage-1.md:213 · W-1
111. “Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type.” — stage-1.md:214 · W-1
112. “Shared ranges, enforced on every endpoint that takes them:” — stage-1.md:216 · W-1
113. “`Idempotency-Key` | 1 to 255 characters | 422 `validation_failed`” — stage-1.md:220 · W-1
114. “`limit` | integer 1 to 200 | 422 `validation_failed`” — stage-1.md:221 · W-1
115. “`offset` | integer 0 or more | 422 `validation_failed`” — stage-1.md:222 · W-1
116. “Requests must not produce 5xx responses, including under concurrent load.” — stage-1.md:224 · W-1 · No 5xx under 50 concurrent requests, including SQLite busy: use BEGIN IMMEDIATE with a busy timeout and serialise writers.
117. “Authentication supports signup and login.” — stage-1.md:228 · W-1
N/A: “Email verification, password reset, refresh tokens and role-management endpoints are out of scope.” — stage-1.md line 228: out-of-scope statement
119. “Permissions specified elsewhere in these requirements still apply.” — stage-1.md:229 · W-1
120. “Email already registered | 409 `email_taken`” — stage-1.md:248 · W-1 · Decision D-6: emails compare case-insensitively; email_taken is checked before handle_taken.
121. “Password shorter than 8 characters | 422 `validation_failed`” — stage-1.md:249 · W-1
122. “`email` not of the form `local@domain` | 422 `validation_failed`” — stage-1.md:250 · W-1
123. “Wrong password or unknown email on login | 401 `unauthenticated`” — stage-1.md:251 · W-1
124. “The handle derived from the email (§4) is already taken | 409 `handle_taken`, and no account is created” — stage-1.md:252 · W-1
125. “Every other endpoint requires a bearer token, except `/health`, `/_test/reset` and the two above.” — stage-1.md:254 · W-1 · Unknown routes are 404 not_found with the §5 body; a known path with the wrong method is 405 method_not_allowed with the §5 body (D-8).
126. “Wallet API endpoints require authentication.” — stage-1.md:255 · W-1
127. “Tokens do not expire.” — stage-1.md:261 · W-1
128. “An account may have multiple valid tokens and concurrent sessions.” — stage-1.md:261 · W-1
129. “Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2, or an equivalent.” — stage-1.md:263 · W-1 · Python stdlib: hashlib.scrypt or pbkdf2_hmac with a per-user salt; keep login under the 5 s timeout with 50 in flight.
130. “Plaintext password storage is not permitted.” — stage-1.md:264 · W-1
131. “Five write paths require an idempotency key (§8 and §11): **`POST /payments`**, **`POST /requests`**, **`POST /requests/{id}/pay`**, **`POST /splits`** and **`POST /settlements`**.” — stage-1.md:268 · W-2
132. “Everything below applies to each of them independently.” — stage-1.md:269 · W-2
133. “The key is scoped to **the authenticated user**.” — stage-1.md:276 · W-2
134. “Two different users may use the same key string with no interaction between them.” — stage-1.md:276 · W-2
135. “A replay means the same user sending the **same method, the same path and the same body**.” — stage-1.md:279 · W-2
136. “The same key with the same body on a different path is a different request, not a replay, and must succeed normally.” — stage-1.md:279 · W-2
137. “Header absent or empty | 400 `missing_idempotency_key`” — stage-1.md:285 · W-2
138. “First use of the key | The normal response, **201**” — stage-1.md:286 · W-2
139. “Replay: same key, same body | **200**, body identical to the original response as a JSON value” — stage-1.md:287 · W-2
140. “Same key, different body | 409 `idempotency_key_reuse`” — stage-1.md:288 · W-2
141. “Key reused after the original request failed with 4xx | Treated as a first use” — stage-1.md:289 · W-2 · 4xx responses are never stored against a key.
142. “"Same body" means the same JSON value after parsing — key order and whitespace do not matter.” — stage-1.md:291 · W-2
143. “For concurrent identical requests with an unused key, exactly one returns 201.” — stage-1.md:293 · W-2 · Claim the key inside the same transaction as the money movement.
144. “The others return 200 with the same body.” — stage-1.md:294 · W-2
145. “The operation takes effect only once.” — stage-1.md:294 · W-2
146. “A successful replay returns the original response, even after the resource changes or is cancelled.” — stage-1.md:296 · W-2
147. “It makes no further state changes.” — stage-1.md:297 · W-2
148. “After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks.” — stage-1.md:299 · W-2 · Order: auth (401) -> JSON object parse (400) -> key present (400) / key length (422) -> claimed-key resolution (200 replay / 409 reuse) -> field validation (422) -> existence (404) -> permission (403) -> state (409).
149. “Thus changing a successful request to an invalid body with the same key still returns `409 idempotency_key_reuse`.” — stage-1.md:300 · W-2
150. “**An idempotent write path.** `Idempotency-Key` is required; see §7.” — stage-1.md:315 · W-2
151. “`note` is optional and defaults to `""`.” — stage-1.md:325 · W-2
152. “`visibility` is optional and defaults to `"public"`.” — stage-1.md:325 · W-2
153. “The caller's balance is below `amount` | 409 `insufficient_funds`” — stage-1.md:346 · W-2
154. “`amount` below 1, above 1000000000, or not an integer | 422 `validation_failed`” — stage-1.md:347 · W-2
155. “`to_handle` is the caller's own handle | 422 `self_payment`” — stage-1.md:348 · W-2
156. “`note` longer than 200 characters | 422 `validation_failed`” — stage-1.md:349 · W-2
157. “`visibility` is neither `public` nor `private` | 422 `validation_failed`” — stage-1.md:350 · W-2
158. “No user has that handle | 404 `not_found`” — stage-1.md:351 · W-2
159. “The debit and the credit are one atomic step.” — stage-1.md:353 · W-2
160. “A payment is never visible in one wallet and not the other, and a failed payment leaves no trace in either.” — stage-1.md:353 · W-2
161. “`note` is stored and returned verbatim: no trimming, no escaping, no normalisation.” — stage-1.md:356 · W-2
162. “Unicode and emoji survive a round trip byte for byte.” — stage-1.md:356 · W-2
163. “**An idempotent write path.**” — stage-1.md:361 · W-2
164. “The caller is the requester.” — stage-1.md:370 · W-2
165. “`amount` below 1, above 1000000000, or not an integer | 422 `validation_failed`” — stage-1.md:391 · W-2
166. “`payer_handle` is the caller's own handle | 422 `self_request`” — stage-1.md:392 · W-2
167. “`note` longer than 200 characters | 422 `validation_failed`” — stage-1.md:393 · W-2
168. “No user has that handle | 404 `not_found`” — stage-1.md:394 · W-2
169. “**The payer's balance is not checked here.** A request for more than the payer holds is created normally and sits `pending`.” — stage-1.md:396 · W-2
170. “**An idempotent write path.** Only the payer may call it.” — stage-1.md:401 · W-2
171. “The body carries `visibility` only, optional, default `"public"`.” — stage-1.md:410 · W-2
172. “It is the payer's choice, not the requester's.” — stage-1.md:410 · W-2
173. “**A replay must send the identical body** — `{}` and `{"visibility": "public"}` are different JSON values, so reusing a key across the two is `409 idempotency_key_reuse`, per §7.” — stage-1.md:411 · W-2 · Body equality is JSON-value equality; {} differs from {"visibility":"public"}.
174. “Returns `201` with the created **payment**, exactly as `POST /payments` returns one, with `request_id` set to this request.” — stage-1.md:414 · W-2
175. “The request becomes `paid` and carries the new `payment_id`.” — stage-1.md:415 · W-2
176. “The request is not `pending` | 409 `request_not_pending`” — stage-1.md:419 · W-2 · Decision D-2: for pay, 404 then 403 then request_not_pending then insufficient_funds.
177. “The payer's balance is below `amount` | 409 `insufficient_funds`” — stage-1.md:420 · W-2
178. “The caller is not the request's payer | 403 `forbidden`” — stage-1.md:421 · W-2
179. “Unknown request | 404 `not_found`” — stage-1.md:422 · W-2
180. “Replaying a successful payment returns 200 with its original payment body, including when the request is already `paid`.” — stage-1.md:424 · W-2
181. “It moves no additional money and must not return `409 request_not_pending`.” — stage-1.md:425 · W-2
182. “Only the payer.” — stage-1.md:430 · W-2
183. “No idempotency key.” — stage-1.md:430 · W-2
184. “Returns `200` with the request, `status: "declined"`.” — stage-1.md:430 · W-2
185. “Declining an already-declined request is `200` with the current state — declining twice is not an error.” — stage-1.md:430 · W-2 · Decline/cancel are naturally idempotent on their own terminal state only.
186. “A `paid` or `cancelled` request is `409 request_not_pending`.” — stage-1.md:432 · W-2
187. “Not the payer is `403 forbidden`.” — stage-1.md:432 · W-2
188. “Only the requester.” — stage-1.md:436 · W-2
189. “No idempotency key.” — stage-1.md:436 · W-2
190. “Returns `200` with the request, `status: "cancelled"`.” — stage-1.md:436 · W-2
191. “Cancelling an already-cancelled request is `200`.” — stage-1.md:437 · W-2
192. “A `paid` or `declined` request is `409 request_not_pending`.” — stage-1.md:437 · W-2
193. “Not the requester is `403 forbidden`.” — stage-1.md:438 · W-2
194. “Requests where the caller is the requester or the payer, and no others.” — stage-1.md:446 · W-2
195. “Newest first by `created_at`.” — stage-1.md:446 · W-2 · Decision D-5: ties broken by insertion order, newest first, so pagination is deterministic.
196. “`direction` is `incoming` (the caller is the payer), `outgoing` (the caller is the requester) or” — stage-1.md:449 · W-2
197. “absent for both.” — stage-1.md:450 · W-2
198. “`status` is one of the four statuses, or absent for all.” — stage-1.md:451 · W-2
199. “`limit` defaults to 50, range 1 to 200.” — stage-1.md:452 · W-2
200. “`offset` defaults to 0 and must be 0 or more.” — stage-1.md:452 · W-2
201. “Outside” — stage-1.md:452 · W-2
202. “either range is 422 `validation_failed`.” — stage-1.md:453 · W-2
203. “An unknown `direction` or `status` value is also 422.” — stage-1.md:453 · W-2
204. “`has_more` is true when items exist beyond the last one returned.” — stage-1.md:454 · W-2 · has_more = offset+returned < total matching.
205. “**An idempotent write path.** Splits an amount the caller already paid, and asks each of the other participants for their share by creating one `pending` request each.” — stage-1.md:462 · W-3
206. “The caller may be included in `participant_handles` or omitted.” — stage-1.md:472 · W-3
207. “Shares follow the equal-split rule in §9, in the order the handles are given.” — stage-1.md:472 · W-3
208. “**A request is created for every participant except the caller**, each for that participant's share, with the caller as requester.” — stage-1.md:473 · W-3
209. “`shares` covers every participant including the caller, in the order given, and always sums to `amount`.” — stage-1.md:491 · W-3
210. “`requests` covers every participant except the caller, in the same order.” — stage-1.md:492 · W-3
211. “`amount` below 1, above 1000000000, or not an integer | 422 `validation_failed`” — stage-1.md:496 · W-3
212. “`participant_handles` empty, or containing a duplicate handle | 422 `validation_failed`” — stage-1.md:497 · W-3
213. “`note` longer than 200 characters | 422 `validation_failed`” — stage-1.md:498 · W-3
214. “Any handle is unknown | 404 `not_found`” — stage-1.md:499 · W-3
215. “A split whose only participant is the caller is **valid**: it computes one share, creates zero requests, and returns `"requests": []`.” — stage-1.md:501 · W-3
216. “Nothing about a split checks anyone's balance.” — stage-1.md:502 · W-3
217. “Payments visible to the caller by the feed contract in §4, newest first by `created_at`.” — stage-1.md:510 · W-2
218. “The relative order of two payments created within the same second is unspecified.” — stage-1.md:516 · W-2 · Checks must not assert the order of same-second payments.
219. “Stable pagination during concurrent writes is not required for this endpoint.” — stage-1.md:517 · W-2
220. “`limit` and `offset` behave exactly as in `GET /requests`.” — stage-1.md:518 · W-2
221. “Shares must be whole minor units, sum exactly to `amount` and differ by at most one minor unit.” — stage-1.md:522 · W-3
222. “When the amount does not divide evenly, the larger shares go to the first participants in `participant_handles` order.” — stage-1.md:523 · W-3
223. “1000 | 3 | 334, 333, 333” — stage-1.md:528 · W-3
224. “1 | 3 | 1, 0, 0” — stage-1.md:529 · W-3
225. “10 | 3 | 4, 3, 3” — stage-1.md:530 · W-3
226. “999 | 3 | 333, 333, 333” — stage-1.md:531 · W-3
227. “5 | 5 | 1, 1, 1, 1, 1” — stage-1.md:532 · W-3
228. “Splitting the same amount among the same people in a different `participant_handles` order gives the extra unit to a different person.” — stage-1.md:534 · W-3
229. “A share of `0` is legal and still produces a request for that participant.” — stage-1.md:535 · W-3
230. “Each split's shares are independent of previous splits.” — stage-1.md:538 · W-3
231. “After any number of splits have been paid in full, wallet balances must still sum exactly to the seeded total.” — stage-1.md:538 · W-3 · Invariant, checked after the split-and-pay concurrency attack.
232. “The service must support `GET /_test/export` and `POST /_test/import`.” — stage-1.md:543 · W-4
233. “Like reset, these are unauthenticated test endpoints.” — stage-1.md:543 · W-4
234. “Exports may contain credentials and session tokens; handle them as private test artifacts.” — stage-1.md:545 · W-4
235. “Return 200 from export with a JSON object containing `track: "pocketful"`, `format_version: 1` and `state` (an implementation-defined JSON object).” — stage-1.md:546 · W-4
236. “The state format is opaque to the caller and must be accepted unchanged by import.” — stage-1.md:547 · W-4 · Export state may be any JSON object; include idempotency records and tokens.
237. “Import takes that entire object and atomically replaces the service's state, returning” — stage-1.md:550 · W-4
238. “It must accept an unchanged export produced by this service.” — stage-1.md:551 · W-4
239. “No dependency on the” — stage-1.md:551 · W-4
240. “source process, files, volume, port or network address is allowed.” — stage-1.md:552 · W-4
241. “Import is replacement, not merge; repeating it restores the exported state without duplicating anything.” — stage-1.md:552 · W-4
242. “Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination.” — stage-1.md:553 · W-4
243. “Test control calls have a 10-second timeout.” — stage-1.md:555 · W-4
244. “Export is an atomic, read-only snapshot; subsequent source writes do not change it.” — stage-1.md:556 · W-4 · Export runs inside one read transaction.
245. “Preserve accounts and hashed-password login, existing bearer tokens, currency, balances, payments, requests, permissions, all completed idempotent request bodies and original responses.” — stage-1.md:558 · W-4
246. “Identities, timestamps and monetary records must not be regenerated or replayed against an already-net balance.” — stage-1.md:560 · W-4
247. “Failed request keys remain reusable.” — stage-1.md:561 · W-4
248. “Existing receipts, tokens and retries must remain valid after import; replacing the state with a fresh fixture does not satisfy this requirement.” — stage-1.md:561 · W-4
249. “Import removes all previous destination data and credentials.” — stage-1.md:563 · W-4
250. “Reset clears all state, including imported state.” — stage-1.md:564 · W-4
251. “State need not survive an abrupt container restart.” — stage-1.md:564 · W-4
252. “The reset fixture may include `settlement_operator_ids`, an array of user ids, default [].” — stage-1.md:569 · W-4 · settlement_operator_ids is preserved by export/import.
253. “An operator may execute a settlement across any wallets.” — stage-1.md:570 · W-4
254. “This permission does not grant access to another user's requests or private activity items.” — stage-1.md:570 · W-4
255. “`POST /settlements` requires an operator and an idempotency key.” — stage-1.md:573 · W-4
256. “No token gives 401; authenticated non-operator gives 403 `forbidden`.” — stage-1.md:573 · W-4
N/A: “Body:” — stage-1.md line 574: label for the example body
258. “transfers contains 1..32 objects.” — stage-1.md:581 · W-4
259. “Each uses ordinary payment amount, note and visibility rules (defaults: empty note, public).” — stage-1.md:581 · W-4
260. “Unknown handle is 404; self-transfer is 422 `self_payment`; malformed batch shape is 422 `validation_failed`.” — stage-1.md:582 · W-4
261. “Entry errors take precedence in input order, before insufficient funds.” — stage-1.md:583 · W-4 · Decision D-9: validate entries in input order; the first failing entry decides the error (422/404), and only when every entry is valid is affordability (409) evaluated.
262. “Unknown fields are ignored.” — stage-1.md:584 · W-4
263. “A settlement is affordable when every wallet's balance after all incoming and outgoing transfers is nonnegative.” — stage-1.md:586 · W-4 · Net effect per wallet, evaluated against the balance at commit time inside the transaction.
264. “Insufficient collective funds gives 409 `insufficient_funds`.” — stage-1.md:587 · W-4
265. “Either all movements commit together or none do; failed validation claims no idempotency key and creates no payment or revision.” — stage-1.md:588 · W-4
266. “Return 201 with `settlement_id`, `committed_at` and `payments` in input order.” — stage-1.md:591 · W-4
267. “Every member is an ordinary payment with `settlement_id` linking the batch; nonmembers expose null for that field.” — stage-1.md:591 · W-4
268. “Members have null request_id and the same server-assigned created_at, equal to committed_at.” — stage-1.md:593 · W-4
269. “Constituents follow ordinary activity-feed visibility.” — stage-1.md:596 · W-4
270. “The settlement response contains every member's receipt.” — stage-1.md:596 · W-4
271. “Replays return 200 with the original complete response.” — stage-1.md:597 · W-4
272. “This is the fifth idempotent write path in stage 1.” — stage-1.md:598 · W-4
273. “A reset/import must preserve settlement operator permissions, original payments, requests, settlement membership and retry responses.” — stage-1.md:599 · W-4


## Stage 2 entries

1001. “The stage-1 requirements continue to apply, with the additions below.” — stage-2.md:3 · W-8
1002. “Numbered section references such as §5 and §7 refer to `stage-1.md`.” — stage-2.md:3 · W-8
N/A: “Users can manage payments, requests and bill splits in a browser.” — stage-2.md line 6: scope summary; behaviour has its own entries
N/A: “They can also reserve money for a recipient to collect later, in one or more captures.” — stage-2.md line 6: scope summary; see 1102-1106
1005. “The following screens must be reachable by URL.” — stage-2.md:9 · W-7
1006. “Other screens must be reachable through the UI.” — stage-2.md:9 · W-7
N/A: “Server-side and client-side rendering are both permitted.” — stage-2.md line 10: permission, no obligation
1008. “`/` | Balance, pay form, request form and the activity feed” — stage-2.md:14 · W-7
1009. “`/requests` | Incoming and outgoing requests, with pay, decline and cancel” — stage-2.md:15 · W-7
1010. “`/split` | Split form” — stage-2.md:16 · W-7
1011. “`/signup` | Signup” — stage-2.md:17 · W-7
1012. “`/login` | Login” — stage-2.md:18 · W-7
1013. “The browser and the API share `/requests`.” — stage-2.md:20 · W-8
1014. “Return the UI for `Accept: text/html`; API requests without that header receive JSON.” — stage-2.md:20 · W-8 · Builder serves the UI files listed by Builder-Two (ui-core/README.md) for Accept containing text/html; everything else stays JSON.
1015. “The UI must expose the `data-testid` attributes listed below for integration testing.” — stage-2.md:23 · W-7
1016. “Additional elements are permitted, and the visual implementation is the team's choice subject to the product-quality requirements below.” — stage-2.md:24 · W-D, W-7
1017. “The browser experience must feel like a coherent, presentation-ready consumer finance product, not a test harness with controls attached.” — stage-2.md:29 · W-D, W-7
1018. “Aim for a calm, trustworthy character.” — stage-2.md:30 · W-D, W-7
1019. “Available funds must be the clearest monetary value once holds exist, with total and held funds visibly secondary.” — stage-2.md:30 · W-D, W-7
1020. “Payments, requests, splits and authorisations should be easy to scan, and status, direction, privacy and money movement should be understandable without interpreting raw API data.” — stage-2.md:32 · W-D, W-7
1021. “Use a consistent visual system for typography, spacing, colour, controls and feedback.” — stage-2.md:35 · W-D, W-7
1022. “Primary actions must be easy to identify.” — stage-2.md:35 · W-D, W-7
1023. “Available, held, pending, loading, successful, refused and uncertain states must be visually distinct as well as satisfying the behavioural requirements below.” — stage-2.md:36 · W-D, W-7
1024. “Format people, amounts and timestamps for people first; expose technical identifiers only where they help the user.” — stage-2.md:38 · W-D, W-7
1025. “The required flows must remain clear and usable at a 375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling.” — stage-2.md:41 · W-D, W-7
1026. “Inputs need visible labels, keyboard focus must be apparent, and text and controls need sufficient contrast.” — stage-2.md:42 · W-D, W-7
1027. “Provide considered empty, loading and error states, and keep navigation consistent across the required routes.” — stage-2.md:43 · W-D, W-7
N/A: “A custom illustration, brand asset or exact visual match to a reference is not required.” — stage-2.md line 44: permission, no obligation
1029. “`signup-email`, `signup-password`, `signup-display-name` | Inputs” — stage-2.md:51 · W-7
1030. “`signup-submit` | Button” — stage-2.md:52 · W-7
1031. “`login-email`, `login-password`, `login-submit` | Inputs and button” — stage-2.md:53 · W-7
1032. “`auth-error` | Error message. Present only when there is one” — stage-2.md:54 · W-7
1033. “`current-user` | Visible on every screen when signed in. Text contains the display name” — stage-2.md:55 · W-7
1034. “`current-handle` | Text is exactly the caller's handle, with no `@` and no surrounding words” — stage-2.md:56 · W-7
1035. “`logout-button` | Button” — stage-2.md:57 · W-7
1036. “`wallet-balance` | Text is exactly the formatted amount. Carries `data-amount="{minor units}"`” — stage-2.md:63 · W-7
1037. “`pay-handle`, `pay-amount`, `pay-note` | Inputs. `pay-amount` is a **decimal** string as a person would type it, e.g. `15.00`” — stage-2.md:64 · W-7
1038. “`pay-visibility` | Selects `public` or `private`. Option values are those two strings” — stage-2.md:65 · W-7
1039. “`pay-submit` | Button” — stage-2.md:66 · W-7
1040. “`pay-error` | Error message, when the payment is refused — including insufficient funds” — stage-2.md:67 · W-7
1041. “`request-handle`, `request-amount`, `request-note`, `request-submit` | The request form” — stage-2.md:68 · W-7
1042. “`request-error` | Error message, when the request is refused” — stage-2.md:69 · W-7
1043. “Keep the pay form's values after success.” — stage-2.md:71 · W-7
1044. “Submitting it again without changing a field must not send another payment: `wallet-balance` falls once, the feed contains one payment and `pay-error` is absent.” — stage-2.md:71 · W-7
1045. “Changing a field makes the next submission a new payment request.” — stage-2.md:73 · W-7
1046. “Retries follow §7.” — stage-2.md:74 · W-7
1047. “**Formatted amount.** `wallet-balance` is the decimal with exactly `minor_units` decimal places, a single space, then the currency code: `100.00 EUR`.” — stage-2.md:76 · W-7
1048. “For a `minor_units` of `0` there is no decimal point at all: `1200 JPY`.” — stage-2.md:77 · W-7
1049. “Balances are never negative, so there is no sign.” — stage-2.md:78 · W-7
1050. “The form accepts decimal amounts and submits minor units to the API.” — stage-2.md:80 · W-7
1051. “With `minor_units: 2`, `15.00` and `15` both submit `1500`; `15.5` submits `1550`.” — stage-2.md:80 · W-7
1052. “Nonnumeric input or more than `minor_units` decimal places must show the form's error element without sending a request.” — stage-2.md:81 · W-7
1053. “For example, `15.005` is rejected rather than rounded.” — stage-2.md:83 · W-7
1054. “`activity-list` | Container. Its children are newest first in the DOM” — stage-2.md:89 · W-7
1055. “`activity-item-{payment_id}` | One per visible payment. Carries `data-visibility="public"` or `data-visibility="private"`” — stage-2.md:90 · W-7
1056. “`activity-parties-{payment_id}` | Text contains both handles” — stage-2.md:91 · W-7
1057. “`activity-amount-{payment_id}` | Text is exactly the formatted amount” — stage-2.md:92 · W-7
1058. “`activity-note-{payment_id}` | Text is exactly the note. Present even when the note is empty” — stage-2.md:93 · W-7
1059. “`empty-activity` | Shown instead of the list when nothing is visible” — stage-2.md:94 · W-7
1060. “Two payments with equal timestamps may appear in either order.” — stage-2.md:96 · W-7
1061. “`incoming-list`, `outgoing-list` | Containers” — stage-2.md:102 · W-7
1062. “`request-item-{request_id}` | One per request. Carries `data-status="{status}"`” — stage-2.md:103 · W-7
1063. “`request-amount-{request_id}` | Text is exactly the formatted amount” — stage-2.md:104 · W-7
1064. “`request-pay-{request_id}` | Button. Present only on a `pending` incoming request” — stage-2.md:105 · W-7
1065. “`request-decline-{request_id}` | Button. Present only on a `pending` incoming request” — stage-2.md:106 · W-7
1066. “`request-cancel-{request_id}` | Button. Present only on a `pending` outgoing request” — stage-2.md:107 · W-7
1067. “`request-error` | Shown when a pay, decline or cancel is refused” — stage-2.md:108 · W-7
1068. “`empty-requests` | Shown when both lists are empty” — stage-2.md:109 · W-7
1069. “`split-amount` | Decimal input, same rule as `pay-amount`” — stage-2.md:115 · W-7
1070. “`split-handles` | Text input: handles separated by commas, in order” — stage-2.md:116 · W-7
1071. “`split-note`, `split-submit` | Input and button” — stage-2.md:117 · W-7
1072. “`split-preview` | Shows the computed shares before submitting. Contains one `split-share-{handle}` per participant” — stage-2.md:118 · W-7
1073. “`split-share-{handle}` | Text is exactly the formatted share amount” — stage-2.md:119 · W-7
1074. “`split-error` | Error message, when the split is refused” — stage-2.md:120 · W-7
1075. “`split-preview` must show the shares the server would compute, by the rule in `stage-1.md` §9, before anything is posted.” — stage-2.md:122 · W-7
1076. “The preview and submitted split must have identical shares.” — stage-2.md:123 · W-7
1077. “After any successful action, the balance, the feed and the request lists on the same page must show the new state without a manual reload.” — stage-2.md:125 · W-7
1078. “Navigation must wait for the write to succeed before it refreshes the data.” — stage-2.md:126 · W-7
N/A: “Any mechanism is fine, including a full navigation.” — stage-2.md line 127: permission: any refresh mechanism
1080. “**There is no live-update requirement here** — another client may change state, but this browser need only refresh after its own action or an explicit refresh.” — stage-2.md:127 · W-7
1081. “Add `wallet-refresh`, a button on `/` that refreshes the balance and feed without clearing” — stage-2.md:133 · W-7
1082. “the pay form.” — stage-2.md:134 · W-7
1083. “**Latest refresh wins:** a delayed earlier read must not overwrite a later refresh, including when responses arrive out of order.” — stage-2.md:134 · W-7
1084. “Another client may spend the balance after this browser reads it.” — stage-2.md:136 · W-7
1085. “A refused payment shows” — stage-2.md:136 · W-7
1086. “`pay-error`, refreshes the balance/feed, and preserves all pay inputs.” — stage-2.md:137 · W-7
1087. “A request cancelled elsewhere while its pay button is visible must show `request-error` when payment is refused and refresh the request list so the stale pay button disappears.” — stage-2.md:137 · W-7
1088. “If a payment response is lost, including after `POST /payments` commits, show `pay-uncertain`” — stage-2.md:140 · W-7
1089. “(nonempty text), not `pay-error`.” — stage-2.md:141 · W-7
1090. “Keep the unchanged form retryable with the **same key and body**.” — stage-2.md:141 · W-7
1091. “Successful retry removes both error/uncertainty elements, refreshes the balance and feed, and moves money exactly once.” — stage-2.md:142 · W-7
1092. “Unknown outcomes are not confirmed rejections.” — stage-2.md:143 · W-7
N/A: “No background polling, live synchronization, or recovery across page reloads is required.” — stage-2.md line 145: permission: no polling or reload recovery required
1094. “The same balance refresh rules apply to the available and held amounts introduced below.” — stage-2.md:146 · W-7
1095. “A stage-2 service must accept an export produced by the same team's stage-1 service.” — stage-2.md:150 · W-8 · Decision D-12: export keeps format_version 1; stage-2 import accepts a stage-1 export (no authorizations means none; tokens, keys and responses preserved).
1096. “A browser signed in before that export/import upgrade must remain signed in afterwards.” — stage-2.md:150 · W-7
1097. “Existing pending requests remain payable through the request screen.” — stage-2.md:152 · W-7
1098. “A payment whose response was lost before export remains retryable after import with the same body and key; the UI must recover the original payment and refresh the imported balance.” — stage-2.md:152 · W-7
N/A: “These requirements apply when import completes between browser requests; migration during an in-flight request is not required.” — stage-2.md line 154: permission: no in-flight migration required
N/A: “No page reload or new screen is required.” — stage-2.md line 156: permission
1101. “The form and pending retry identity must survive the upgrade.” — stage-2.md:156 · W-7
1102. “A payment may be **authorised** now and **captured** later, for the full amount or less.” — stage-2.md:161 · W-8
1103. “An authorisation places a *hold* on the payer's wallet: it reserves money without moving it.” — stage-2.md:161 · W-8
1104. “Capturing moves the money; a final capture also releases whatever was not captured.” — stage-2.md:162 · W-8
1105. “Nonfinal captures keep the remainder held.” — stage-2.md:163 · W-8
1106. “An open authorisation expires and releases its remainder on its own.” — stage-2.md:164 · W-8
1107. “The sum of all wallet `total` values always equals the total seeded by the last reset.” — stage-2.md:166 · W-8 · Invariant, checked after every concurrency attack.
1108. “A hold moves no money; payments, settlements and captures transfer money between wallets.” — stage-2.md:167 · W-8
1109. “`available = total − held` must never be negative.” — stage-2.md:168 · W-8 · Invariant: available never negative, including transiently.
1110. “Held funds cannot fund new payments,” — stage-2.md:168 · W-8
1111. “authorizations or settlement net debits.” — stage-2.md:169 · W-8
1112. “Captures may spend the money reserved for them.” — stage-2.md:169 · W-8
1113. “Cumulative captures must not exceed the authorized amount.” — stage-2.md:170 · W-8
1114. “Each idempotent capture moves” — stage-2.md:170 · W-8
1115. “money once.” — stage-2.md:171 · W-8
1116. “A closed hold cannot be captured again.” — stage-2.md:171 · W-8
N/A: “The existing API changes as follows:” — stage-2.md line 173: connective, introduces 1118-1132
1118. “`GET /me` keeps `balance`, and `balance` **equals `total`**.” — stage-2.md:175 · W-8
1119. “`available` and `held` are new” — stage-2.md:175 · W-8
1120. “fields beside it.” — stage-2.md:176 · W-8
1121. “With no open holds, `balance`, `total` and `available` agree and `held` is zero, and every earlier behaviour is unchanged.” — stage-2.md:176 · W-8
1122. “`POST /payments` remains an immediate transfer.” — stage-2.md:178 · W-8
1123. “It must not leave an intermediate hold” — stage-2.md:178 · W-8
1124. “or require a separate capture.” — stage-2.md:179 · W-8
1125. “Every `409 insufficient_funds` in stage 1 — on `POST /payments`,” — stage-2.md:180 · W-8
1126. “`POST /requests/{id}/pay` and settlements — is now evaluated against `available`.” — stage-2.md:181 · W-8
1127. “With no open holds, the result is unchanged.” — stage-2.md:182 · W-8
1128. “Paying a request remains immediate.” — stage-2.md:183 · W-8
N/A: “Authorizing a request is out of scope.” — stage-2.md line 183: out-of-scope statement
1130. “`POST /splits` is unchanged.” — stage-2.md:184 · W-8
1131. “There are now seven idempotent write paths: stage 1's five, authorizations and captures.” — stage-2.md:185 · W-8
1132. “The same replay rules apply independently to each.” — stage-2.md:186 · W-8
N/A: “The fixture gains a service-wide default lifetime and an `authorizations` array.” — stage-2.md line 190: describes the fixture example; rules are 1134-1150
1134. “`authorization_ttl_seconds` applies to every authorisation created through the API.” — stage-2.md:206 · W-8
1135. “It defaults” — stage-2.md:206 · W-8
1136. “to 600 when omitted.” — stage-2.md:207 · W-8
1137. “If supplied, it must be a positive integer number of seconds.” — stage-2.md:207 · W-8
1138. “Seeded authorisations carry their own absolute `expires_at` instead.” — stage-2.md:208 · W-8
1139. “A user's seeded `balance` is still `total`.” — stage-2.md:209 · W-8
1140. “**`available` is derived, never seeded** — the service” — stage-2.md:209 · W-8
1141. “subtracts the seeded open holds itself.” — stage-2.md:210 · W-8
1142. “A sum of seeded unexpired open holds larger than that user's `balance` is a reset error:” — stage-2.md:211 · W-8
1143. “`422 validation_failed` from `POST /_test/reset`, changing nothing, exactly like a negative seeded balance.” — stage-2.md:212 · W-8
1144. “Seeded `status` is `open`, `captured`, `voided` or `expired`.” — stage-2.md:214 · W-8
1145. “Only `open` holds anything.” — stage-2.md:214 · W-8
1146. “An earlier fixture may omit `authorizations` altogether; omission means an empty list.” — stage-2.md:215 · W-8
1147. “An authorization whose `expires_at` is at or before now is `expired` and holds no funds.” — stage-2.md:217 · W-8 · Expiry is computed from the clock at every read and write, never by a background job alone.
1148. “Reads and writes must reflect expiry even if no request occurred at the deadline.” — stage-2.md:218 · W-8
1149. “`GET /authorizations` must show `status: "expired"`, and `GET /me` must include the released remainder in `available`.” — stage-2.md:219 · W-8
1150. “Seeded expiry times are at least an hour from reset time, in the past or future; newly created authorizations may have shorter lifetimes.” — stage-2.md:220 · W-8
1151. “`balance` and `total` are always equal.” — stage-2.md:234 · W-8
1152. “`held` is the sum of open holds, and `available` is `total − held`, never negative.” — stage-2.md:234 · W-8
1153. “`Idempotency-Key` is required.” — stage-2.md:239 · W-8
1154. “The caller is the payer.” — stage-2.md:239 · W-8
1155. “`note` and `visibility` are optional with the same defaults as `POST /payments`.” — stage-2.md:245 · W-8
1156. “`expires_at` is `created_at` plus `authorization_ttl_seconds`.” — stage-2.md:265 · W-8
1157. “The caller's `available` is below `amount` | 409 `insufficient_funds`” — stage-2.md:269 · W-8
1158. “`amount` below 1, above 1000000000, or not an integer | 422 `validation_failed`” — stage-2.md:270 · W-8
1159. “`to_handle` is the caller's own handle | 422 `self_payment`” — stage-2.md:271 · W-8
1160. “`note` over 200 characters, or `visibility` neither `public` nor `private` | 422 `validation_failed`” — stage-2.md:272 · W-8
1161. “No user has that handle | 404 `not_found`” — stage-2.md:273 · W-8
1162. “An open authorisation is **not** a feed item and never appears in `GET /activity`.” — stage-2.md:275 · W-8
1163. “`Idempotency-Key` is required.” — stage-2.md:279 · W-8
1164. “Only the receiver (the `to` party) may capture.” — stage-2.md:279 · W-8
1165. “`amount` is optional and defaults to the authorisation's remaining amount.” — stage-2.md:285 · W-8
1166. “As on `POST /requests/{id}/pay`, **a replay must send the identical body** — `{}` and `{"amount": 2000}` are different JSON values even when they mean the same capture, so reusing a key across the two is 409 `idempotency_key_reuse` per `stage-1.md` §7.” — stage-2.md:285 · W-8
1167. “Returns `201` with the created **payment**, in exactly the shape `POST /payments` returns, with `authorization_id` set to this authorisation and `request_id: null`.” — stage-2.md:290 · W-8
1168. “The payment's `amount` is the captured amount; its `note` and `visibility` are copied from the authorisation; it appears in the activity feed by the ordinary visibility rule.” — stage-2.md:291 · W-8
1169. “Payments created without an authorisation carry `authorization_id: null`; their existing `request_id` semantics are unchanged.” — stage-2.md:293 · W-8
1170. “By default the authorisation becomes `captured`, carries `captured_amount` and `payment_id`, and **releases the uncaptured remainder immediately**: capturing 1500 of 2000 returns 500 to the payer's `available` in the same step.” — stage-2.md:296 · W-8
1171. “**Default: one final capture per authorisation.** A second capture after a final capture is `409 authorization_not_open`.” — stage-2.md:300 · W-8 · Decision D-14: capture order: auth, body, key resolution, 422 amount type/range, 404, 403, 409 authorization_not_open, 409 authorization_expired, 422 capture_exceeds_authorization.
1172. “**Extended capture mode.** To keep the remainder held, send `{"amount": 700, "final": false}`.” — stage-2.md:303 · W-8
1173. “`final` is boolean, default `true`, so earlier single-capture requests retain their behavior.” — stage-2.md:304 · W-8
1174. “With `final: false` and an uncaptured remainder, status stays `open`; further captures are allowed up to that remainder.” — stage-2.md:305 · W-8
1175. “Capturing the entire remainder closes it even with `final: false`.” — stage-2.md:306 · W-8
1176. “A final capture closes it and releases any remainder.” — stage-2.md:307 · W-8
1177. “`capture_exceeds_authorization` compares with the **remaining** amount; omitted amount defaults to that remainder.” — stage-2.md:307 · W-8
1178. “`captured_amount` is cumulative; `payment_id` is the latest capture; `payment_ids` lists every capture in order.” — stage-2.md:308 · W-8
1179. “Every authorization response adds `remaining_amount`: the amount still held, zero when closed.” — stage-2.md:310 · W-8
1180. “Void and expiry can close a partially captured authorization, release only the remainder, and preserve all capture records.” — stage-2.md:311 · W-8
1181. “New fields do not change idempotency body equality.” — stage-2.md:312 · W-8
1182. “The authorisation is not `open` | 409 `authorization_not_open`” — stage-2.md:316 · W-8
1183. “`expires_at` is at or before now | 409 `authorization_expired`” — stage-2.md:317 · W-8 · D-14: a stored-open authorisation past expires_at is authorization_expired; voided/captured/expired-status is authorization_not_open.
1184. “`amount` above the authorisation's uncaptured remainder | 422 `capture_exceeds_authorization`” — stage-2.md:318 · W-8
1185. “`amount` below 1, or not an integer | 422 `validation_failed`” — stage-2.md:319 · W-8
1186. “The caller is not the receiver | 403 `forbidden`” — stage-2.md:320 · W-8
1187. “Unknown authorisation | 404 `not_found`” — stage-2.md:321 · W-8
1188. “**Only the payer may void** — the `from` party releasing their own hold.” — stage-2.md:325 · W-8
1189. “No idempotency key, like decline and cancel.” — stage-2.md:325 · W-8
1190. “`200` with the authorisation, `status: "voided"`, the hold released.” — stage-2.md:328 · W-8
1191. “Voiding an already-voided authorisation is `200` with the current state.” — stage-2.md:328 · W-8
1192. “A `captured` or `expired` one is `409 authorization_not_open`.” — stage-2.md:329 · W-8
1193. “For an existing authorization, capture and void return 403 `forbidden` when the caller is not the permitted party, including callers who are neither party.” — stage-2.md:332 · W-8
1194. “`GET /authorizations` returns only authorizations involving the caller.” — stage-2.md:333 · W-8
1195. “Authorisations where the caller is the payer or the receiver, and no others.” — stage-2.md:342 · W-8
1196. “Newest first by `created_at`.” — stage-2.md:342 · W-8
1197. “`direction` is `outgoing` (the caller is the payer), `incoming` (the caller is the receiver), or” — stage-2.md:345 · W-8
1198. “absent for both.” — stage-2.md:346 · W-8
1199. “`status` is one of the four statuses, or absent for all.” — stage-2.md:347 · W-8
1200. “An authorisation expired by the clock” — stage-2.md:347 · W-8
1201. “matches `expired`, never `open`.” — stage-2.md:348 · W-8
1202. “`limit`, `offset` and `has_more` behave exactly as on `GET /requests`.” — stage-2.md:349 · W-8
1203. “A new route `/authorizations`, and the wallet gains two numbers.” — stage-2.md:353 · W-7
1204. “The UI and the API share `/authorizations`: serve HTML for `Accept: text/html` and JSON otherwise, as for `/requests`.” — stage-2.md:353 · W-8
1205. “`wallet-balance` | Formatted `total`, retaining the existing display and `data-amount`” — stage-2.md:358 · W-7
1206. “`wallet-available` | Formatted `available`, with `data-amount`. **Present this as the headline number** — it is what the user can actually spend” — stage-2.md:359 · W-7
1207. “`wallet-held` | Formatted `held`, with `data-amount`. Absent when `held` is zero” — stage-2.md:360 · W-7
1208. “`authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit` | The authorise form. Same input rules as the pay form” — stage-2.md:361 · W-7 · Decision D-11: the authorize form is on both / and /authorizations (the spec ties it to no route).
1209. “`authorize-error` | Shown when the authorisation is refused, including insufficient available funds” — stage-2.md:362 · W-7
1210. “`authorization-list` | Container on `/authorizations`. Children newest first in the DOM” — stage-2.md:363 · W-7
1211. “`authorization-item-{authorization_id}` | Carries `data-status="{status}"`” — stage-2.md:364 · W-7
1212. “`authorization-amount-{id}` | Text is exactly the formatted authorised amount” — stage-2.md:365 · W-7
1213. “`authorization-captured-{id}` | Formatted captured amount. Present only when `status` is `captured`” — stage-2.md:366 · W-7
1214. “`authorization-expires-{id}` | Text is the RFC 3339 `expires_at`” — stage-2.md:367 · W-7
1215. “`authorization-capture-amount-{id}` | Decimal input, pre-filled with the remaining amount. Present only on an incoming `open` authorisation” — stage-2.md:368 · W-7 · An authorization expired by the clock is not open: no capture input.
1216. “`authorization-capture-{id}` | Button. Present only on an incoming `open` authorisation” — stage-2.md:369 · W-7
1217. “`authorization-void-{id}` | Button. Present only on an outgoing `open` authorisation” — stage-2.md:370 · W-7
1218. “`authorization-error` | Shown when a capture or a void is refused” — stage-2.md:371 · W-7
1219. “`empty-authorizations` | Shown when the list is empty” — stage-2.md:372 · W-7
1220. “The UI must reflect seeded and newly created holds.” — stage-2.md:374 · W-7
1221. “Show available funds as the user's spending balance, including immediately after reset with open holds.” — stage-2.md:374 · W-7
1222. “Concurrent requests must produce the same results as executing them one at a time in some order, and the requirements above hold at every read.” — stage-2.md:379 · W-8


## Stage 3 entries

2001. “The requirements from stages 1 and 2 continue to apply, with the additions below.” — stage-3.md:3 · W-9
2002. “Numbered section references such as §5 and §7 refer to `stage-1.md`.” — stage-3.md:4 · W-9
N/A: “Users can request historical balances and paginated statements.” — stage-3.md line 6: scope summary
N/A: “Senders can correct eligible payments while preserving the original receipt.” — stage-3.md line 6: scope summary; see 2046-2066
N/A: “Historical queries must support both the effective date of a payment and the information available at a specified time.” — stage-3.md line 7: scope summary; see 2070-2083
2006. “Every payment's `created_at` is an RFC 3339 instant with an offset identifying when it moved money.” — stage-3.md:12 · W-9
2007. “Every endpoint returning a payment includes it.” — stage-3.md:13 · W-9
2008. “`GET /activity` retains its existing ordering by this field.” — stage-3.md:13 · W-9
2009. “Seeded payments may supply `created_at`; omission uses reset time, before subsequent API-created payments.” — stage-3.md:16 · W-9
2010. “A seeded `created_at` in the future gives `422 validation_failed` from `POST /_test/reset`, with no state change.” — stage-3.md:17 · W-9
2011. “A fixture's `balance` remains the balance after all seeded payments.” — stage-3.md:20 · W-9
2012. “Loading those payments must not change that balance.” — stage-3.md:20 · W-9
2013. “`as_of` is optional and is an RFC 3339 instant with an offset.” — stage-3.md:29 · W-10
2014. “Anything else — a naive local time, a bare date, an empty value — is 422 `validation_failed`.” — stage-3.md:29 · W-10
2015. “Without temporal query parameters the response retains the existing money fields and reports current corrected values.” — stage-3.md:30 · W-10
2016. “With it, `balance` is the caller's balance as it stood at that instant: the balance after every payment of theirs with `created_at` at or before `as_of`, and before every payment after it.” — stage-3.md:33 · W-10 · Decision D-16: as_of is inclusive (payment at exactly as_of counts); statement windows are half-open [from,to).
2017. “A payment made at exactly `as_of` counts as having happened.” — stage-3.md:34 · W-10
2018. “An `as_of` at or after the latest payment returns the current balance.” — stage-3.md:37 · W-10
2019. “An `as_of` before the earliest payment returns the opening balance — what the wallet held” — stage-3.md:38 · W-10
2020. “before anything moved.” — stage-3.md:39 · W-10
2021. “The response carries `as_of` back, exactly as given.” — stage-3.md:40 · W-10
2022. “Both `from` and `to` are optional; `from` defaults to the opening of the wallet and `to` to now.” — stage-3.md:48 · W-10
2023. “`limit` and `offset` behave exactly as in `GET /requests`.” — stage-3.md:49 · W-10
2024. “Returns the payments the caller sent or received in the half-open window `[from, to)`, **oldest first**, each with the caller's balance immediately after it:” — stage-3.md:51 · W-10
N/A: “This abbreviated example omits the revision fields and `snapshot` token described below.” — stage-3.md line 54: describes the abbreviated example
N/A: “Statement requirements:” — stage-3.md line 66: label introducing 2027-2035
2027. “Entries are ordered by `created_at` ascending, then payment `id` ascending for ties.” — stage-3.md:68 · W-10 · Ties by payment id ascending (string comparison of the opaque id); D-17: payment ids must sort in creation order within a second, or the tie order is simply by id as stated.
2028. “`opening_balance` is the balance immediately before `from`.” — stage-3.md:69 · W-10
2029. “`closing_balance` is the” — stage-3.md:69 · W-10
2030. “balance immediately before `to`.” — stage-3.md:70 · W-10
2031. “`opening_balance` plus all `delta` values in the full window must equal `closing_balance`.” — stage-3.md:71 · W-10
2032. “A sent payment has a negative `delta`; a received payment has a positive `delta`.” — stage-3.md:72 · W-10
2033. “Pagination must not change an entry's `balance_after` or the window's opening and closing” — stage-3.md:73 · W-10
2034. “balances.” — stage-3.md:74 · W-10
2035. “These values describe the full window regardless of `limit` and `offset`.” — stage-3.md:74 · W-10
2036. “Only payments sent or received by the caller appear in their statement, including when other payments are public.” — stage-3.md:76 · W-10
2037. “The activity-feed visibility rules do not apply to statements.” — stage-3.md:77 · W-10
2038. “The service must distinguish **when money took effect** from **when it learned that fact**.” — stage-3.md:81 · W-9
2039. “Every payment has a revision history.” — stage-3.md:82 · W-9
2040. “Revision 1 has `amount` as originally paid and `effective_at = recorded_at = created_at`.” — stage-3.md:82 · W-9
2041. “A seeded payment's supplied `created_at` is also its original recorded/effective time; omission uses reset time.” — stage-3.md:83 · W-9
2042. “Opening balances equal seeded ending balances minus the net effect of original seeded payments.” — stage-3.md:84 · W-9
2043. “Corrections must not change those opening balances.” — stage-3.md:85 · W-9
2044. “New accounts open at zero.” — stage-3.md:86 · W-9
N/A: “Seeded history is consistent and nonnegative.” — stage-3.md line 86: assumption about fixtures, not a product obligation
2046. “`POST /payments/{payment_id}/corrections` requires an idempotency key and the original sender.” — stage-3.md:89 · W-9
2047. “An authenticated non-sender gets 403 `forbidden`; unknown payment gets 404.” — stage-3.md:90 · W-9
N/A: “Body:” — stage-3.md line 90: label for the example body
2049. “All fields are required.” — stage-3.md:97 · W-9
2050. “Revision is a positive integer; amount is an integer 0..1000000000 (zero reverses the entire payment); reason is a string of 1..200 characters; effective time is an RFC 3339 instant not later than now.” — stage-3.md:97 · W-9
2051. “Invalid input is 422 `validation_failed`.” — stage-3.md:99 · W-9
2052. “Correction changes neither parties nor visibility.” — stage-3.md:100 · W-9
2053. “It appends an immutable revision, returning 201 with `payment_id`, `revision`, `amount`, `effective_at`, server-assigned `recorded_at`, and `reason`.” — stage-3.md:100 · W-9
2054. “Recorded times for one payment strictly increase.” — stage-3.md:102 · W-9 · recorded_at strictly increases per payment even within the same clock second: D-18 uses microsecond timestamps and bumps by 1 µs when needed.
2055. “A stale expected revision gives 409 `stale_revision`.” — stage-3.md:102 · W-9
2056. “Successful replay returns that original revision with 200 even after newer revisions.” — stage-3.md:103 · W-9
2057. “Different body with the same key is 409 `idempotency_key_reuse`.” — stage-3.md:104 · W-9
2058. “The difference from the previous amount moves between the **same two wallets** in the same atomic step.” — stage-3.md:106 · W-9
2059. “Increasing the amount debits the original sender; decreasing it debits the original receiver.” — stage-3.md:107 · W-9
2060. “A currently unaffordable debit gives 409 `insufficient_funds`.” — stage-3.md:108 · W-9
2061. “Otherwise, if any user's corrected balance is negative at any effective-time boundary, return 409 `historical_overdraft`.” — stage-3.md:108 · W-9 · Check every effective-time boundary of both wallets under the latest known revisions, including holds (2111).
2062. “Balances at a boundary include the combined effect of all movements at that instant.” — stage-3.md:110 · W-9
2063. “Either failure preserves balances, revision history, statements and idempotency state.” — stage-3.md:111 · W-9
2064. “The sum of balances must equal the seeded total in every historical view.” — stage-3.md:112 · W-9
2065. “The original payment and every original idempotent response remain unchanged.” — stage-3.md:114 · W-9
2066. “`GET /activity` continues to display the original payment; correction records are not new feed payments.” — stage-3.md:114 · W-9
2067. “`GET /payments/{payment_id}/revisions` returns `{"revisions": [...]}` in revision order, including revision 1 (`reason: ""`).” — stage-3.md:116 · W-9
2068. “Only the two parties can read it; a third party gets 404 even for a public payment.” — stage-3.md:117 · W-9
2069. “No token is 401.” — stage-3.md:118 · W-9
2070. “`GET /me` and `GET /statement` accept optional `known_at`, an RFC 3339 instant with offset.” — stage-3.md:120 · W-10
2071. “For each payment, select its latest revision recorded **at or before** `known_at`; if none was yet recorded, that payment contributes nothing.” — stage-3.md:121 · W-10
2072. “Omission means everything known when the read begins.” — stage-3.md:122 · W-10
2073. “Then apply selected revisions according to their **effective** times.” — stage-3.md:123 · W-10
2074. “`as_of` retains its inclusive meaning; a statement retains its half-open window.” — stage-3.md:123 · W-10
2075. “Both query instants may be in the future.” — stage-3.md:124 · W-10
2076. “Invalid/empty instants are 422.” — stage-3.md:125 · W-10
2077. “Echo supplied `known_at` exactly.” — stage-3.md:125 · W-10
2078. “Statement ordering is now by selected `effective_at`, then payment id.” — stage-3.md:127 · W-10
2079. “Each entry retains `payment`, `delta` and `balance_after`, and adds the selected `revision`, `effective_at` and `recorded_at`.” — stage-3.md:127 · W-10
2080. “`payment.amount` is the selected amount for this statement.” — stage-3.md:129 · W-10
2081. “Zero-amount revisions still appear as entries with zero delta.” — stage-3.md:129 · W-10
2082. “No correction is counted alongside the revision it replaces.” — stage-3.md:130 · W-10
2083. “With no corrections and no `known_at`, previous behavior is unchanged.” — stage-3.md:131 · W-10
2084. “Every first `GET /statement` response additionally returns an opaque `snapshot` token.” — stage-3.md:135 · W-10 · Snapshots are kept in memory or SQLite until reset.
2085. “It freezes the caller's selected revisions, window, balances, entries and default `to` at that read.” — stage-3.md:136 · W-10
2086. “`GET /statement?snapshot=<token>&limit=...&offset=...` pages that exact result, even after payments or corrections.” — stage-3.md:137 · W-10
2087. “Only limit and offset may accompany a snapshot; supplying `from`, `to` or `known_at` with it gives 422 `validation_failed`.” — stage-3.md:138 · W-10
2088. “Unknown token, another user's token, or a token from before reset gives 404 `not_found`.” — stage-3.md:139 · W-10
2089. “Tokens last until reset.” — stage-3.md:140 · W-10
N/A: “No storage survival across container restarts is required.” — stage-3.md line 140: permission: no restart survival required
2091. “Paging changes neither balances nor entries; the final partial page and offsets beyond the end must report `has_more` correctly.” — stage-3.md:141 · W-10
2092. “Unrecognized query parameters remain ignored under stage 1's general rule.” — stage-3.md:143 · W-10
2093. “A correction may move a payment into or out of a statement window.” — stage-3.md:145 · W-10
2094. “Existing snapshots remain unchanged during concurrent payments or corrections.” — stage-3.md:145 · W-10
2095. “Concurrent corrections using the same expected revision cannot both succeed.” — stage-3.md:146 · W-9
2096. “Stage-1 settlements retain their original receipts and privacy rules.” — stage-3.md:151 · W-9
2097. “Each member's original revision uses its shared committed_at as both effective_at and recorded_at.” — stage-3.md:151 · W-9
2098. “Single-payment corrections reject settlement members with 422 `linked_payment_immutable`.” — stage-3.md:153 · W-9
2099. “A stage-3 service must accept exports produced by the same team's stage-1 or stage-2 service.” — stage-3.md:155 · W-9 · A stage-3 import accepts stage-1 and stage-2 exports unchanged (format_version 1, D-12).
2100. “The ledger must import and account for authorizations and captures.” — stage-3.md:156 · W-9
2101. “Captures are immutable linked payments: a correction of a capture gives 422 `linked_payment_immutable`.” — stage-3.md:156 · W-9
2102. “For `GET /me?as_of=T&known_at=K`, all four money fields describe that same view: `balance = total`, `available = total - held`.” — stage-3.md:161 · W-10
2103. “A hold starts at authorization creation; nonfinal capture reduces it at capture time; final capture, void or expiry releases the remainder at that event's time.” — stage-3.md:162 · W-10
2104. “Expiry takes effect at `expires_at`.” — stage-3.md:164 · W-10
2105. “Events other than clock expiry are known at their server-assigned event time.” — stage-3.md:164 · W-10
2106. “Once creation is known, the expiry deadline is known too.” — stage-3.md:166 · W-10
2107. “For queries beyond now, an open hold expires at its deadline.” — stage-3.md:167 · W-10
2108. “Without `as_of`, use the instant the request began.” — stage-3.md:167 · W-10 · One clock reading per request (9015).
2109. “Authorizations expose `closed_at` (null while open; event time when closed).” — stage-3.md:168 · W-9
2110. “Historical `total` follows stage-3 effective/recorded-time rules.” — stage-3.md:170 · W-10
2111. “A correction is rejected with 409 `historical_overdraft` if it makes either total or available negative at any past effective/event boundary, under the latest known revisions.” — stage-3.md:170 · W-9
2112. “Current unaffordable debits still take precedence as `insufficient_funds`.” — stage-3.md:172 · W-9
2113. “Seeded open holds are assumed created at reset unless `created_at` is supplied; seeded closed holds need not reconstruct a prior lifecycle.” — stage-3.md:173 · W-9
2114. “`GET /statement` still contains money movements only: authorization, release and expiry are not payments.” — stage-3.md:175 · W-10
2115. “Captures appear exactly once with their links.” — stage-3.md:176 · W-10
2116. “Old snapshots remain unchanged after any lifecycle action or correction.” — stage-3.md:176 · W-10
