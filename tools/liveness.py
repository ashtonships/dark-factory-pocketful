#!/usr/bin/env python3
"""Seat liveness: which seat owes the band a reply and has gone silent.

Added after the submitted run (5 Oct 2026). In that run a vendor safety filter ended the Adversary's turn while it
held stage 4's last review; every seat still showed Connected, nobody woke it, and stage 4 was never accepted.

A seat owes a reply from the first text message that addresses it (`@[[seat-id]]` in a room export, or
`mention_names` in `band room messages --json`; the human dispatch counts) until that seat next posts a text message.
A stall is reported when the whole room has been quiet (no seat sent a text, thought or tool call) for --silence
minutes while at least one seat still owes a reply: a seat waiting while others work is normal, a room where nobody
works while work is held is the failure. Each owing seat is named with its last error, when that is what it last
sent. Read-only: it never posts, restarts or wakes anything.

  liveness.py room.json                       # replay the run: every stall, when it would have been reported
  liveness.py room.json --at 2026-10-04T09:00Z    # state at one moment
  band room messages ROOM --json --page N ...  # live: save the pages, pass the files; exit 1 while a seat is stalled
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True

MENTION = re.compile(r"@\[\[([0-9a-f-]{36})\]\]")


def when(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalise(raw: dict) -> dict:
    """One message from either a console export (camelCase) or a `band room messages --json` page (snake_case)."""
    if "insertedAt" in raw:
        content = raw.get("content") or ""
        kind = raw.get("messageType")
        mentions = set(MENTION.findall(content)) if kind == "text" else set()
        return {"at": when(raw["insertedAt"]), "kind": kind, "sender": raw.get("senderId"),
                "name": raw.get("senderName"), "agent": raw.get("senderType") == "Agent",
                "mentions": mentions, "content": content}
    content = raw.get("content") or ""
    kind = raw.get("message_type")
    names = raw.get("mention_names") or {}
    mentions = set(names) | (set(MENTION.findall(content)) if kind == "text" else set())
    return {"at": when(raw["inserted_at"]), "kind": kind, "sender": raw.get("sender_id"),
            "name": raw.get("sender_name"), "agent": raw.get("sender_type") == "Agent",
            "mentions": mentions if kind == "text" else set(), "content": content}


def load(paths: list[Path]) -> list[dict]:
    seen, messages = set(), []
    for path in paths:
        data = json.loads(path.read_text())
        rows = data.get("messages", []) if isinstance(data, dict) else data
        for raw in rows:
            if raw.get("id") in seen:
                continue
            seen.add(raw.get("id"))
            messages.append(normalise(raw))
    return sorted(messages, key=lambda m: m["at"])


def state(messages: list[dict], at: datetime, silence: timedelta) -> list[dict]:
    """Seats that owe a reply at `at` and have been silent for at least `silence`."""
    seats = {m["sender"]: m["name"] for m in messages if m["agent"] and m["sender"]}
    owed: dict[str, tuple[datetime, str]] = {}
    last_seen: dict[str, datetime] = {}
    last_kind: dict[str, dict] = {}
    for m in messages:
        if m["at"] > at:
            break
        sender = m["sender"]
        if m["agent"] and sender in seats:
            last_seen[sender] = m["at"]
            last_kind[sender] = m
            if m["kind"] == "text":
                owed.pop(sender, None)
        if m["kind"] == "text":
            for seat in m["mentions"]:
                if seat in seats and seat != sender and seat not in owed:
                    owed[seat] = (m["at"], seats.get(sender) or ("the dispatch" if not m["agent"] else "?"))
    room_quiet_from = max(last_seen.values(), default=None)
    if room_quiet_from is None or at - room_quiet_from < silence:
        return []
    stalled = []
    for seat, (since, by) in sorted(owed.items(), key=lambda item: item[1][0]):
        quiet_from = max(since, last_seen.get(seat, since))
        if at - quiet_from >= silence:  # the room is quiet too (checked above)
            last = last_kind.get(seat)
            error = last["content"][:160] if last and last["kind"] == "error" else None
            stalled.append({"seat": seats[seat], "owes": by, "owed_since": stamp(since),
                            "silent_since": stamp(quiet_from), "silent_minutes": int((at - quiet_from).total_seconds() // 60),
                            "last_error": error})
    return stalled


def replay(messages: list[dict], silence: timedelta, until: datetime, step: timedelta) -> list[dict]:
    """Every stall in the run, with the first minute a watchdog polling every `step` would have reported it."""
    incidents: dict[tuple[str, str], dict] = {}
    moment = messages[0]["at"]
    while moment <= until:
        for row in state(messages, moment, silence):
            key = (row["seat"], row["silent_since"])
            if key not in incidents:
                incidents[key] = dict(row, reported_at=stamp(moment))
            incidents[key]["silent_minutes"] = row["silent_minutes"]
        moment += step
    return sorted(incidents.values(), key=lambda row: row["reported_at"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path, help="room.json, or saved `band room messages --json` pages")
    parser.add_argument("--silence", type=int, default=30, help="minutes of silence before a seat is reported (30)")
    parser.add_argument("--at", help="report the state at this UTC time instead of replaying")
    parser.add_argument("--until", help="replay until this UTC time (default: last message + 12 h)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    messages = load(args.files)
    if not messages:
        print("no messages", file=sys.stderr)
        return 2
    silence = timedelta(minutes=args.silence)
    if args.at:
        rows = state(messages, when(args.at), silence)
    else:
        until = when(args.until) if args.until else messages[-1]["at"] + timedelta(hours=12)
        rows = replay(messages, silence, until, timedelta(minutes=1))
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            head = f"{row.get('reported_at', '')} " if "reported_at" in row else ""
            print(f"{head}{row['seat']} owes {row['owes']} since {row['owed_since']}, silent since "
                  f"{row['silent_since']} ({row['silent_minutes']} min)"
                  + (f"; last sent an error: {row['last_error']}" if row["last_error"] else ""))
        if not rows:
            print("no stalled seat")
    return 1 if (args.at and rows) else 0


if __name__ == "__main__":
    sys.exit(main())
