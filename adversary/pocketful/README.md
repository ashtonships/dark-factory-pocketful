# Pocketful retained adversarial checks

These scripts stay on the `adversary` branch, outside every deliverable folder. They never edit product code.
The HTTP checks reset and import service state: point them only at disposable loopback instances. Credentials
and exports stay in memory, never in reports or on the external SSD. Runtime state need not survive an abrupt
restart in stages 1–2; a persisted export imported into a fresh process is the required restart/upgrade bridge.

## Accepted revisions

Before a product attack, merge only the exact Checker-accepted revision into this worktree, preserving the
retained attack commits. Build/run isolated containers with runtime outbound access disabled. Take the shared
lock for full runs:

```sh
/Users/ashton/DarkFactory/tools/with-check-lock python3 adversary/pocketful/attack_stage1.py --base http://127.0.0.1:18081 --destination http://127.0.0.1:18082 --item 4
```

`--item 1/2/3/4` selects the obligations already implemented. Later-item cases are explicitly skipped, not
reported as passing. `--destination` must name another disposable process for independent export/import
or stage-1 → stage-2 upgrades; omission tests replacement within one process only. `--case <test_method>`
reproduces one attack. The test names and descriptions identify scope:

- W-1: negative-reset rollback, replacement/token invalidation, seeded net balances, strict JSON, chunked and
  persistent HTTP body consumption, simultaneous signup collisions, new account handle/balance.
- W-2: 50-way identical writes, conflicting identities, overspending, request terminal races, request-pay
  retries, parsed JSON equality (including boolean versus integer), user/path scoping, invalid-body replay
  precedence, failed-key reuse, lost-receipt replay, privacy, query grammar, exact large balances and Unicode.
- W-3: ordered remainders, caller omitted/included/sole participant, zero-share requests and zero payments.
- W-4: net-funded cycles, input-order validation before funds, atomic failed batch, 50-way batch replay;
  original receipts/IDs/timestamps, old tokens and hashed-password login, operator permissions, pending
  requests, failed keys and removal of destination credentials survive repeated replacement imports.

The sum/nonnegativity assertions cover every completed attack and each sequential split/import operation.
Independent `/me` calls are not falsely treated as one atomic multi-wallet read during concurrent writes.
Export contents are opaque; no private storage schema is assumed.

The accepted `57cc82e` Docker runner and exact Checker mutation runner are:

```sh
/Users/ashton/DarkFactory/tools/with-check-lock python3.12 -B adversary/pocketful/run_stage1_docker.py --report /Volumes/SSD/overflow/darkfactory/pf-s1-57cc82e-attacks.json
/Users/ashton/DarkFactory/tools/with-check-lock python3.12 -B adversary/pocketful/measure_stage1.py --report /Volumes/SSD/overflow/darkfactory/pf-s1-57cc82e-mutants-exact-summary.json
```

The first archives only the pinned stage-1 tree, limits each disposable service to 2 CPUs/2 GiB,
and puts services on an internal-only Docker bridge. Disposable fixed-destination TCP relays expose
loopback client ports because Docker Desktop does not publish ports on the internal bridge. Relays
are outside the product CPU envelope and cannot proxy to arbitrary destinations. It runs items 1–4
and three 50-write-burst/reset latency probes without weakening the API's 5/10-second budgets.

The October 3 attempts did not reach retained tests or reset measurements: a Docker network-connect
control call timed out at load 229–297, and the retry's Docker build timed out at load 471–349.
These are infrastructure/setup failures, not product findings or passing attacks. The exact full
Checker mutation command also failed its unmodified Docker-build baseline at load 232–132:
seed 1, requested 20, generated 0, valid 0, catch rate null; no survivors were scored. This is not
a 0% catch rate. The raw baseline evidence is private under `~/.cache/pf-adversary-mutants/`;
the public summary is on the SSD. Future per-copy JUnit output is kept outside the mutation
tool's disposable copy tree so timeout-only kills can be distinguished from semantic detection.
Checker attributes the control-plane stalls to host contention and the Docker VM's 3.8 GiB memory,
shared with unrelated services; that diagnosis is peer evidence, not an independently measured
normal-load result. No claim is made that reset exceeds its 10-second budget at normal load.

For a bounded source-review reproduction without using another seat's tests:

```sh
/Users/ashton/DarkFactory/tools/with-check-lock python3.12 adversary/pocketful/review_api.py /Users/ashton/DarkFactory/band-work/pf-a --revision ca640ffc9a88bc59770f6d9383b761b3453db528
```

This runner archives pinned product sources, imports them in an isolated interpreter, starts a loopback
server and runs the retained W-1/W-2 HTTP attacks. Its database stays in an internal `/tmp` directory,
not on the SSD. Four additional deterministic barriers pause an authenticated payment/request-pay/
request-cancel before reset, or pause `/me` between user and metadata reads. All four barriers pass
at `ca640ffc`: stale writes return 401 without receipts or movements; an in-flight read returns one
coherent pre-reset snapshot and subsequent reads reject the old token. This instrumentation changes
only the isolated test process, never product files.

The full in-process HTTP suite is not passing acceptance evidence: the initial host Python 3.14 run
has 11 passing cases, 2 client timeouts and 3 future-item skips; a Python 3.12 repeat has 2 passing
cases, 13 timeout errors and 1 skip. These run the client and server in the same host interpreter,
not in the specified resource-limited Docker deployment. No timeout was weakened or hidden, and no
product cause has been established. The 50-way different-key and credit-overflow probes are retained
for an isolated container reproduction; the already reported source review does not claim runtime
or latency acceptance.

## Client review reproductions

```sh
node adversary/pocketful/review_core.js /Users/ashton/DarkFactory/band-work/pf-a 77595cc
python3 adversary/pocketful/run_review.py /Users/ashton/DarkFactory/band-work/pf-a --revision 73beaa0
```

The core runner loads the exact Git object in a VM. The browser runner archives the exact Git object to a
temporary source-only SSD folder, launches its dev-only stub, and closes it after the run. It uses the existing
`/Volumes/SSD/overflow/darkfactory/b2-pw/node_modules/playwright-core` and system Chrome, with page requests
restricted to the isolated loopback origin. The stub is a UI integration double, not service acceptance evidence.
No uncommitted Builder-Two changes are used. Failure exits on these revisions are expected evidence:

- PF-A1: empty/null 201 payment receipt is classified `ok`; rendering dereferences null and fails to show uncertainty.
- PF-A2: raw amount text `15` → `15.00` produces an identical normalized body and incorrectly retains intent identity.
- PF-A3: the inclusive permitted wallet boundary `2^53` is rejected by the client's `Number.isSafeInteger` check.
- PF-A4: a legal large balance at `2^53 - 1` produces a 500px-wide page at the required 375px viewport.

The superseding fix head `93f3606` passes the independent core suite (11/11) and browser suite
(32/32, including D-11 checks at both 1280px and 375px):

```sh
node adversary/pocketful/review_core.js /Users/ashton/DarkFactory/band-work/pf-a 93f3606
python3 adversary/pocketful/run_review.py /Users/ashton/DarkFactory/band-work/pf-a --revision 93f3606 --d11
```

The raw-amount identity probe now supplies the form's raw fields as the fifth `keyFor` argument.
A body-only caller cannot distinguish `15` from `15.00` after normalization; identical JSON should
retain its replay identity. The probe separately verifies body-only replay and distinct raw identities
for pay, authorize, request, split and capture slots. Source review checks each real form supplies its
raw editable fields. Earlier heads still fail the raw-field probe. Browser navigation waits for
DOMContentLoaded plus an explicit ready element instead of treating the document load event as
application readiness. D-11 exercises the home authorization form, precision refusal, available/held
updates, private receipt/feed separation, unchanged replay, refused input preservation and continued
presence on the authorizations route. These results close PF-A1–4 as review findings; they are not
Checker acceptance or integration evidence against the actual stage-2 money service.

## W-7 real-service review

```sh
node adversary/pocketful/review_core.js /Users/ashton/DarkFactory/band-work/pf-a f220845 stage-2/ui/pocketful-core.js
NODE_PATH=/Volumes/SSD/overflow/darkfactory/b2-pw/node_modules TMPDIR=/tmp node adversary/pocketful/review_style.js /Users/ashton/DarkFactory/band-work/pf-a f220845
/Users/ashton/DarkFactory/tools/with-check-lock python3.12 -B adversary/pocketful/run_real_review.py --revision f220845 --report /Volumes/SSD/overflow/darkfactory/pf-w7-f220845-real-review-repeat.json
```

The real runner archives the pinned stage-2 Git tree, builds a disposable Docker image, runs one
2-CPU/2-GiB service, and exercises its HTTP API with Chrome at 1280 and 375 pixels. It never uses
the development stub. Browser requests are restricted to the loopback service origin. Docker uses
the default bridge to avoid the previously starved internal-network control steps; this is not a
new proof of no-outbound deployment. API credentials stay in memory and browser profiles stay on
the internal disk. Source/build files and nonsecret reports are on the SSD. A bounded preflight
requires host load below 40 and Docker version response below three seconds before runtime work.

At 9332b9f the core suite passes 11/11 and the first real-container run passes 40/42. Both failures
are PF-A6: Sign out is 40 pixels tall rather than the binding 44 pixels, at both widths. The
superseding f220845 fixes it in source, isolated CSS and real browser probes. The first f220845
run also exposes the same capture retry defect at both widths. Its unrelated early-read assertion
at 375 pixels used an obsolete loading selector; the retained runner now waits for both old and
new loading classes and explicitly for the expected balance before checking raw-amount identity.
The original report is retained, not overwritten or counted as three product findings.

The capture counterexample starts with an incoming open hold of 1000 minor units. Submit a
nonfinal 300 capture, commit it through the real API but hold its response. Change the input to
200 and submit another nonfinal capture; commit it but drop its response. Wait for uncertainty,
then deliver the older 300 success while holding the ensuing list read. Retry the unchanged 200
input. At f220845 the retry body is unchanged but its key is new, and cumulative captured money
is 700 rather than 500. The older success unconditionally calls `api.keys.forget(slotName)`
before the submission's stale-ticket guard, discarding the newer uncertain capture's identity.
This is client retry evidence, not a server idempotency failure or an acceptance verdict.

The retained presence checks also cover zero held funds, available as the largest money number,
incoming/outgoing pending request actions, another client's cancellation followed by refused pay
and refresh, successful cancellation refresh, and incoming open hold default final capture mode.
PF-A1–4, D-11 home holds, XSS text, unchanged replay and simultaneous pay submissions are retained.

## Mutation measurements

```sh
/Users/ashton/DarkFactory/tools/with-check-lock python3 adversary/pocketful/measure.py --revision 77595cc --item 5
/Users/ashton/DarkFactory/tools/with-check-lock python3 adversary/pocketful/measure.py --revision 73beaa0 --item 6
```

These invoke `tools/seeded_faults.py --product <pinned ui-core copy> --count 20 --seed <item>` with
`--build-command "node --check pocketful-core.js"`. W-5 uses `--test-command node selftest.js`; W-6 uses
`--test-command python3 <absolute-path>/browser_measure.py`, which invokes `sh run-drill.sh` while keeping
temporary browser profiles containing test sessions off the SSD. These are Builder-Two's tests, not Checker's: Checker explicitly has no
W-5/W-6 test command yet. Dev-only stub and test scripts are excluded from mutation, not from execution.
Reports live on the SSD and contain source diffs/check output only. The syntax-valid catch-rate denominator
does not establish that every survivor is a fault in a required behavior; survivor triage is mandatory.

The initial W-5 sample at `77595cc` killed 13/20 syntax-valid mutants (65%, seed 5). Seven survivors were
triaged: one demonstrates a missing crypto-fallback uniqueness check; others alter unspecified copy,
forbidden-input handling or equivalent behavior. The W-6 seed-6 attempt at `73beaa0` did not get past the
unmodified browser baseline within 120 seconds. Its score is `null`, with zero scored mutants; that is not
a 0% score or a demonstrated service failure.

At `93f3606`, W-6 seed 6 requested 20 mutations but stopped with `environment_unstable` after
10 syntax-valid candidates (9 killed, 1 survivor). A control baseline failed a 10-second navigation
waiting for the document `load` event. The official catch rate remains `null`; 9/10 is not a
publishable coverage score. Survivor 2 only changes the pluralization of an unspecified precision
error message, not a required behavior. The report is
`/Volumes/SSD/overflow/darkfactory/pf-w6-93f3606-mutants.json`.
