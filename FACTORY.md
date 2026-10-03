# FACTORY.md

An evidence-gated software factory: five seats in one Band Desktop room that turn a written specification into a
requirements ledger, build against it, check it independently and attack it, and accept nothing on anyone's word.

> The *measured* sections below come from the practice run on the event's toy track (26–27 Sep 2026, repository
> `toy-result`, 91 commits on `main`) and from a replay of the gate on a copy of it (1 Oct 2026). The pocketful run's
> own numbers replace them when that run finishes.

## The idea in one paragraph

Most failures in agent-built software are not code that fails its tests; they are requirements nobody tested. So
the factory's centre is not the builder but the **requirements ledger**: before anything is built, the coordinator
writes every obligation in the specification as a numbered entry quoting its source sentence. Every work item
carries its entries. The checker writes its own tests from those sentences, never from the tests that happened to
ship, and a revision is accepted only when every entry has evidence the checker produced itself. The adversary then
attacks what was accepted (concurrency, retries, restarts, limits, upgrades), and every finding becomes a ledger
entry that later work must also satisfy. Checking is vendor-crossed: code written by one model family is checked by
the other.

## Seats

| Seat | Harness | Model | Owns | Never does |
|---|---|---|---|---|
| Coordinator | Claude Code | claude-opus-5-5 | the ledger and its status, the plan, every handoff, the final report | write product code or tests |
| Builder | Codex | gpt-6.1-sol | implementing its work items to the specification, on its own branch | read shipped tests, accept its own work |
| Builder-Two | Claude Code | claude-opus-5-5 | implementing its work items (a different scope), on its own branch | read shipped tests, accept its own work |
| Checker | Claude Code | claude-opus-5-5 | checks from the specification; the acceptance run; interface review; the verdict; merging to main | edit product code, weaken a check |
| Adversary | Codex | gpt-6.1-sol | the pre-mortem; attacks on accepted work; code review of Builder-Two's work | edit product code, give verdicts |

Every line of product code is examined by a model family other than the one that wrote it: Builder's (Codex) work
is judged by the Checker (Claude); Builder-Two's (Claude) work is code-reviewed by the Adversary (Codex) before the
Checker's verdict. Both families build, so the factory is not a single model checking itself. **Builders build blind**: they get the specifications, never
the shipped tests, so nothing can be written to the tests; only the Checker runs the event harness. Each seat works
on its own branch in its own worktree; the Checker merges accepted branches into `main` without rewriting history, so
every commit traces to a seat, a work item and a room message.

Mandates: `mandates/<seat>.md`, one per seat, each starting with its harness and model. They describe how each seat
works and name nothing about any particular problem.

## The loop, per task

1. **Ledger.** The coordinator reads the whole specification and commits `ledger/<task>.md`: one numbered entry per
   obligation, each quoting its sentence. Ambiguities are resolved in writing, choosing the reading that keeps every
   stated invariant.
2. **Plan.** Entries are grouped into work items in dependency order: runtime contract and data model first.
3. **Design first, for screens.** The Codex builder draws three concepts per screen with its built-in image
   generation. The checker picks one per screen and records why in the ledger. Screens are then built to the pick
   and reviewed against it, side by side, at desktop and phone widths. Server work does not wait for the design.
4. **Build.** The coordinator hands the builder one work item with its entries, the specification text, the paths
   and the acceptance commands, all inside the handoff (no "see above").
5. **Independent check.** In parallel, the checker writes tests for the same entries from the specification text,
   before reading the builder's code.
6. **Acceptance.** The builder hands back a committed revision. The checker checks it out clean, builds it from its
   own run instructions with no outbound network, runs the task's commands, every earlier task's commands and its
   own tests, and reads the diff for anything that recognises tests instead of implementing rules.
7. **Verdict.** Accept, or reject naming the failing entries with a reproduction. A rejection goes back to the
   builder unchanged through the coordinator.
8. **Attack.** The adversary attacks each accepted revision. Findings become ledger entries and new work items.
9. **Done.** The task ends when every entry maps to accepted evidence. The coordinator posts the revision, the ledger
   coverage and every check that was run.

## Why this shape (and what it costs)

- **Ledger first** costs time before the first line of code, and buys coverage of requirements the shipped checks
  never exercise, which is where the full test set is decided.
- **Tests from the specification, by a different seat and model family,** catch the builder's blind spots instead of
  repeating them. The cost is duplicated reading of the specification.
- **An adversary that only attacks accepted work** keeps rejection meaningful: findings are grounded in the
  requirements and reproducible, not manufactured conflict.
- **Two builders on separate scopes** spread the work (no seat writes most of the code) and keep each builder's
  context small; the cost is integration, which the Checker's merge-and-recheck absorbs.
- **Blind building** costs the builders the convenience of green checks, and removes the most common way an entry
  is disqualified: code written to the tests.

## How the factory catches bad work

- **No seat can say "done"; only the gate can.** `tools/gate.py run --stage N --rev <commit>` clones that exact commit,
  takes the shared check lock and runs, stopping at the first red step: the mandate and credential scan, the
  test-fitting scan, the event's checks in isolated mode (no network, the published CPU and memory limits, every
  earlier stage's suite too), and the Checker's own checks. It appends a receipt to `receipts/chain.jsonl` (both
  revisions, the stage folder's git tree hash, every count and timing) carrying the sha256 of the receipt before it,
  so an edited or deleted receipt breaks the chain. The Checker merges a stage folder into `main` only after GATE
  GREEN for that exact tree, and a stage with a green stage-level receipt is frozen. `tools/gate.py verify` rechecks
  the chain and every stage tree `main` ever held, from a clone, so a merge that skipped the gate is visible to anyone.
  A git hook that would refuse such a merge outright exists (`tools/hooks/reference-transaction`) but ships switched
  off: see *What we tried that failed*.
- Nothing is accepted without a revision, the exact commands and their output from the checker's own run.
- Code that special-cases a test, a fixture or an input is a named rejection reason for the checker.
- Every earlier task's acceptance commands run on every new revision, so extending never silently breaks the past.
- The adversary's scripts are committed and run again on every later revision.
- *Measured (toy practice run):* bad results the factory caught.
  - **Keep-alive (ledger 87).** The Adversary's first attack on the accepted stage 1 found that a rejected request
    (404/405/400) left its body unread, so the next request on the same connection broke. Stage 1 was reopened through
    that one entry, fixed by the Builder (a0f7b8e), re-checked and re-frozen.
  - **Out-of-order clicks (ledger 89).** The Adversary's review of Builder-Two's stage-2 page found that two clicks in
    flight could leave the page showing a stale value. The Checker then **rejected** the first rework because its rule
    ("highest value since page load") contradicted another requirement after a reset; the Coordinator amended the
    entry and the second rework was accepted (cfcb370).
  - **Non-JSON bodies (ledgers 94, 95).** Python's JSON parser accepts `NaN`/`Infinity` and silently decodes UTF-16 and
    UTF-32. Both were found by the Adversary in Builder-Two's stage 4 and became 400s.
  - **Chunked bodies (ledger 96).** In its final review the Checker found that a body sent with
    `Transfer-Encoding: chunked` was read as empty, so `{"by":5}` added 1 and the leftover bytes became a stray 400.
    It **rejected** stage 4 and reopened stages 1–3. The shipped stage-1 tests pass that build 8/8; only the Checker's
    own checks see it. The gate replay on 1 Oct reproduced it on the frozen stage-1 tree (GATE RED #5: harness 8/8,
    Checker 81/85) and refused to call it green.
  - **Seeded faults.** The Adversary's mutation runs killed 18/20 (stage 1), 15/20 (stage 2, fast selection) and 18/20
    (stage 3) of deliberately planted faults. Each survivor is listed in the ledger status, and most are behaviour the
    specification leaves open.

## Cost and time *(measured)*

| Task | Wall-clock | Work items | Rejections | Commits by seat (non-merge) | Model usage per seat |
|---|---|---|---|---|---|
| Toy practice, stages 1–4 | 4 h 33 min, ledger (07:05) to last commit (11:38), 27 Sep | 7 (W-0 to W-6, plus W-1b) | 2 (W-3 rework 1; W-5 on ledger 96) | Coordinator 27, Checker 17 (+31 merges), Builder-Two 7, Builder 4 | not metered: all seats ran on flat-rate subscriptions |
| Pocketful | *after the run* | | | | |

On the toy run the Coordinator's first commit was the ledger (61/61 specification sentences ledgered or waived, 3
waivers); findings and decisions grew it to 96 entries. The Checker's 148 checks reference all 71 requirement entries.
Of the builders' added lines, Builder-Two wrote 579 and Builder 365.

## What we tried that failed *(measured)*

- **Seats that could not start.** On the first evening the five seats existed but none answered the roll call. Band
  Desktop's background service could not find the `codex` or `claude` programs on its search path. Fix: each seat's
  runtime command is an absolute path, checked with *Test runtime* before any task is dispatched.
- **A seat that failed between runs.** On 2 Oct both Codex seats showed *Failed* ("an earlier runtime preparation has
  unresolved cleanup") while the three Claude seats were connected. The dispatch was held rather than sent to a
  three-seat band. Rule kept: never dispatch unless `band doctor` shows every seat connected.
- **The freeze hook.** We built a git hook that refuses any update of `main` changing a stage folder without a green
  receipt. On a disposable copy it did the mechanical part: five commits outside the stage folders passed, and a
  commit into a frozen stage was refused with exit 128 in 0.10 s. But we could never show it accepting a *real* green.
  Every real gate run on the toy result was red: the daemon was down in round 1, and in round 2 the Checker found the
  chunked-body defect. Our cut rule said: unproven by the deadline means it does not ship. So the gate, the receipts
  and `gate.py verify` ship; the hook does not.
- **Rework that never landed.** Ledger 96 reopened stages 1–3 at the end of the toy run, and the run stopped before
  that rework was merged. Frozen stage 1 therefore still carries the chunked-body defect: the receipts show it red, and
  nobody overwrote it. On pocketful the time box puts final reviews before the cut-off, not at it.
- **Identity slips.** Three merge commits were made with the machine's default git identity and no work-item id.
  History is never rewritten, so they stay as recorded exceptions (ledger 88), and every later commit pins its seat's
  identity on the command line.

## Standing it up

1. Install Band Desktop, sign in, and create five local-agent seats named as in the table, each with its harness and
   model, all with the same working directory (the parent of your result repository), allowed to edit files and run
   commands without asking.
2. Initialise an empty result repository. Put `README.md`, `FACTORY.md` and `mandates/` at its root, and confirm the
   layout with the event's offline check (`harness check <result> --track <track>`) before the first run.
3. Create one room, add all five seats, and confirm each seat answers a mention and can mention back.
4. Paste the task (the complete specification, the absolute result path, the deliverable-folder rules and the
   acceptance commands) into the room, addressed to @Coordinator. That task is the only input; the band runs to its
   final report on its own.
