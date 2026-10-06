# FACTORY.md

An evidence-gated software factory: five seats in one Band Desktop room turn a written specification into a
requirements ledger, build against it, check it independently and attack it. No seat can say "done". Only a
program can: `tools/gate.py` judges an exact commit and writes a hash-chained receipt.

This file covers how to stand the factory up, why it is shaped this way and what that costs. It also reports what the
submitted Pocketful run measured, including what went wrong. Every number names the command that produced it, and
the raw outputs are in [`measurements/`](measurements/).

## Result of the submitted run (Pocketful)

| | |
|---|---|
| Stages reached | **1, 2 and 3**, each accepted by a green gate receipt and frozen. Stage 4 was built but never accepted before the band's own cut-off, so it is not submitted (see *What failed*) |
| Event harness, fresh clone of `main`, isolated mode | stage-1/ claims 1, stage-2/ claims 2, stage-3/ claims 3. Each folder passes every earlier suite (147/147, 35/35, 6/6) and fails the next stage's suite (stage-1/ on suite 2: 0/35; stage-2/ on suite 3: 2/6; stage-3/ on suite 4: 0/5), so none overshoots (`measurements/harness-isolated/`) |
| Gate receipts | 9 (4 green, 5 red); `python3 tools/gate.py verify` → "receipts: 9 verified (4 green, 5 red)" and "verify: ok" over every first-parent commit on `main` |
| Human input after the dispatch | **0 messages**. The dispatch was the only human message in the room (`tools/room_audit.py`). The operator did take infrastructure actions outside the room (seat restarts, a model pin); every one is listed with its time in *Operator actions during the run* |
| Spec coverage | Every one of stages 1–3's 611 specification sentences is in the ledger, and 559 of their 572 obligations (98%) have a check the Checker wrote from the specification, against 188 shipped checks (`measurements/spec_coverage.md`) |
| Builder tool calls touching the shipped tests | **0** (`tools/room_audit.py`, over 1,224 builder tool calls) |
| Wall-clock | Dispatch Sat 3 Oct 16:49:58 UTC. The Coordinator's first action came at about 19:27 UTC, because the seats could not start until then (see *What failed*). Stage 1 went green at 02:59 UTC, stage 2 at 06:09 and stage 3 at 07:18. The last room message was at 08:16 UTC. The band then stalled (see *What failed*), so **no final report was posted** |
| Model spend | 1.46 M output tokens and 3.37 M uncached input tokens (the five seats plus 14 automated commit-hook review sessions; table below) |

## The idea in one paragraph

Agent-built software rarely fails the tests that shipped with it. It fails the requirements nobody tested. So the
centre of this factory is not the builder but the **requirements ledger**. Before anything is built, the Coordinator
writes every obligation in the specification as a numbered entry that quotes its source sentence. Every work item
carries its entries. The Checker writes its own tests from those sentences, never from the tests that happened to
ship. The Adversary attacks what was accepted, and every finding becomes a ledger entry that later work must also
meet. Acceptance is not a seat's opinion. The Checker runs the gate, and a stage folder is merged onto `main` only after a
green receipt for that exact stage tree. Checking is vendor-crossed: code written by one model family is examined by the
other.

## Seats

| Seat | Harness | Model | Owns | Never does |
|---|---|---|---|---|
| Coordinator | Claude Code | claude-opus-5-5 | the ledger and its status, the plan, every handoff, decisions on ambiguity, the final report | write product code or tests |
| Builder | Codex | gpt-6.1-sol | its work items (server, data, money logic in this run) on its own branch | read the shipped tests, accept its own work |
| Builder-Two | Claude Code | claude-opus-5-5 | its work items (a different scope: the UI and client recovery logic in this run) on its own branch | read the shipped tests, accept its own work |
| Checker | Claude Code | claude-opus-5-5 | checks written from the specification; the gate run; interface review; the verdict; merging to `main` | edit product code, weaken a check |
| Adversary | Codex | gpt-6.1-sol | the pre-mortem; attacks on accepted work; code review of Builder-Two's work; planted-fault measurements | edit product code, give verdicts |

By design, product code is examined by the other model family: the Checker (Claude) judges Builder's Codex work, and
the Adversary (Codex) reviews Builder-Two's Claude work before the Checker's verdict. One exception in this run: stage
3 was accepted while the Adversary's review of the W-10 delta was still pending (the Adversary was being interrupted by
provider safety refusals; see *What failed*). Both families build, so this is
not one model checking itself. **Builders build blind**: they get the specification and never the shipped tests, and
only the Checker runs the event harness. Each seat works on its own branch in its own worktree. The Checker merges
accepted branches into `main` without rewriting history, so every commit traces to a seat, a work item and a room
message.

The mandates are in `mandates/<seat>.md`, one per seat. Each starts with its `Harness:` and `Model:` lines, says how
the seat works, and names nothing about any particular problem. An earlier version of the same mandates ran the event's
toy practice track first; that run is not submitted and its evidence is not in this repository.

## The loop, per stage

1. **Ledger.** The Coordinator reads the stage's specification and commits `ledger/<task>.md`, with one numbered
   entry per obligation, each quoting its sentence. It resolves ambiguities in writing (`D-n` decisions), choosing
   the reading that keeps every stated invariant. Nobody asks the human.
2. **Plan.** It groups entries into work items in dependency order and splits them between the two builders by
   layer, so neither builder carries most of the code.
3. **Design first, for screens.** The Codex builder draws three concepts per screen at desktop and phone width. The
   Checker picks one per screen and records why, and the screens are built to the pick.
4. **Build.** The handoff carries the work item, its entries, the specification text, the paths and the acceptance
   commands. It never says "see above".
5. **Independent check.** In parallel, the Checker writes tests for the same entries from the specification,
   before reading the builder's code.
6. **Review.** The Adversary code-reviews Claude-built work. The Checker reads every diff for code that recognises
   tests instead of implementing rules.
7. **Gate.** `tools/gate.py run --stage N --rev <commit>` exports that exact commit and runs a fixed sequence,
   stopping at the first red step: the mandate and credential scan, the test-fitting scan (shipped-test literals
   reused in product code), the event harness in isolated mode for every suite up to N (no outbound network, the published CPU
   and memory limits), and the Checker's own checks. It appends a receipt to `receipts/chain.jsonl` with both
   revisions, the stage folder's git tree hash, every count and timing, and the sha256 of the previous receipt.
8. **Verdict.** On green, the Checker merges and freezes the stage. On red, the failing entries and a reproduction
   go back to the builder through the Coordinator, and the stage is gated again.
9. **Attack.** The Adversary attacks accepted work. Findings become ledger entries (`9000+`) and work items, and a
   change to a frozen stage must pass the whole gate again.

## How the factory catches bad work, as measured in this run

| Catch | Stage | Written by | Caught by | What happened |
|---|---|---|---|---|
| Duplicate token inside one export imported with 204 instead of 422 | 3 (re-gate) | Builder-Two (Claude) | Checker's checks, via the gate | GATE RED #8 at 2132717 (Checker 410/411, shipped suites all green). Builder-Two fixed it in a3f0daa (stage 3) and 06d4eea (stage 4, statement.py only in each); receipt #9 tested 06d4eea, and GATE GREEN #9 followed **14 min 44 s** later. The shipped tests passed the broken build; only the Checker's spec-derived check saw it. **The fix is gated but not on `main`:** the Checker held the merge for the stage-4 gate, and the band stalled before it. `main`'s stage-3 is still receipt #7's tree, which accepts a repeated token within one export |
| A settlement change that contradicted an accepted decision (malformed batches 400 instead of 422, D-9) | 2 | Builder (Codex) | Coordinator, before the gate | 80c511a was reverted at the Coordinator's request (124477e). Bad work never reached the gate |
| Four interface defects in the stage-2 screens (PF-A1 to PF-A4), then PF-A6 and PF-A7 | 2 | Builder-Two (Claude) | Adversary (Codex) code review | Each became a ledger entry and was fixed (93f3606, f220845, 7223619). PF-A1 to PF-A6 were re-reviewed by the Adversary, whose pinned-browser review went from 10/14 to 32/32. PF-A7 was fixed in 7223619, and Builder-Two reported its own tests plus 46/46 Adversary-authored checks passing. The Coordinator asked the Adversary to confirm with its own run (05:37 UTC), but its next turn was ended by the safety filter, so a separate Adversary retest is not established |
| 50 concurrent logins slowest at 6.09 s against a 5 s requirement | 1 | Builder | Checker's checks, via the gate | GATE RED #3 rejected 1f882ff, which had already bounded login cost. Builder then cut new hashes to 5,000 iterations (86a0196), and GATE GREEN #4 followed |
| Shipped-test literals in product code | 1, 2, 4 | both builders | the test-fitting scan, via the gate | GATE RED #1, #2 and #5, and the W-11 overfit reject. The ones we traced ('-1' as a list index, '300' as the HTTP success bound) were false positives (see *What failed*); the builders reworded the code rather than add an allow-list entry |
| Nine ledger entries no check covered | 3 | (coverage gap) | Checker's final review, after acceptance | 31249e3 added six checks covering entries 2006, 2007, 2063, 2064, 2104–2106, 2113 and 2116. All pass on accepted stage 3; they ran in the later 411-check re-gate, not in receipt #7 |
| Snapshots lost across a stage-3 export and stage-4 import | 3 | (spec gap found while building 4) | Checker, independently of the Coordinator | Decision D-27 / entry 3046 reopened frozen stage 3 through the gate (RED #8, then GREEN #9). Because stage 4 was never accepted, `main` keeps the receipt-#7 tree of stage 3 |

The heuristic counts from `tools/factory_numbers.py` over the room log are 394 seat-to-seat handoffs and 53 messages
that say "reject", 40 of them followed by a commit on the same work item. These are text-matching heuristics. The
table above was checked against the room by hand.

### Did the checks prove more than the shipped tests?

| | Stage 1 | Stage 2 | Stage 3 |
|---|---|---|---|
| Shipped checks at the green receipt (isolated, cumulative) | 146/147 (1 reset timeout under host load) | 182/182 | 188/188 |
| Checker's own checks at the green receipt | 234/234 | 329/329 | 397/397 (411/411 at the later re-gate) |
| Checker checks per shipped check, cumulative | 1.6× | 1.8× | 2.1× |

On a fresh clone of the public repository on 5 Oct (stage folders unchanged since 02600fb), on a quiet machine, the shipped suites pass 147/147, 182/182 and 188/188 (`harness run --all --mode isolated`).

**Spec coverage beyond the shipped checks** (`measurements/spec_coverage.md`): stages 1–3 have 611 specification sentences. All of them are in the ledger, 39 as waivers for sentences with no behaviour. Of the 572 obligations, 559 (98%) have at least one check the Checker wrote from the specification: 246 of 252 for stage 1, 204 of 211 for stage 2 and 109 of 109 for stage 3.

**Reproducing the Checker's numbers.** Rerun the Checker's suite at each receipt's `checks_rev`, not at `main`'s head. At the head, `checker/items.json` also binds W-13 (the D-27 snapshot amendment) to stage 3. That amendment is on the builder branches only, so the head suite would fail `main`'s stage-3 on those checks. Receipt #7's `checks_rev` is a48ed06, and there the suite is 397/397 on `main`'s stage-3.

Source: `receipts/chain.jsonl` lines 4, 6 and 7 (`python3 tools/gate.py show`). The stage-3 suite that shipped has 6
checks. The Checker's suite grew by 68 checks between receipts #6 and #7, then by 14 for receipt #9: 6 from its final review and 8 for W-13.

**Planted faults (mutation testing)** were measured only in part. On W-5 the Adversary's run killed 13 of 20 valid
mutants (65%) using Builder-Two's own 38-case self-test, because the Checker had no W-5 check yet, so it measures
the builder's self-test, not the Checker's suite. One survivor exposed a real blind spot in the self-test (key generation from different entropy). It
was sent back as a test gap; the product was correct. Two runs on W-6 gave no valid score because the browser
baseline was too slow or unstable on the loaded machine. We report them as null, not as a rate. The practice run's mutation results are not evidenced in this repository.

## Why this shape, and what it costs

- **Ledger first** costs time before the first line of code. Stage 1's ledger covered 273 of 273 sentences (252
  obligations and 21 waivers by `tools/spec_coverage.py` after the run; the Coordinator counted 251 and 22 during it) and took the Coordinator about 20 minutes. In return the factory covers what the
  shipped checks never exercise, which is where the hidden test set is decided.
- **Tests from the specification, by a different seat and model family,** catch the builder's blind spots instead
  of repeating them. The cost is reading the specification twice. In this run the Checker produced 22% of the output
  tokens.
- **Acceptance by program, not by message.** Each receipt holds the sha256 of the one before it, so editing, removing or reordering a receipt breaks the chain unless every later receipt is rewritten too. The chain is not signed. The gate run itself is rerunnable with the event kit. And `gate.py verify`
  re-checks from a clone that the chain is intact and that every stage-tree change in `main`'s first-parent history
  matches a recorded green receipt (it does not rerun the tests; the receipts record those runs). The cost is that every acceptance runs the full harness
  and the Checker's suite: about 5 minutes a gate run at normal load, and 18–36 minutes on the overloaded machine, and that a false positive in the gate costs a rewrite (see below).
- **An adversary that attacks only accepted work** keeps rejection meaningful: findings are grounded in requirements
  and reproducible. The cost is a seat that writes no product code.
- **Two builders on separate layers** spread the work: of all lines added in `main`'s history (code, tests, ledgers and
  copied stage folders alike), Builder accounted for 28.8% and Builder-Two 28.0% (at the run's last commit, 02600fb: `measurements/factory_numbers-run-end.md`). The cost is integration, which the Checker's merge-and-recheck absorbs.
- **Blind building** costs the builders the convenience of green tests, and removes the most common way an entry is
  disqualified: code written to the tests.

## Cost and time (measured)

Tokens per seat from the dispatch to the last activity, read from the seats' own Claude Code and Codex session logs
(`tools/seat_usage.py --since 2026-10-03T16:49:58Z --until 2026-10-04T08:20:00Z`, output in
`measurements/seat_usage.md`):

| Seat | Harness | Model (turns) | Uncached input | Cache write | Cached input | Output |
|---|---|---|---:|---:|---:|---:|
| Coordinator | Claude Code | claude-opus-5-5 (366) | 736 | 860,422 | 70,238,227 | 236,326 |
| Builder | Codex | gpt-6.1-sol (38), gpt-6-sol (2) | 1,972,532 | n/a | 65,750,272 | 350,188 |
| Builder-Two | Claude Code | claude-opus-5-5 (364) | 730 | 1,134,229 | 81,029,978 | 382,602 |
| Checker | Claude Code | claude-opus-5-5 (352) | 720 | 1,347,259 | 84,933,488 | 319,648 |
| Adversary | Codex | gpt-6.1-sol (29), gpt-6-sol (1) | 1,397,124 | n/a | 35,424,000 | 157,155 |
| Automated security reviews of the Claude seats' commits: 14 sessions from the operator's machine-wide Claude Code commit hook (prompt "Review this change for security vulnerabilities", identified by the operator from each session's first prompt), started by the seats' own commits in their worktrees. Set up before the run; no person involved | Claude Code | claude-opus-5-5 (42) | 84 | 376,688 | 919,708 | 13,633 |
| **Total** | | | 3,371,926 | 3,718,598 | 338,295,673 | 1,459,552 |

- **Wrong-model turns, disclosed.** Three Codex turns ran on `gpt-6-sol` instead of the mandated `gpt-6.1-sol`:
  Builder 19:57–20:02 UTC (2,620 output tokens) and 20:06–20:37 UTC (44,505), and Adversary at 20:03 UTC (178).
  That is 47,303 output tokens, 3.2% of the run. Band sends a model with every turn, and the seats' older Band sessions still held the old default model (operator diagnosis from the session settings, not recorded in this repository). The operator then pinned every Codex session to `gpt-6.1-sol` (see *Operator actions during the run*). From 20:38 UTC every Codex turn ran on it.
- **Proving against building:** the Checker and Adversary produced 476,803 output tokens and the two builders 732,790,
  a ratio of 0.65.
- The totals above cover everything in the window. That includes stage-4 candidate work, which is not submitted, and the 14 commit-hook review sessions, not only the three delivered stages.
- Operator-reported, not verified by an invoice: all seats ran on flat-rate Claude and ChatGPT subscription plans with no metered API keys, so the run added no per-token bill. The token counts themselves are measured, not estimated. Any dollar figure for this run seen elsewhere (for example an API-equivalent estimate) is a catalogue-price estimate from a different dataset, not a cost we paid.
- **Time per stage:** stage 1 took 7 h 33 min from the Coordinator's first action to its green receipt. That
  includes three red receipts on a machine at load 140–520 (other workloads ran on it). Stage 2 took 3 h 10 min more
  and stage 3 another 1 h 9 min.

Commits on `main` by author (`tools/factory_numbers.py`, non-merge): Coordinator 42, Checker 27, Builder 17,
Builder-Two 14, the shared default identity "Dark Factory band" 20, and the one setup commit. Added-line share:
Builder 28.8%, Builder-Two 28.0%, Checker 20.7%, Coordinator 3.4%. These are measured at the run's last commit, 02600fb (`measurements/factory_numbers-run-end.md`). `measurements/factory_numbers.md` is the same tool at a later commit, so it also counts the operator's documentation commits. Its "Refusals: 0" counts refusals by the git freeze hook, which was switched off. It does not count the vendor's safety refusals, which are below.

## Operator actions during the run

Nothing here was a message to a seat, an approval, a hint or a rerun. Each was an infrastructure action outside the room. The participant guide does not say whether such actions are allowed during a submitted run, so we list them here for the judges to weigh, and we don't claim an exemption. Times are UTC on 3 Oct.

| Time | Action | Why |
|---|---|---|
| 16:49:58 | Dispatch posted to @Coordinator | the only human message in the room |
| 17:02–19:15 | Retried waking the seats. Fixed the Band service's PATH and shell start-up, then restarted the Band service | the seats could not start a room session: the runtime command did not resolve on a machine at load 350–520 |
| 19:27 | The Coordinator woke on the buffered dispatch by itself | — |
| about 19:30–20:02 | *Restart agent* in Band Desktop for Builder, Builder-Two, Checker and Adversary, one at a time; they were ready at 19:57, 19:58, 20:00 and 20:02 | the service restart had left them in an unfinished cleanup state |
| 20:03–20:38 | Pinned the two Codex seats' sessions to `gpt-6.1-sol` (`band runtime settings`) and restarted those sessions. Five turn attempts failed in the room with "model is not supported" before the pin held (`measurements/model-pin-replay.md`) | three turns had run on `gpt-6-sol`, the old default held by older Band sessions |
| after 20:38 | none. Later seat restarts in the room log are Band waking a seat for a message (TEAMWORK.md, glossary) | — |

After the stall at 08:16 UTC on 4 Oct, the operator neither restarted, nudged nor reran anything. The run ended with the band's own cut (D-26, 19:00 UTC) and no final report. The room was downloaded on 5 Oct. The practice-run lessons that the setup commit's FACTORY.md carried (keep-alive, chunked bodies, NaN), and that the Coordinator turned into entries 9001–9003, were written before the dispatch, as was the dispatch's own fixed stack and builder split. `DISPATCH.md` is that dispatch in generic form.

## What failed, and what we changed or would change

- **The seats could not start for 2 h 37 min after the dispatch.** By the operator's diagnosis (from the Band daemon's logs, not
  kept in this repository), Band's background service ran with a minimal PATH and its terminal-PATH probe timed out on
  a machine at load 350–520, so the Claude seats could not start a room session. The dispatch waited, buffered, until the Coordinator woke at about 19:27 UTC. We fixed the service's PATH
  and restarted the seats with Band Desktop's *Restart agent*. That was infrastructure only: no message was posted
  to the room. **Rule now:** check the runtime commands with *Test runtime* and `band doctor` immediately before a
  dispatch, not the day before.
- **A vendor safety filter kept stopping the red-team seat, and nothing reacted.** From 04:23 to 08:11 UTC the
  Adversary's Codex turns ended 15 times with a provider safety refusal ("flagged for possible cybersecurity risk"),
  most likely set off by its own attack scripts. The last one, at 08:11 UTC, held the last step of stage 4: the
  Adversary's review of W-12. The seats wake only on messages, and no seat or message acted on the refusals. The room's
  last message is at 08:16 UTC, nothing happened before the band's own cut-off (D-26, 19:00 UTC), and stage 4 was
  never accepted. **What the factory lacks is a liveness check** on any seat holding the critical path. Fix: the
  Coordinator re-pings a seat that has been silent past a time box on a critical-path item, and reassigns the review
  (the Checker can review in the Adversary's place, with the vendor crossing waived and recorded). Attack scripts
  should also be phrased as tests of the team's own service so that a filter does not read them as intrusion.
- **The test-fitting scan raised false positives.** `overfit_scan.py` flagged `-1` in `digits[-1]` (a list index)
  and `300` in `status < 300` (the HTTP success range) as literals copied from the shipped tests. Those two tokens caused or
  shared GATE RED #1, #2 and #5 and the W-11 reject. Each cost a rewrite (`<= 299`; `max()` instead of `[-1]`) rather than a code
  change. The builders reworded instead of adding allow-list entries, which kept the allow list empty but cost
  minutes. Fix (not applied to this repository after the run): skip subscript indexes and HTTP status-class bounds.
- **Stage 4 was first cut too early, then reopened.** The dispatch rule was "stage 3 not accepted by Sun 04:00 → no
  stage 4" (04:00 CDT, 09:00 UTC). The Coordinator applied it as a forecast at 06:10 UTC, and stage 3 was then accepted 1 h 42 min before
  the cut time. The band noticed and reopened stage 4 itself at 07:22 UTC, under a new cut (D-26, 19:00 UTC). Lesson:
  a cut rule must be applied at its time, not forecast.
- **Security traded for latency.** Builder tried scrypt password hashing (be618df) and reverted it 3 minutes later
  (8e1fc80) to keep the login-latency margin on the loaded machine. The Coordinator recorded this as accepted risk
  9019. Logins use PBKDF2 at 5,000 iterations. That is weaker than we would ship to production, and we say so here.
- **The host was overloaded.** Gate runs met load averages of 140–520 on 14 cores, from unrelated jobs on the same
  Mac. This produced RED #3 (login latency) and the one reset timeout in receipt #4. Fix: run the factory on a
  machine that does nothing else.
- **Identity slips.** Twenty non-merge commits carry the repository's default identity "Dark Factory band" instead
  of a seat's. They are mostly Coordinator ledger commits made from the shared `main` checkout. One of them (fc2a0e2,
  07:12 UTC, on the Coordinator's branch) swept stage-3 files that were already staged in that checkout in with a ledger line (its tool call ran
  only `git add ledger/status.md`). It reached `main` only through a later ledger merge (757013c, 07:21 UTC), after stage 3's green receipt
  #7 and its accepting merge (4bbf23d, 07:18 UTC), and `main`'s stage-3 tree stayed the one #7 accepted. The Coordinator
  noticed and recorded it (ledger status, *Provenance*), and from 9a7c654 onward it commits only `ledger/` paths, as
  itself. History is never rewritten. All 47 product commits appear by sha in the room, and 19 of the 20 "Dark Factory band" commits match a Coordinator tool call (TEAMWORK.md).
- **No final report.** The Coordinator's mandate requires one, with the spec-coverage table and the planted-fault rate. The band stalled first, so neither was produced in the run. `measurements/spec_coverage.md` gives the coverage now, measured after the run. **Fix:** the timekeeper below, and a rule that the Coordinator posts an interim report at each stage acceptance.
- **Independence slipped once.** At 08:08 UTC on 4 Oct, on the Coordinator's instruction and with the Checker's command, Builder ran one W-11 check from `checker/`. The Coordinator stopped it in its next message (08:10:46: "from now on don't run Checker's checker/ tests"). At 07:54 Builder-Two had been given the Checker's W-13 tests as its acceptance and was told within the same minute not to use them, and it did not. Builders never read the shipped tests (`tools/room_audit.py`: 0 of 1,224 tool calls). **Fix:** the Checker's `checker/` folder becomes unreadable from the builders' worktrees.
- **The gate's bar on the shipped suites is the event's own claim, not 100%.** At stage level the gate needs the harness to report that the folder claims its stage, with no earlier suite regressing (`tools/gate.py`, `harness` step). Receipt #4 accepted stage 1 at 146/147, with one reset timeout under host load. On a quiet machine the same tree passes 147/147. **Fix:** require every shipped check to pass and rerun a flake once.
- **The machine's own tooling reviewed seats' commits.** The operator's machine-wide Claude Code commit hook ran an automated security review on the Claude seats' commits (14 sessions, 13,633 output tokens; table above). It is environment tooling, set up before the run. **Fix:** run the factory under a clean user profile with no personal hooks.
- **The freeze hook did not ship.** `tools/hooks/reference-transaction` would refuse any update of `main` that
  changes a stage folder without a green receipt. A replay proved that it refuses. It was never proven to accept a
  real green before the dispatch, so under our own cut rule it is switched off. `gate.py verify` reports such a merge
  after the fact instead.

## After the run: the two failures, fixed

Both tools below were written after the submitted run, on 5 Oct, and were not part of it. They are read-only, and
each is replayed on this run's own `room.json` and session logs (`measurements/liveness-replay.md`,
`measurements/model-pin-replay.md`; tests in `tools/tests/`).

**A silent seat stalled the band (stage 4 was never accepted).** `tools/liveness.py` reads the room (`room.json`, or
saved `band room messages --json` pages) and reports a stall when the whole room has been quiet for 30 minutes while
a seat still owes a reply. A seat owes a reply from the first text that addresses it until it next posts a text. A
seat waiting while others work is not a stall. Replayed on this run, it reports three stalls, all real. The first is
the 2 h 37 min start-up stall, reported 31 minutes after the dispatch. The second is a 30-minute quiet room at 00:18
UTC Sunday. The third is the fatal one: the room went quiet at 08:16 UTC with the Adversary holding W-12's review,
and it is reported at 08:46 UTC, 10 h 14 min before the band's own cut (D-26, 19:00 UTC). Telling the band is the
part not built yet. In the next version a non-model Band seat (a "timekeeper") runs it every minute and posts the
stall to @Coordinator, so recovery stays inside the band and adds no human input. Creating that seat's Band identity
is an owner step, so it was not done for this entry.

**Seats ran on the wrong model, and nobody in the factory saw it.** `tools/model_pin.py` reads each mandate's
`Model:` line, then every turn each seat ran (seat_usage.py's readers), and exits 1 on any turn that used another
model. It also lists room errors that reject a model. Replayed on this run, it reports exactly the three gpt-6-sol
turns disclosed above (Builder 2,620 and 44,505 output tokens, Adversary 178). It also lists the five failed turns from 20:04 to 20:38 UTC, while the operator was applying the
pin ("The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account"). Run by the Checker before every gate (`model_pin.py --since
<last receipt>`), it would have refused gate #1 until the pin held. The operator only found the turns at 20:40 UTC,
from the logs.

## Standing it up

1. **Prerequisites.**
   - Install Band Desktop and sign in.
   - Docker must be running.
   - You need Python 3.12 or newer, and git.
   - Set up the event kit at `<KIT>`: `python3 -m venv .venv && .venv/bin/pip install -r harness/requirements.txt && .venv/bin/python -m playwright install chromium`.
   - Install the Claude Code and Codex CLIs and sign in to each.
   - Use one machine that runs nothing else. Our gate runs took 18–36 min at load 140–520, against about 5 min normally.
2. **Seats.** In Band Desktop, create the five local-agent seats from the table.
   - Set each one's runtime command to an absolute path, give all five the working directory `<WORKSPACE>` (the parent of the result repository), and allow edits and commands without asking.
   - Click *Test runtime* on each right before the dispatch, not the day before.
   - **The Codex gotcha.** Band re-sends a seat's saved model with every turn. Give each Codex seat one test turn, then run `python3 tools/model_pin.py --cwd <WORKSPACE> --since <test time>`. Fix the seat's model in Band (`band runtime settings`) until it exits 0. Our run lost three turns to this.
3. **Result repository and seat worktrees.**
   ```sh
   cd <WORKSPACE> && git init -b main result && cd result
   cp -R <FACTORY>/FACTORY.md <FACTORY>/README.md <FACTORY>/DISPATCH.md <FACTORY>/mandates <FACTORY>/tools .
   rm -f tools/gate.json && mkdir -p receipts && touch receipts/.gitkeep
   git add -A && git -c user.name="Factory setup" -c user.email=<SETUP-EMAIL> commit -m "Factory setup"
   git config extensions.worktreeConfig true
   git config --worktree user.name Checker            # the main checkout belongs to the Checker
   for s in coordinator builder builder-two checker adversary; do
     git worktree add -b "$s" ../result-wt/"$s" main
     git -C ../result-wt/"$s" config --worktree user.name "$s"
     git -C ../result-wt/"$s" config --worktree user.email <SEAT-EMAIL>
   done
   ```
   A per-worktree identity avoids the run's slip, where 20 commits carried the shared default identity. `stage-1/` starts empty.
4. **Mandates.** Put the text of `mandates/<seat>.md` into the matching seat's instructions in Band. The `Harness:` and `Model:` lines must match what the seat really runs. Never put anything about the problem into a mandate.
5. **Gate config.** Copy `tools/gate.example.json` to `tools/gate.json` and fill every placeholder with an absolute path. `_doc` explains each key. On macOS keep `checks_out` under your home folder, because Docker must mount it. Optionally run `python3 tools/gate.py install-hook` to refuse ungated stage trees on `main`. It was off in our run.
6. **Check lock.** At most one full harness run should happen at a time.
   - `gate.py` takes the lock itself. It looks for the directory in this order: `gate.json` `"lock"`, then `$CHECK_LOCK`, then `$HOME/DarkFactory/.check-lock`. Always set `lock`.
   - Every other full run goes through a small wrapper. Save this as `<WORKSPACE>/with-check-lock` and `chmod +x` it:
     ```sh
     #!/bin/sh
     LOCK="${CHECK_LOCK:?set CHECK_LOCK}"; i=0
     until mkdir "$LOCK" 2>/dev/null; do i=$((i+1)); [ "$i" -ge 540 ] && { echo "lock busy: $(cat "$LOCK/holder")" >&2; exit 75; }; sleep 5; done
     echo "$$ $(date -u +%FT%TZ) $*" > "$LOCK/holder"
     trap 'rm -f "$LOCK/holder"; rmdir "$LOCK"' EXIT INT TERM
     "$@"
     ```
   - A gate started under the wrapper inherits the lock, because the holder PID is one of its ancestors.
7. **The Checker's checks.** The Checker writes `checker/run_checks.py` for your problem and merges it into `main` before the first gate. Its contract:
   - **Call.** It is called as `checker_command`, run with the clean `--checks-rev` clone as working directory. By default that is `<harness python> checker/run_checks.py --repo <clean product clone> --stage N --out <gate out>/checker`.
   - **Its job.** It builds and starts `stage-N/` itself and runs only the checks that bind stage N. Ours keeps `checker/items.json`, which maps each work item to the first stage it binds.
   - **Green.** The gate counts the step green only on exit 0 **and** at least one test with no failures or errors, counted from JUnit XML under `<out>/checker/` or else from a pytest summary line on stdout.
   - **Mutation runs.** It also accepts `--stage-dir <folder>`, so `seeded_faults.py` can point it at a mutated copy.
8. **Dry check.** Run `harness check <WORKSPACE>/result --track <track>` from `<KIT>`, then `python3 tools/gate.py verify` in the result repository. Then run `band doctor`: every seat must be connected and must answer a mention in a fresh room that holds all five seats.
9. **Dispatch.** Fill in `DISPATCH.md` and post it as one message to @Coordinator. It is the only human input.
10. **During the run, watch only.**
    - Every few minutes, save the newest pages with `band room messages <ROOM> --json --page 1`, then run `python3 tools/liveness.py <pages>`. It exits 1 while the band is stalled.
    - Run `python3 tools/model_pin.py --cwd <WORKSPACE> --since <last receipt time>`.
    - Resolve runtime problems before the dispatch. During a submitted run, follow the organizer's input rules, and don't assume an infrastructure intervention (such as Band's *Restart agent*) is exempt. Record any intervention, its time and its effect, as *Operator actions during the run* does here. Never post to the room.
11. **After the run.**
    - In the Band console, scroll the room to its very top first, because the export holds only the messages the page has loaded. Our first download had 2,700 of 6,645.
    - Then use ⋮ → Download → *Download full room transcript* (the guide calls it *Download full session*) and save it as `room.json` at the repository root.
    - On a fresh clone, run `harness check`, then `harness run --all --mode isolated`, then `gate.py verify`.
    - Then run `tools/room_audit.py`, `tools/factory_numbers.py`, `tools/seat_usage.py` and `tools/spec_coverage.py` (commands in `tools/README.md`).
