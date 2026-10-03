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

## Work items (stage 1)

| Item | Seat | Entries | Scope |
|---|---|---|---|
| W-1 | Builder | 2–3, 9–12, 14–15, 18, 22–25, 27–32, 34–48, 50–55, 57–61, 80–89, 91–92, 95–103, 105–117, 119–130, 9001–9003 | Runtime contract and data model: container, RUN.md, health, reset/seed, conventions, errors, auth, `GET /me`, the SQLite schema for every stage-1 record |
| W-2 | Builder | 62–79, 131–204, 217–220 | Payments, requests (create, pay, decline, cancel, list), the activity feed, idempotency on every write path |
| W-3 | Builder | 205–216, 221–231 | Splits and the equal-split rule |
| W-4 | Builder | 232–273 | Export/import and atomic net settlements |
| W-5 | Builder-Two | stage-2 UI entries (added at stage 2) | Client core for the screens, outside stage folders until stage 2 opens |
| W-D | Builder | stage-2 product and visual direction | Three concepts per screen, picked by Checker; starts when W-1 is accepted |

## Practice-run lessons (made entries so the same faults cannot recur)

9001. “Unparseable body, or a field of the wrong JSON type” — §5 · W-1 · Every rejected request (400/401/404/405/422) must read and discard its whole body so the next request on a keep-alive connection is parsed correctly.
9002. “Unparseable body, or a field of the wrong JSON type” — §5 · W-1 · A body sent with `Transfer-Encoding: chunked` must be decoded and read in full, not treated as empty.
9003. “Unparseable body, or a field of the wrong JSON type” — §5 · W-1 · `NaN`, `Infinity`, `-Infinity`, invalid UTF-8 and UTF-16/32 bodies are 400 `malformed_request`; duplicate keys follow the last value.

## Findings (added as they arrive)

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
