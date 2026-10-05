# DISPATCH.md

The exact dispatch of the submitted run is in `room.json`: message `ce2a5988-7e6c-46eb-bd72-0168cd4b0082`
(2026-10-03T16:49:58Z, the only human message in the room). This file is its generic form, written after the run:
every process rule is kept, and everything that belonged to that one track (the product, its stack, its screens, its
times) is a `<PLACEHOLDER>`. One rule was added from the run's own lessons and is marked *(added after the run)*.
Fill every placeholder, delete the `<!-- -->` notes, and post the text below the line as one message addressed to the
Coordinator seat. Use absolute paths: a seat may not resolve a relative one.

| Placeholder | Example |
|---|---|
| `<COORDINATOR>` | the Coordinator's mention, as Band writes it (`@[[seat-id]]` in a raw message) |
| `<PRODUCT>` / `<ONE-LINE PRODUCT DESCRIPTION>` | the track's product name and what it is |
| `<REPO>` | absolute path of the result repository |
| `<WORKTREES>` | absolute folder holding one worktree per seat, e.g. `<REPO>-wt` |
| `<SPEC>` | absolute folder holding `stage-1.md` … `stage-4.md` and nothing else |
| `<KIT>` | absolute path of the event kit (harness, shipped tests); Checker and Adversary only |
| `<TRACK>` | the harness track name |
| `<CHECKS>` | absolute folder for check output |
| `<LOCK-WRAPPER>` | your check-lock wrapper (see FACTORY.md, *Standing it up*) |
| `<STACK>` | the stack decision, or delete the paragraph to let the band choose |
| `<LAYER A>` / `<LAYER B>` | the two builders' layers |
| `<UI STAGE>` | the first stage whose specification has screens |
| `<DEADLINE>`, `<CUT-1>`, `<CUT-2>`, `<TIME ZONE>` | absolute times with zone |

---

<COORDINATOR>: the <PRODUCT> task. This message is the only input this run gets: nobody will answer, approve or steer
after it, so decide from the specification, record why, and keep moving. Run all four stages in order with the band,
following your mandates, and post your final report when stage 4 is accepted, when the time box below ends, or when you
are blocked. Start now.

Paths (absolute):
- Result repository (commit only here; its `main` belongs to @Checker): <REPO>
- Seat worktrees (one per seat and branch, created from the result repository): <WORKTREES>/<seat>
  with branches `coordinator`, `builder`, `builder-two`, `checker`, `adversary`
- Specifications for builders (specs only): <SPEC>/stage-1.md … stage-4.md
- Full event kit with the harness and the shipped tests (@Checker and @Adversary only): <KIT>
- Check output folders (a new sub-folder per run): <CHECKS>
- Shared check lock (wrap every full run that is not the gate; the gate takes it itself): <LOCK-WRAPPER> <command>
- Design images: design/<stage>/ in the result repository, outside every stage folder

Task: build <PRODUCT>, <ONE-LINE PRODUCT DESCRIPTION>, one stage at a time, to the four specifications. Every handoff
carries the complete specification text of its stage, pasted into the message (split it into numbered messages if it
is long), as your mandate says; a handoff never says "see above" or points at a room message. Write the ledger one
stage at a time (stage N's ledger before stage N's first assignment), not all four up front, so building starts early.

Stack (decided, so nobody spends time choosing): <STACK: one container per stage folder; the language and HTTP server;
where state lives and how a write that must be atomic is made atomic; how the interface is served; no runtime
dependency outside the image and no outbound network at run time>.

Split the building by layer so both builders carry real work: @Builder owns <LAYER A>; @Builder-Two owns <LAYER B>.
Either may take the other's item when <COORDINATOR> reassigns it.
<!-- In the submitted run: Builder (Codex) owned the data model, transactions and the API; Builder-Two (Claude Code)
owned the browser screens and their client-side recovery flows. Keep the two builders on different model families
from their reviewers. -->

The screens arrive in stage <UI STAGE> and their product quality counts. Design first, one round: @Builder draws three
concepts per screen, @Checker picks one per screen (or asks once for one revision), and the screens are built to the
pick. Start the design item as soon as the data model it depends on is accepted, so it is ready when stage <UI STAGE>
begins. <!-- Delete this paragraph if the track has no interface. -->

Deliverable-folder rules (these decide whether a stage counts):
- Each stage-N/ folder is a complete, buildable service on its own, holding the solution to stage N and nothing later.
  Stage 1 goes in `stage-1/`, which starts empty.
- Once stage N is accepted, freeze stage-N/. Stage N+1 is a copy of stage-N/ extended to the next specification. Never
  copy a .git folder.
- A folder that also passes the next stage's whole suite claims nothing: never build ahead in an earlier folder.
- Every folder has its own Dockerfile and RUN.md and must start from a clean container with no outbound network.

Acceptance is code, not assurance. @Checker accepts a revision only through the gate, from the result repository:
  cd <REPO> && python3 tools/gate.py run --stage N --rev <the exact commit to merge>
The gate clones that commit cleanly, takes the check lock, and runs, stopping at the first red step: the mandate and
credential scan, the test-fitting scan on stage-N/, the event harness in isolated mode (no network, the published CPU
and memory limits; every suite up to N plus the overshoot probe; "claimed stage: N" required), then @Checker's own
checks. It appends a hash-chained receipt to receipts/chain.jsonl and prints one line, GATE GREEN or GATE RED with the
reasons; paste that line verbatim into every verdict. Use `--level item` for a work item that does not finish its
stage (earlier suites must still hold and @Checker's checks must pass; suite N may be incomplete); a stage is accepted
only by a green receipt at the default `--level stage`.
<!-- Keep the next sentence only if the freeze hook is NOT installed (`python3 tools/gate.py install-hook`). -->
No hook enforces this for you, so the rule is yours: never let an update of `main` change a stage-N/ tree that has no
green receipt for that exact tree, and treat a stage with a green stage-level receipt as frozen: it changes only with
another green stage-level receipt. `python3 tools/gate.py verify` rechecks every stage tree `main` ever held against
the receipts, so a merge that breaks this rule shows in the final report. So: gate the builder's handed-back commit,
merge only after GATE GREEN, and when two branches change the same stage folder, merge them on a branch first, gate
that commit, then merge it into main. After each merge, @Checker commits receipts/ on main (outside every stage
folder).

@Checker's own checks plug into the gate through one contract, set in tools/gate.json (`checker_command`): create
`checker/run_checks.py` on your branch before the first gate run. Called as
`<harness python> checker/run_checks.py --repo <clean checkout> --stage N --out <folder>`, it builds and starts
stage-N/ itself, runs every check of yours that binds stage N, writes JUnit XML into the out folder, and exits 0 only
when all of them pass (no tests found counts as red). The gate runs your checks and reads tools/gate.json from `main`
(or the commit you name with `--checks-rev`), never from the builder's branch, so merge your checks into main before
gating with them. `python3 tools/gate.py show` lists the receipts; `python3 tools/gate.py verify` checks the chain and
main's history. If the gate itself cannot run (exit 2, not a red verdict) twice with the same error, @Checker records
the error in the room and as a ledger entry, and the band continues; a red verdict is never bypassed.

Shipped checks are only part of what judging runs, so a stage is accepted on @Checker's checks from the specification
plus the gate, never on the harness alone. Builders verify their own work by building and starting the container per
RUN.md and exercising the specification; they never open the shipped tests and never run the harness.

Time box and cut order (check `date`; times are <TIME ZONE>): the final report is due by <DEADLINE>.
- Stage 1 is the floor: it comes first and is never traded away.
- If stage 3 is not accepted by <CUT-1>, do not start stage 4; finish and harden stages 1 to 3.
- If stage 3 cannot be accepted by <CUT-2>, stop work on it; the entry is stages 1 and 2, and stage-3/ is not merged.
- A cut applies at its time, not as a forecast: until the clock reads <CUT-1>, keep working toward the stage it guards.
  *(added after the run: the run's Coordinator applied the stage-4 cut on a forecast, 2 h 50 min before its time, and
  stage 3 was then accepted 1 h 42 min before the cut time; the band had to reopen stage 4 itself.)*
- Never leave stage-<UI STAGE>/ with screens that are not presentable: polish it before starting the next stage.
- A stage folder that is not accepted is never merged into main (`tools/gate.py verify` reports any that was).

Keep the ledger, the design images, the checker's checks, the adversary's scripts and the receipts outside the stage
folders. Every seat commits with its own identity and the work-item id. Never rewrite history. Mandates stay as they are:
nothing specific to this task is ever written into mandates/.

The final report (Coordinator, in the room) gives: the committed revision of `main`; the stages accepted, each with its
GATE GREEN line; ledger coverage, pasted from
  cd <REPO> && python3 tools/spec_coverage.py --spec <SPEC> --ledger ledger/<task>.md --checks checker --format markdown
the Adversary's seeded-fault catch rate and the test-fitting scan result; every check run and its result; the cuts
applied and when; and what remains uncertain. Before it, @Checker also runs and pastes:
  cd <KIT> && .venv/bin/python -m harness check <REPO> --track <TRACK>
  cd <REPO> && python3 tools/gate.py verify
