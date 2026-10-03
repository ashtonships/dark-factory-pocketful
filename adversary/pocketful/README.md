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
