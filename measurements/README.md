# Measurements

Raw outputs of the commands FACTORY.md quotes, made after the run by the factory's operator (not by a seat). Inputs
are this repository, `room.json` and the seats' local session logs, all read-only.

| File | Command |
|---|---|
| `factory_numbers.md` | `python3 tools/factory_numbers.py --repo . --branch main --room room.json --receipts receipts/chain.jsonl --forbidden <event kit>/pocketful/test --builder Builder --builder Builder-Two --format markdown` |
| `room_audit.md` | `python3 tools/room_audit.py room.json --forbidden <event kit>/pocketful/test --forbidden-regex '\btest/stage_\d' --builder Builder --builder Builder-Two --format markdown` |
| `seat_usage.md` | `python3 tools/seat_usage.py --since 2026-10-03T16:49:58Z --until 2026-10-04T08:20:00Z --format markdown` (reads the local Claude Code and Codex session logs, so only the machine that ran the seats can reproduce it) |
| `factory_numbers-run-end.md` | the same `factory_numbers.py` command with `--branch 02600fb`: the run's last commit, before any operator commit after the run. FACTORY.md quotes its shares |
| `spec_coverage.md` | `python3 tools/spec_coverage.py --spec <event kit>/pocketful/spec --ledger ledger/pocketful.md --checks checker --format markdown` |
| `liveness-replay.md` | `python3 tools/liveness.py room.json --until 2026-10-04T19:00:00Z` (tool added after the run) |
| `model-pin-replay.md` | `python3 tools/model_pin.py --cwd <band-work> --since 2026-10-03T16:49:58Z --until 2026-10-04T08:20:00Z --room room.json` (tool added after the run) |
| `harness-isolated/` | the event harness, `harness run --repo <fresh clone of 02600fb> --all --mode isolated` (Sun 4 Oct 19:10 UTC): summary, and per folder the report and the counts for every suite it ran, including the next-stage probe |


`room.json` is the full download unchanged except for two values. First, a private e-mail address that a seat's
`git config` call printed (2026-10-04T03:36:14Z) is replaced by `[REDACTED]`, as the participant guide allows.

Second, the session token of the band's own local test service (1 distinct value, sent with curl to 127.0.0.1 inside tool calls) is replaced by `[REDACTED]` wherever it appears: it matches the harness's credential shape although it was a throwaway test value.
