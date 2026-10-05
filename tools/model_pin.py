#!/usr/bin/env python3
"""Model pin: did every seat run on the model its mandate names?

Added after the submitted run (5 Oct 2026). In that run Band re-sent a seat's saved model with every turn, so the two
Codex seats ran three turns on gpt-6-sol although their mandates say gpt-6.1-sol, and nothing in the factory noticed;
the operator found it hours later in the session logs.

For each seat it reads the `Model:` line of mandates/<seat>.md, then every turn that seat ran in the window, using
seat_usage.py's readers (Claude Code transcripts and Codex rollouts, attributed by the seat's mandate heading), and
reports each turn on another model. With --room it also lists room error messages that reject a model. Exit 1 on any
mismatch, so a checker can run it before each gate (`model_pin.py --since <last receipt>`). Read-only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import seat_usage  # noqa: E402

MODEL_LINE = re.compile(r"^Model:[ \t]*(\S+)", re.MULTILINE)
MODEL_ERROR = re.compile(r"model[^\n]{0,80}not supported|unknown model|model_not_found|invalid model", re.IGNORECASE)


def mandate_models(folder: Path) -> dict[str, str]:
    pins = {}
    for path in sorted(folder.glob("*.md")):
        found = MODEL_LINE.search(path.read_text())
        if found:
            heading = re.search(r"^#[ \t]+([A-Za-z][\w-]*)", path.read_text(), re.MULTILINE)
            pins[heading.group(1) if heading else path.stem] = found.group(1)
    return pins


def mismatches(sessions: list[dict], pins: dict[str, str]) -> list[dict]:
    rows = []
    for session in sessions:
        seat = session.get("seat")
        if seat not in pins:
            continue
        for model, data in sorted(session["models"].items()):
            if model != pins[seat]:
                rows.append({"seat": seat, "pinned": pins[seat], "ran": model, "turns": data["turns"],
                             "output_tokens": data.get("output", 0), "first": data.get("first"),
                             "last": data.get("last")})
    return sorted(rows, key=lambda row: row["first"] or "")


def room_model_errors(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    rows = data.get("messages", []) if isinstance(data, dict) else data
    out = []
    for raw in rows:
        kind = raw.get("messageType") or raw.get("message_type")
        text = raw.get("content") or ""
        # Band records a failed turn twice: an `error` message and a `task` event whose text starts "error:".
        failed = kind == "error" or (kind == "task" and text.startswith("error:"))
        if failed and MODEL_ERROR.search(text):
            out.append({"at": raw.get("insertedAt") or raw.get("inserted_at"),
                        "seat": raw.get("senderName") or raw.get("sender_name"), "error": text[:200]})
    out.sort(key=lambda row: row["at"] or "")
    unique = []  # one row per failure: drop the twin recorded within 30 s by the same seat
    for row in out:
        if unique and unique[-1]["seat"] == row["seat"] and _seconds(unique[-1]["at"], row["at"]) <= 30:
            continue
        unique.append(row)
    return unique


def _seconds(earlier: str, later: str) -> float:
    return (seat_usage.parse_time(later) - seat_usage.parse_time(earlier)).total_seconds()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mandates", type=Path, default=Path(__file__).resolve().parents[1] / "mandates")
    parser.add_argument("--since", help="window start, ISO time with zone")
    parser.add_argument("--until", help="window end, ISO time with zone")
    parser.add_argument("--cwd", required=True, help="the seats' working directory")
    parser.add_argument("--claude-root", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--room", type=Path, help="room.json or a saved messages page: also list model errors")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    pins = mandate_models(args.mandates)
    if not pins:
        print("no mandate with a Model: line", file=sys.stderr)
        return 2
    since = seat_usage.parse_time(args.since) if args.since else None
    until = seat_usage.parse_time(args.until) if args.until else None
    report = seat_usage.build_report(args.cwd, since, until, sorted(set(pins.values())), args.claude_root,
                                     args.codex_root, seats=list(pins))
    rows = mismatches(report["sessions"], pins)
    errors = room_model_errors(args.room) if args.room else []
    if args.json:
        print(json.dumps({"pins": pins, "mismatches": rows, "room_model_errors": errors}, indent=2))
    else:
        print("pins: " + ", ".join(f"{seat}={model}" for seat, model in pins.items()))
        for row in rows:
            print(f"MISMATCH {row['seat']}: pinned {row['pinned']}, ran {row['ran']} for {row['turns']} turn(s), "
                  f"{row['output_tokens']:,} output tokens, {row['first']} to {row['last']}")
        for error in errors:
            print(f"ROOM ERROR {error['at']} {error['seat']}: {error['error']}")
        if not rows:
            print("every seat ran on its pinned model")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
