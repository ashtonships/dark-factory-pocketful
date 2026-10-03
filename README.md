# Pocketful

Track: pocketful. Built by the factory described in [FACTORY.md](FACTORY.md); the band writes every stage folder, and
only the stage gate (`tools/gate.py`) lets a stage folder onto `main`.

| Path | What it is |
|---|---|
| `FACTORY.md`, `mandates/` | the factory: seats, how they work, what each costs |
| `stage-1/` … `stage-4/` | the service, one complete folder per stage (Dockerfile and RUN.md in each) |
| `ledger/` | the requirements ledger: every obligation of the specification, quoted and numbered |
| `checker/` | the Checker's own checks, written from the specification |
| `receipts/chain.jsonl` | the gate's hash-chained receipts: every acceptance run, green or red |
| `tools/` | the gate, its hook and the measurement tools |
| `room.json` | the Band room the work happened in |
