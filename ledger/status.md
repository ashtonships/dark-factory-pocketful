# Ledger status

Updated by Coordinator. Ledger: `ledger/pocketful.md`. Time box: final report by Sun 4 Oct 18:00 CDT.

| Stage | State | Accepted revision | Gate receipt |
|---|---|---|---|
| 1 | ACCEPTED, FROZEN: GATE GREEN #4 at 57cc82e (stage-1 tree 8f19cbfb6d7e), harness s1 146/147 (1 reset ReadTimeout at load ~290), Checker 234/234; main ef11f77 + receipt fa85767; Sat 22:10 (ledger 273/273 sentences, 251 entries + 22 waivers + 9001–9003) | — | — |
| 2 | ACCEPTED, FROZEN: GATE GREEN #6 at bc4cc1c (stage-2 tree ad34602f4b70), harness s1 147/147 + s2 35/35, Checker 329/329, load ~5; interface PASS (1017-1027); main abf639b + receipt 7c52233; Sun 01:45 | bc4cc1c | #6 |
| 3 | ACCEPTED, FROZEN: GATE GREEN #7 at 5413e25 (stage-3 tree 276ec0a8a545), harness s1 147/147 + s2 35/35 + s3 6/6, Checker 397/397; main 4bbf23d + receipt f556fba; Sun 02:13 | 5413e25 | #7 |
| 4 | OPEN from 02:30 (stage 3 accepted before the 04:00 cut): W-11 Builder (copy, refunds, import), W-12 Builder-Two (correction batches). Cut D-26: accepted by 14:00 or entry = stages 1–3 | — | — |

| Item | Seat | State | Entries | Evidence |
|---|---|---|---|---|
| W-1 | Builder | d3614cf; gating with W-2 at ca640ff | see ledger table | — |
| W-2 | Builder | ca640ff handed back 16:24; gate requested | 62–79, 131–204, 217–220 | — |
| W-3 | Builder | a3d2baf handed back; gate after W-1/W-2 | 205–216, 221–231 | — |
| W-4 | Builder | 6bbce6d handed back (complete stage 1); stage gate requested | 232–273 | — |
| W-5 | Builder-Two | handed back 77595cc; in Adversary code review | stage-2 UI | Builder-Two self-test 38/38 (not evidence) |
| W-6 | Builder-Two | 73beaa0 → f074486 (D-11) → 93f3606 (fixes PF-A1..A4, survivor-11 test); in Adversary re-review | stage-2 UI | Builder-Two drill 109/109 (not evidence) |
| W-D | Builder | 57cc82e: 30 concepts (5 screens × A/B/C × desktop/phone); with Checker for the pick | 1016–1027 | — |

## Blockers and exceptions

- Identity exception: main merge commit 370fdb5 (ledger merge) carries the repository's default git identity, not Checker's. History is not rewritten; reported by Checker.

## Checks

- Checker checks on main at 72c24d2: W-1 59, W-2 97, W-3 27, W-4 42 (items in force: checker/items.json). 247/254 stage-1 entries referenced; unreferenced: 2, 3 (process), 23, 32 (harness isolated mode), 35 (from stage 2), 219, 251 (permissions).

## Seeded faults

- W-5 at 77595cc, seed 5 (Adversary, `adversary/pocketful/measure.py --revision 77595cc --item 5`, test = Builder-Two's selftest 38 cases, as Checker had no W-5 check yet): 20 valid, 13 caught, 7 survived (65%). Report /Volumes/SSD/overflow/darkfactory/pf-w5-77595cc-mutants.json.
  - Survivor 11 (key generation radix in the getRandomValues fallback collapses distinct entropy into one key): a real blind spot in the checks; sent to Builder-Two as a selftest gap (keys from different entropy must differ). Product at 77595cc is correct.
  - Survivors 1, 2, 4, 9, 14 and 19 are equivalent or outside the input domain per Adversary's triage (reason text, copy, zero-total split, fallback entropy length, negative formatting, globalThis detection).
  - The seventh survivor's triage is pending.
- W-6 at 73beaa0, seed 6: no valid score. The unmodified baseline (Builder-Two's browser drill) took longer than 120 s, so 0 mutants were generated and the catch rate is null, not 0%. Report /Volumes/SSD/overflow/darkfactory/pf-w6-73beaa0-mutants.json. Adversary's own pinned-Chrome review: 10/14 pass; the 4 failures are PF-A1/PF-A2 at 1280 and 375. Holding: Unicode and markup notes and names render inertly, unchanged-form replay, a double submit debits once, no horizontal scroll, safe manual retry after an empty receipt.
- W-6 at 93f3606, seed 6: environment_unstable after 10 valid mutants, 9 killed and 1 survivor; the control baseline later failed, so the catch rate is null (not 90%). Report /Volumes/SSD/overflow/darkfactory/pf-w6-93f3606-mutants.json. The survivor changes the pluralisation of an error message, which is unspecified wording. Adversary's re-review of 93f3606: core 11/11, browser 32/32; PF-A1..A4 fixed (attack scripts at 3e4ffd3).

- Gate: GATE RED #1 stage 1 item rev ca640ffc9a88 (receipt line 1, main d5f64ac). Overfit high: core.py:216 '-1', server.py:218 '19'. Checker pre-run 157/158 (keep-alive drop at 5 s socket timeout; 50 logins slowest 13.3 s at host load about 270). Host load comes from other apps on this Mac (Codex/Claude renderers, Docker VM with unrelated CRM containers), not from our jobs.
- Gate: GATE RED #2 stage 1 stage rev 6bbce6de286c (receipt line 2), with the same two overfit tokens. Checker's pre-run of all W-1..W-4 checks on 6bbce6d (checks 04e77d0, load 286 to 368): 224 passed, 3 failed. Two are the keep-alive idle close and one is the 50-login latency (13.9 s). Every W-3 and W-4 check passed, and Builder's W-4 readings were accepted. Rework is with Builder.
- Gate: GATE RED #3 stage 1 stage rev 1f882fffb4ea tree 7130a693ac14 (receipt line 3, main 239bc21): overfit 0 high, harness s1 147/147, checker 233/234. The only failure is 50 concurrent logins, slowest 6.09 s against 5 s, at host load 143 to 338 (entries 30, 31, 116, 129). Decision (Sat 19:29): Builder cuts login CPU further, because a rerun waiting for low load is unbounded while other apps keep the load near 280. W-D design started at the same time, since it touches only design/ and the gate shows the data model green (harness 147/147).
- W-1 login rework 86a0196 (5000 iterations, tagged), with W-D 57cc82e on top; stage-1 tree 8f19cbfb6d7e; stage gate requested at 57cc82e. W-8 assigned at the same time, based on that candidate tree.
- 21:30: Checker's wait for low load expired without a rerun (load 140 to 330 all evening). Told Checker to gate 57cc82e (the login-cost rework) now and accept the result as it falls.
- W-8 handed back at 80c511a (chain cd4efc0 copy = stage-1 tree 8f19cbfb6d7e, f60ba6f server, 80c511a typed fields). 80c511a made malformed settlement batches 400, contradicting §11/D-9 (422); Builder asked to git-revert it. PF-A5 (9018) fixed in f60ba6f.
- W-7 part 1 (Builder-Two): merge builder, move ui-core pages into stage-2/ui/, drill against the real stage-2 container. Part 2, the restyle, follows the design pick.
- Time check: stage 1 still not accepted at 21:30 because of host load. Cut rule: stage 3 not accepted by Sun 04:00 → no stage 4; not accepted by 12:00 → entry is stages 1-2.
- Stage 1 accepted 22:10. Adversary dispatched to attack 57cc82e: retained suite, a reset-latency probe after a 50-way burst, seeded faults (seed 1). W-7 part 2 (restyle to the pick) sent to Builder-Two.
- W-8 124477e (revert of 80c511a; stage-2 tree equals f60ba6f). D-19 event-time commit requested from Builder.
- W-7 handed back at 9332b9f on builder-two (merges builder 124477e as e72d825; only stage-2/ui/ changed). Builder-Two evidence: drill 161/161 against the real container through a fault proxy; upgrade drill 26/26; selftest 43/43; screenshots /Volumes/SSD/overflow/darkfactory/w7-shots/. Sent to Adversary for code review and to Checker for a pre-gate dry run and interface review. Gate commit = builder-two after merging Builder's D-19 commit.
- Stage-3 checks on main 2bba408 (W-9 36, W-10 30), not in force.
- 01:00: stage-2 gate requested at 78cfc4e (builder-two merge of W-8 c7b6c05 onto W-7 7223619; stage-1 tree 8f19cbfb6d7e, stage-2 tree 61e7f3da80ff). PF-A6 closed; PF-A7 fixed, with independent confirmation pending.
- GATE RED #5 stage 2 at 78cfc4e (receipt line 5, main 0a210dd): one high overfit token, '300' (the HTTP 2xx bound) at ui/pocketful-core.js:280. Checker's own run of 78cfc4e: 321/321 at load about 9; final interface judgement on 1017-1027 PASS (I-1 not visible in fixtures; cosmetic). Builder-Two is fixing the literal. Coordinator runs the overfit scan before the regate, because builders must not read the shipped tests.
- Stage 2 accepted at 01:45 (GATE GREEN #6). Stage 3 dispatched; Adversary queue: stage-1 attack, stage-2 attack, seeded faults (seed 2), stage-3 pre-mortem. Stage 4 cut by rule.
- 01:50: W-9 handed back at 53a3a1e (corrections, revisions, closed_at, imports; Builder evidence: a 50-way expected-revision race gave exactly one 201). W-9a was 77ddcf9 and the copy 6ffaf19 (stage-3 copy = stage-2 tree ad34602f4b70). The route hook was reassigned from Builder to Builder-Two to save a round trip (recorded exception to the file-ownership split). The scrypt hardening (9019) is still open with Builder. W-10 statement.py is at d08f22c on builder-two.
- 02:30: Checker's stage-3 dry run on 63e1fef (checks 7cb0e7c, W-9/W-10 in force at a48ed06): 387/388, the one failure a bug in Checker's own check (fixed); W-9+W-10 65/65 ×3; harness s1 147/147, s2 35/35, s3 6/6 (claimed stage 3, no overshoot). The overfit scan would be RED with two tokens: RUN.md '19' (Builder) and statement.py '-1' (Builder-Two); both sent for rewording. w10-dev/ to be removed from builder-two. Pending: Builder's scrypt/login commit.
- 02:12: stage-3 candidate 5413e25 (builder-two: merge of Builder 8e1fc80, scrypt reverted, RUN.md reworded, onto W-10 802bbe3). Builder-Two evidence: stage-1/2 unchanged since receipt 7c52233; route hook and Dockerfile COPY intact; b2-w10-accept 79/79 (not evidence). Coordinator overfit scan of stage-3 at 5413e25: 377 candidates, 177 findings, 0 high. Stage-3 gate requested from Checker; Adversary asked to review the W-10 delta 53a3a1e..5413e25 before the verdict.
- 02:20: background security review of 5413e25 raised 2 issues, both triaged as no action. (1) missing-authentication in stage-3/server.py: GET /statement calls authenticate() and snapshot lookups are owner- and generation-checked (statement.py:92); the unauthenticated routes are /_test/reset, /_test/export and /_test/import, which the spec requires (stage-1.md:254, :544). (2) weak-kdf in stage-3/core.py: the accepted risk 9019 (scrypt reverted for latency margin, bec1be7).
- 02:30: stage 3 accepted (GATE GREEN #7, Checker 397/397). Adversary review of the W-10 delta still pending; any valid finding is fixed in stage-4/ and stage-3/ alike via a new ledger entry. Stage 4 opened: entries 3001–3045 (44 + 1 waiver), D-21..D-26, W-11/W-12 dispatched; Checker designs W-11/W-12 checks in parallel.
- W-11 copy step: builder dc76f88 (ff of main 757013c, then copy-only commit). Coordinator verified: stage-3 and stage-4 trees both 276ec0a; stage-1..3 unchanged since f556fba. Builder-Two told to merge dc76f88 into builder-two before W-12 edits.
- D-23 corrected: historical_overdraft is 409, not 422 (stage-3.md:110 and :171 define it as 409; stage-4.md:54 says "the existing codes apply"). Raised by Builder-Two; b5e24ab already returns 409. Open W-12 dependency: Builder adds a nullable correction_batch_id column to payment_revisions (core.py schema, export/import, corrections.py INSERT).
