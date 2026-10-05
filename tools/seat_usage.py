#!/usr/bin/env python3
"""Tokens per seat for one factory run, measured read-only from local session logs.

Claude Code seats: transcripts under <claude-root>/<cwd-slug>*/ (*.jsonl, plus */subagents/*.jsonl). Each
assistant API response carries message.usage and message.model; a response split over several records (one per
content block) shares message.id and is counted once. Records whose `cwd` is outside --cwd are ignored.

Codex seats: rollouts under <codex-root>/YYYY/MM/DD/*.jsonl whose session_meta has the given originator (default
`jam`) and a cwd inside --cwd. token_count events carry a cumulative total per rollout; the run's usage is the last
cumulative total inside the window minus the last one before it. Each increase is booked to the model of the latest
turn_context, so a few minutes on a wrong model shows up as its own row.

Seat attribution never guesses:
  * Claude: BAND's `agent-name` / `custom-title` records, and any seat mandate heading
    (`Harness: ...` / `Model: ...` / `# <Seat>`) in a prompt the seat received (tool results are ignored, since
    a seat may read other seats' mandates).
  * Codex: the mandate heading in the developer instructions (or base instructions).
  A session with no seat, or with more than one, is reported as unattributed with the reason.

Token columns: `input` is uncached input, `cache_write` is Claude cache creation, `cached_input` is input read from
cache, `output` includes reasoning tokens. Codex reports input_tokens including cached tokens; the tool subtracts them
so both providers use the same meaning. Raw fields are kept in the JSON.

Nothing is written; no transcript text is copied into the report.
"""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable


DEFAULT_SEATS = ("Coordinator", "Builder", "Builder-Two", "Checker", "Adversary")
DEFAULT_ALLOW = ("gpt-6.1-sol", "claude-opus-5-5")
MANDATE = re.compile(r"Harness:[ \t]*([^\n]+?)[ \t]*\n[ \t]*Model:[ \t]*([^\n]+?)[ \t]*\n(?:[ \t]*\n)*[ \t]*#[ \t]+([A-Za-z][\w-]*)")
TOKEN_FIELDS = ("input", "cache_write", "cached_input", "output")


def parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"time without a zone: {value!r} (use Z or an offset)")
    return moment.astimezone(timezone.utc)


def iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def within(moment: datetime | None, since: datetime | None, until: datetime | None) -> bool:
    if moment is None:
        return False
    return (since is None or moment >= since) and (until is None or moment <= until)


def inside(path: str | None, root: str) -> bool:
    if not path:
        return False
    path = os.path.normpath(path)
    root = os.path.normpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def claude_slug(cwd: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(cwd))


def read_jsonl(path: Path) -> Iterable[tuple[int, dict]]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield number, record


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten(item) for item in value)
    if isinstance(value, dict):
        if value.get("type") == "tool_result":
            return ""
        if isinstance(value.get("text"), str):
            return value["text"]
        if "content" in value:
            return _flatten(value["content"])
    return ""


def mandate_seats(text: str, seats: Iterable[str]) -> set[str]:
    known = {seat.lower(): seat for seat in seats}
    found = set()
    for match in MANDATE.finditer(text):
        seat = known.get(match.group(3).lower())
        if seat:
            found.add(seat)
    return found


def _empty_tokens() -> dict:
    return {field: 0 for field in TOKEN_FIELDS}


def _add(target: dict, tokens: dict) -> None:
    for field in TOKEN_FIELDS:
        target[field] += tokens.get(field, 0)


def _seen(entry: dict, moment: datetime | None) -> None:
    if moment is None:
        return
    stamp = iso(moment)
    if entry.get("first") is None or stamp < entry["first"]:
        entry["first"] = stamp
    if entry.get("last") is None or stamp > entry["last"]:
        entry["last"] = stamp


def _attribution(names: set[str], mandates: set[str]) -> tuple[str | None, str | None]:
    candidates = names | mandates
    if not candidates:
        return None, "no agent name or seat mandate found"
    if len(candidates) > 1:
        return None, "conflicting seat identities: " + ", ".join(sorted(candidates))
    return next(iter(candidates)), None


# ------------------------------------------------------------------ Claude Code


def claude_sessions(root: Path, cwd: str, since: datetime | None, until: datetime | None,
                    seats: Iterable[str]) -> list[dict]:
    seats = tuple(seats)
    known = {seat.lower(): seat for seat in seats}
    slug = claude_slug(cwd)
    files: list[Path] = []
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            if folder.is_dir() and (folder.name == slug or folder.name.startswith(slug + "-")):
                files.extend(sorted(folder.glob("*.jsonl")))
                files.extend(sorted(folder.glob("*/subagents/*.jsonl")))
    sessions = []
    for path in files:
        names: set[str] = set()
        mandates: set[str] = set()
        responses: dict[str, dict] = {}
        synthetic = 0
        for number, record in read_jsonl(path):
            kind = record.get("type")
            if kind in ("agent-name", "custom-title"):
                value = record.get("agentName") if kind == "agent-name" else record.get("customTitle")
                if isinstance(value, str) and value.strip().lower() in known:
                    names.add(known[value.strip().lower()])
                continue
            if record.get("cwd") and not inside(record.get("cwd"), cwd):
                continue
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            if kind in ("user", "system"):
                mandates |= mandate_seats(_flatten(message.get("content", record.get("content"))), seats)
                continue
            if kind != "assistant":
                continue
            try:
                moment = parse_time(record.get("timestamp", ""))
            except (ValueError, AttributeError):
                continue
            if not within(moment, since, until):
                continue
            model = message.get("model") or "unknown"
            if model == "<synthetic>":
                synthetic += 1
                continue
            usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
            key = message.get("id") or record.get("requestId") or f"{path.name}:{number}"
            responses[key] = {"model": model, "time": moment, "raw": {
                field: int(usage.get(field) or 0) for field in
                ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}}
        if not responses:
            continue
        seat, reason = _attribution(names, mandates)
        models: dict[str, dict] = {}
        totals = _empty_tokens()
        for response in responses.values():
            raw = response["raw"]
            tokens = {"input": raw["input_tokens"], "cache_write": raw["cache_creation_input_tokens"],
                      "cached_input": raw["cache_read_input_tokens"], "output": raw["output_tokens"]}
            entry = models.setdefault(response["model"], {"turns": 0, **_empty_tokens()})
            entry["turns"] += 1
            _add(entry, tokens)
            _seen(entry, response["time"])
            _add(totals, tokens)
        times = [response["time"] for response in responses.values()]
        sessions.append({
            "provider": "claude", "file": str(path), "seat": seat, "unattributed_reason": reason,
            "identity_sources": {"agent_name": sorted(names), "mandate": sorted(mandates)},
            "first": iso(min(times)), "last": iso(max(times)), "models": models, "tokens": totals,
            "turn_unit": "assistant API response", "synthetic_skipped": synthetic,
        })
    return sessions


# ------------------------------------------------------------------ Codex


def _day_folders(root: Path, since: datetime | None, until: datetime | None) -> list[Path]:
    if since is None or until is None:
        return sorted(path for path in root.glob("*/*/*") if path.is_dir())
    # Folder dates are local; pad a day either side and let event times decide.
    day = (since - timedelta(days=1)).date()
    end = (until + timedelta(days=1)).date()
    folders = []
    while day <= end:
        folder = root / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        if folder.is_dir():
            folders.append(folder)
        day += timedelta(days=1)
    return folders


def _codex_usage(info: Any) -> dict | None:
    if not isinstance(info, dict) or not isinstance(info.get("total_token_usage"), dict):
        return None
    total = info["total_token_usage"]
    return {field: int(total.get(field) or 0) for field in
            ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")}


def codex_sessions(root: Path, cwd: str, since: datetime | None, until: datetime | None,
                   seats: Iterable[str], originator: str = "jam") -> list[dict]:
    seats = tuple(seats)
    sessions = []
    if not root.is_dir():
        return sessions
    for folder in _day_folders(root, since, until):
        for path in sorted(folder.glob("*.jsonl")):
            records = list(read_jsonl(path))
            if not records or records[0][1].get("type") != "session_meta":
                continue
            meta = records[0][1].get("payload") or {}
            if meta.get("originator") != originator or not inside(meta.get("cwd"), cwd):
                continue
            mandates = mandate_seats(_flatten(meta.get("base_instructions")), seats)
            model = None
            before = None            # last cumulative total before the window
            previous = None          # last cumulative total seen
            models: dict[str, dict] = {}
            turns: dict[str, int] = defaultdict(int)
            times = []
            for _, record in records[1:]:
                payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
                kind = record.get("type")
                if kind == "response_item" and payload.get("type") == "message" and payload.get("role") in ("developer", "system"):
                    mandates |= mandate_seats(_flatten(payload.get("content")), seats)
                    continue
                try:
                    moment = parse_time(record.get("timestamp", ""))
                except (ValueError, AttributeError):
                    moment = None
                if kind == "turn_context":
                    model = payload.get("model") or "unknown"
                    if within(moment, since, until):
                        turns[model] += 1
                        times.append(moment)
                        _seen(models.setdefault(model, {"turns": 0, **_empty_tokens(), "reasoning_output": 0}), moment)
                    continue
                if not (kind == "event_msg" and payload.get("type") == "token_count"):
                    continue
                usage = _codex_usage(payload.get("info"))
                if usage is None or moment is None:
                    continue
                if until is not None and moment > until:
                    continue
                if since is not None and moment < since:
                    before = previous = usage
                    continue
                times.append(moment)
                if previous is not None and all(usage[f] >= previous[f] for f in usage):
                    delta = {f: usage[f] - previous[f] for f in usage}
                else:        # first event, or the counter restarted: the whole total is new
                    delta = dict(usage)
                previous = usage
                if not any(delta.values()):
                    continue
                entry = models.setdefault(model or "unknown", {"turns": 0, **_empty_tokens(), "reasoning_output": 0})
                entry["input"] += delta["input_tokens"] - delta["cached_input_tokens"]
                entry["cached_input"] += delta["cached_input_tokens"]
                entry["output"] += delta["output_tokens"]
                entry["reasoning_output"] += delta["reasoning_output_tokens"]
                _seen(entry, moment)
            for name, count in turns.items():
                models.setdefault(name, {"turns": 0, **_empty_tokens(), "reasoning_output": 0})["turns"] = count
            if not models:
                continue
            totals = _empty_tokens()
            for entry in models.values():
                _add(totals, entry)
            seat, reason = _attribution(set(), mandates)
            sessions.append({
                "provider": "codex", "file": str(path), "seat": seat, "unattributed_reason": reason,
                "identity_sources": {"mandate": sorted(mandates)},
                "first": iso(min(times)) if times else None, "last": iso(max(times)) if times else None,
                "models": models, "tokens": totals, "turn_unit": "turn_context record",
                "cumulative_before_window": before, "cumulative_last_in_window": previous,
            })
    return sessions


# ------------------------------------------------------------------ report


def build_report(cwd: str, since: datetime | None, until: datetime | None, allow: Iterable[str],
                 claude_root: Path, codex_root: Path, seats: Iterable[str] = DEFAULT_SEATS,
                 originator: str = "jam") -> dict:
    seats = tuple(seats)
    allow = sorted(set(allow))
    sessions = (claude_sessions(claude_root, cwd, since, until, seats)
                + codex_sessions(codex_root, cwd, since, until, seats, originator))
    rows: dict[tuple[str, str], dict] = {}
    for session in sessions:
        key = (session["seat"] or "unattributed", session["provider"])
        row = rows.setdefault(key, {"seat": key[0], "provider": key[1], "models": {}, "sessions": 0,
                                    **_empty_tokens()})
        row["sessions"] += 1
        _add(row, session["tokens"])
        for model, data in session["models"].items():
            row["models"][model] = row["models"].get(model, 0) + data["turns"]
    order = {seat: index for index, seat in enumerate(seats)}
    table = sorted(rows.values(), key=lambda row: (order.get(row["seat"], len(order)), row["provider"]))
    flags = []
    for session in sessions:
        for model, data in sorted(session["models"].items()):
            if model not in allow:
                flags.append({"seat": session["seat"] or "unattributed", "provider": session["provider"],
                              "model": model, "turns": data["turns"],
                              "tokens": {field: data[field] for field in TOKEN_FIELDS},
                              "file": session["file"], "first": data.get("first"), "last": data.get("last")})
    totals = _empty_tokens()
    for row in table:
        _add(totals, row)
    return {
        "window": {"since": iso(since), "until": iso(until)}, "cwd": os.path.normpath(cwd),
        "allowed_models": allow, "seats": list(seats),
        "sources": {"claude_root": str(claude_root), "codex_root": str(codex_root), "codex_originator": originator},
        "table": table, "totals": totals,
        "off_allowlist": flags, "unattributed_sessions": sum(1 for s in sessions if s["seat"] is None),
        "sessions": sessions,
        "notes": ["input = uncached input; cache_write = Claude cache creation; cached_input = read from cache; "
                  "output includes reasoning tokens",
                  "Claude turns = assistant API responses (deduplicated by message id); "
                  "Codex turns = turn_context records in the window"],
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict) -> str:
    window = report["window"]
    lines = [f"# Seat usage, {window['since'] or 'start'} to {window['until'] or 'now'}", "",
             f"cwd `{report['cwd']}`; allowed models: {', '.join(report['allowed_models'])}", "",
             "| Seat | Provider | Models (turns) | Input | Cache write | Cached input | Output | Sessions |",
             "|---|---|---|---:|---:|---:|---:|---:|"]
    for row in report["table"]:
        models = ", ".join(f"{name} ({count})" + ("" if name in report["allowed_models"] else " ⚠")
                           for name, count in sorted(row["models"].items()))
        lines.append("| " + " | ".join(_cell(v) for v in (
            row["seat"], row["provider"], models, f"{row['input']:,}", f"{row['cache_write']:,}",
            f"{row['cached_input']:,}", f"{row['output']:,}", row["sessions"])) + " |")
    t = report["totals"]
    lines.append(f"| **Total** | | | {t['input']:,} | {t['cache_write']:,} | {t['cached_input']:,} | {t['output']:,} | "
                 f"{sum(row['sessions'] for row in report['table'])} |")
    lines += ["", f"Off-allowlist turns: {len(report['off_allowlist'])}"]
    for flag in report["off_allowlist"]:
        lines.append(f"- {flag['seat']} ({flag['provider']}): {flag['model']}, {flag['turns']} turns, "
                     f"output {flag['tokens']['output']:,}, {flag['first']} to {flag['last']}")
    lines.append(f"Unattributed sessions: {report['unattributed_sessions']}")
    for session in report["sessions"]:
        if session["seat"] is None:
            lines.append(f"- {session['provider']} `{Path(session['file']).name}`: {session['unattributed_reason']}")
    lines += ["", *("- " + note for note in report["notes"])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", help="window start, ISO time with zone (e.g. 2026-10-03T19:27Z)")
    parser.add_argument("--until", help="window end, ISO time with zone (default: no end)")
    parser.add_argument("--cwd", default="/Users/ashton/DarkFactory/band-work",
                        help="seats' working directory (sessions inside it count)")
    parser.add_argument("--allow-model", action="append", dest="allow",
                        help="allowed model id; repeatable (default: gpt-6.1-sol, claude-opus-5-5)")
    parser.add_argument("--seat", action="append", dest="seats", help="seat name; repeatable (default: the five seats)")
    parser.add_argument("--originator", default="jam", help="Codex session originator (default: jam)")
    parser.add_argument("--claude-root", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--format", choices=("json", "markdown", "both"), default="json")
    args = parser.parse_args(argv)
    try:
        since = parse_time(args.since) if args.since else None
        until = parse_time(args.until) if args.until else None
    except ValueError as exc:
        parser.error(str(exc))
    if since and until and until < since:
        parser.error("--until is before --since")
    report = build_report(args.cwd, since, until, args.allow or DEFAULT_ALLOW, args.claude_root.expanduser(),
                          args.codex_root.expanduser(), args.seats or DEFAULT_SEATS, args.originator)
    if args.format in ("json", "both"):
        print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.format in ("markdown", "both"):
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
