# Pocketful, built by an evidence-gated factory

**Team:** Ashton MacDonald (solo entrant). Five agent seats in one Band Desktop room did the work; his only input to
the room was the dispatch message. His infrastructure actions outside the room are listed with their times in FACTORY.md,
*Operator actions during the run*.
**Track:** pocketful. **Stages submitted:** 1, 2 and 3.

Five seats on two model families (Claude Code with claude-opus-5-5, Codex with gpt-6.1-sol) turned the Pocketful
specification into a requirements ledger. Two builders built it without seeing the shipped tests, a Checker tested it
with checks written from the specification, and an Adversary attacked what was accepted. No seat could say "done".
Only `tools/gate.py` could, and every verdict it gave, red or green, is a hash-chained receipt in this repository.

**For judges, in one minute:** [`FACTORY.md`](FACTORY.md) is the factory and what it measured;
[`TEAMWORK.md`](TEAMWORK.md) is the evidence that the seats did the work together and without a human;
[`docs/APP.md`](docs/APP.md) is a tour of the app with screenshots of every state the stage-2 specification names;
[`DISPATCH.md`](DISPATCH.md) is the dispatch in generic form, so the factory can be pointed at another problem.

## How to read this repository

| Path | What it is |
|---|---|
| [`FACTORY.md`](FACTORY.md) | the factory: seats, setup, design choices and their cost, measured time and tokens, what it caught, what failed |
| [`mandates/`](mandates/) | one generic mandate per seat, each starting with its harness and model |
| `stage-1/`, `stage-2/`, `stage-3/` | the service, one complete folder per stage, each with its `Dockerfile` and `RUN.md`. Written only by the band |
| [`ledger/pocketful.md`](ledger/pocketful.md) | the requirements ledger: every sentence of the specification as a numbered entry, plus decisions (D-1 to D-27) and findings (9001 onward) |
| [`ledger/status.md`](ledger/status.md) | the Coordinator's running status: every work item, handoff, verdict and exception |
| [`checker/`](checker/) | the Checker's own checks, written from the specification (`checker/run_checks.py`) |
| [`receipts/chain.jsonl`](receipts/chain.jsonl) | the gate's receipts: every acceptance run, 4 green and 5 red |
| [`tools/`](tools/) | the gate and the measurement tools |
| [`measurements/`](measurements/) | raw output of the measurement commands quoted in FACTORY.md |
| `room.json` | the Band room the work happened in, downloaded from the Band console (two values redacted, see `measurements/README.md`) |
| `design/` | the three concepts per screen the factory drew before building the stage-2 UI, and the pick |
| branches `coordinator`, `builder`, `builder-two`, `checker`, `adversary` | each seat's own branch, pushed as the seat left it. `builder` and `builder-two` hold the stage-4 work that was never accepted; `adversary` holds its attack scripts |
| `ui-core/` | the client-side code Builder-Two started before stage 2 and kept identical to `stage-2/ui` and `stage-3/ui`. It is not itself a stage folder |

## Check it yourself

```sh
python3 tools/gate.py verify      # checks the receipt chain, and that every stage tree main held has a green receipt
python3 tools/gate.py show        # one line per receipt: time, verdict, stage, revision, tree, reason
cd stage-2 && docker build -t pocketful-stage-2 . && docker run --rm -p 18080:18080 -e PORT=18080 pocketful-stage-2
# then open http://127.0.0.1:18080/
```

## Scoreboard

| Stage | Green receipt | Revision | Stage tree | Shipped checks at the receipt (cumulative) | Shipped checks, fresh clone, quiet machine | Checker's checks | Obligations with a Checker-written check |
|---|---|---|---|---|---|---|---|
| 1 | #4, 2026-10-04 02:59 UTC | 57cc82e | 8f19cbfb6d7e | 146/147 (1 reset timeout under host load 150–290) | 147/147 | 234/234 | 246/252 |
| 2 | #6, 2026-10-04 06:09 UTC | bc4cc1c | ad34602f4b70 | 182/182 | 182/182 | 329/329 | 204/211 |
| 3 | #7, 2026-10-04 07:18 UTC | 5413e25 | 276ec0a8a545 | 188/188 | 188/188 | 397/397 | 109/109 |

- On a fresh clone of `main`, the event harness in isolated mode reports stage-1/ claims 1, stage-2/ claims 2 and
  stage-3/ claims 3, with no overshoot.
- Human messages in the room after the dispatch: **0**. Builder tool calls touching the shipped tests: **0** of
  1,224 (`tools/room_audit.py`).
- **Spec coverage:** all 611 specification sentences of stages 1–3 are in the requirements ledger, and 559 of their
  572 obligations (98%) have a check the Checker wrote from the specification. 188 checks shipped
  (`measurements/spec_coverage.md`).
- **What the factory caught:** 5 red gate receipts, the seven catches in FACTORY.md (*How the factory catches bad work*),
  and 40 "reject" messages followed by a commit on the same work item (a text-matching upper bound). Five review-to-fix chains are traced message by message in TEAMWORK.md (c). The
  sharpest: GATE RED #8, a duplicate token accepted on import. The shipped tests passed it and only the Checker's
  spec-derived check failed it. Builder-Two fixed it and GATE GREEN #9 came 14 min 44 s after RED #8. That fix was gated but
  never merged: it waited for the stage-4 gate, and the band stalled first. So `main`'s stage-3 is receipt #7's tree and
  still has this defect.
- **Known defect on `main`, stated up front:** `stage-3/` (receipt #7's tree) accepts an import whose export repeats
  one token. The Checker's check caught it (GATE RED #8) and Builder-Two's fix passed the gate (GREEN #9), but the fix
  lives only on the builder branches: `git show a3f0daa -- stage-3` is the fix, and
  `git diff main:stage-3 06d4eea:stage-3` is everything `main` lacks. Merging it would be a hand commit into a stage
  folder after the run, so we did not.
- Output tokens: 1.46 M (the five seats plus 14 automated commit-hook review sessions, FACTORY.md *Cost and time*), measured from session logs. 3.2% of them came from turns on a
  model other than the mandated one, which we disclose (FACTORY.md, *Cost and time*).
- Stage 4 was built but not accepted before the band's own cut-off, because the Adversary seat was stopped by a
  vendor safety filter. It is not submitted. FACTORY.md, *What failed*, explains it.
