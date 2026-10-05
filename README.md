# Pocketful, built by an evidence-gated factory

**Team:** Ashton MacDonald (solo entrant). Five agent seats in one Band Desktop room did the work; his only input was
the dispatch message.
**Track:** pocketful. **Stages submitted:** 1, 2 and 3.

Five seats on two model families (Claude Code with claude-opus-5-5, Codex with gpt-6.1-sol) turned the Pocketful
specification into a requirements ledger. Two builders built it without seeing the shipped tests, a Checker tested it
with checks written from the specification, and an Adversary attacked what was accepted. No seat could say "done".
Only `tools/gate.py` could, and every verdict it gave, red or green, is a hash-chained receipt in this repository.

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
| `room.json` | the Band room the work happened in, downloaded unchanged |
| `design/` | the three concepts per screen the factory drew before building the stage-2 UI, and the pick |
| branches `coordinator`, `builder`, `builder-two`, `checker`, `adversary` | each seat's own branch, pushed as the seat left it. `builder` and `builder-two` hold the stage-4 work that was never accepted; `adversary` holds its attack scripts |
| `ui-core/` | the client-side code Builder-Two developed before stage 2 existed. It is not part of any stage folder |

## Check it yourself

```sh
python3 tools/gate.py verify      # re-proves every receipt and every stage tree main ever held
python3 tools/gate.py show        # one line per receipt: time, verdict, stage, revision, tree, reason
cd stage-2 && docker build -t pocketful-stage-2 . && docker run --rm -p 18080:18080 -e PORT=18080 pocketful-stage-2
# then open http://127.0.0.1:18080/
```

## Scoreboard

| Stage | Green receipt | Revision | Stage tree | Shipped checks (cumulative) | Checker's checks |
|---|---|---|---|---|---|
| 1 | #4, 2026-10-04 02:59 UTC | 57cc82e | 8f19cbfb6d7e | 146/147 | 234/234 |
| 2 | #6, 2026-10-04 06:09 UTC | bc4cc1c | ad34602f4b70 | 182/182 | 329/329 |
| 3 | #7, 2026-10-04 07:18 UTC | 5413e25 | 276ec0a8a545 | 188/188 | 397/397 |

- On a fresh clone of `main`, the event harness in isolated mode reports stage-1/ claims 1, stage-2/ claims 2 and
  stage-3/ claims 3, with no overshoot.
- Human messages in the room after the dispatch: **0**. Builder tool calls touching the shipped tests: **0** of
  1,224 (`tools/room_audit.py`).
- One real catch: GATE RED #8, a duplicate token accepted on import. The shipped tests passed it and the Checker's
  check failed it. Builder-Two fixed it, and GATE GREEN #9 came 14 min 44 s later.
- Output tokens: 1.46 M across the five seats, measured from their session logs. 3.2% of them came from turns on a
  model other than the mandated one, which we disclose (FACTORY.md, *Cost and time*).
- Stage 4 was built but not accepted before the band's own cut-off, because the Adversary seat was stopped by a
  vendor safety filter. It is not submitted. FACTORY.md, *What failed*, explains it.
