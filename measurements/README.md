# Measurements

Raw outputs of the commands FACTORY.md quotes, made after the run by the factory's operator (not by a seat). Inputs
are this repository, `room.json` and the seats' local session logs, all read-only.

| File | Command |
|---|---|
| `factory_numbers.md` | `python3 tools/factory_numbers.py --repo . --branch main --room room.json --receipts receipts/chain.jsonl --forbidden <event kit>/pocketful/test --builder Builder --builder Builder-Two --format markdown` |
| `room_audit.md` | `python3 tools/room_audit.py room.json --forbidden <event kit>/pocketful/test --forbidden-regex '\btest/stage_\d' --builder Builder --builder Builder-Two --format markdown` |
| `seat_usage.md` | `python3 tools/seat_usage.py --since 2026-10-03T16:49:58Z --until 2026-10-04T08:20:00Z --format markdown` (reads the local Claude Code and Codex session logs, so only the machine that ran the seats can reproduce it) |
| `harness-isolated.json` | the event harness, `harness run --repo <fresh clone of main> --all --mode isolated`, summary |
