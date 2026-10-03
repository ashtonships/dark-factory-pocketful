#!/usr/bin/env python3
"""Measure a saved Band room without changing its input."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


MESSAGE_TYPES = ("text", "thought", "tool_call", "tool_result", "error")


class MessageList(list[dict]):
    """A normal list that also retains source filenames for empty input files."""

    def __init__(self, records: Iterable[dict], source_files: Iterable[str]):
        super().__init__(records)
        self.source_files = list(dict.fromkeys(source_files))


def parse_time(value: str) -> datetime:
    """Parse an ISO 8601 timestamp with an explicit timezone, for comparisons."""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid ISO 8601 time: {value!r}") from exc
    if stamp.tzinfo is None:
        raise ValueError(f"time has no timezone: {value!r}")
    return stamp.astimezone(timezone.utc)


def _field(record: dict, snake: str, camel: str, default: Any = "") -> Any:
    return record.get(snake, record.get(camel, default))


def _normalise(record: dict) -> dict:
    if not isinstance(record, dict):
        raise ValueError("each room record must be an object")
    record_id = record.get("id")
    if not isinstance(record_id, (str, int)) or isinstance(record_id, bool):
        raise ValueError("each room record needs an id")
    stamp = _field(record, "time", "insertedAt", None)
    if stamp is None:
        stamp = record.get("inserted_at")
    parse_time(stamp)
    seat_type = str(_field(record, "sender_type", "senderType")).casefold()
    return {
        "id": str(record_id), "time": stamp,
        "sender_id": str(_field(record, "sender_id", "senderId")),
        "sender_name": str(_field(record, "sender_name", "senderName")),
        "sender_type": "agent" if seat_type == "agent" else "human",
        "message_type": str(_field(record, "message_type", "messageType")).casefold(),
        "content": record.get("content", ""),
        "tool_name": str(_field(record, "tool_name", "toolName")),
        "source_files": list(record.get("source_files", [])),
    }


def normalise_messages(records: Iterable[dict]) -> list[dict]:
    """Keep the first occurrence of an id and sort by time, then id."""
    unique: dict[str, dict] = {}
    for raw in records:
        record = _normalise(raw)
        previous = unique.get(record["id"])
        if previous is None:
            unique[record["id"]] = record
        else:
            for source in record["source_files"]:
                if source not in previous["source_files"]:
                    previous["source_files"].append(source)
    return sorted(unique.values(), key=lambda item: (parse_time(item["time"]), item["id"]))


def _unwrap(document: Any) -> Iterable[dict]:
    if isinstance(document, list):
        for item in document:
            yield from _unwrap(item)
    elif isinstance(document, dict) and "messages" in document:
        if not isinstance(document["messages"], list):
            raise ValueError("room 'messages' must be a list")
        for item in document["messages"]:
            if not isinstance(item, dict) or "id" not in item:
                raise ValueError("each room record must be an object with an id")
            yield item
    elif isinstance(document, dict) and "id" in document:
        yield document
    else:
        raise ValueError("expected a room object, a list of pages, or a list of records")


def load_messages(paths: Iterable[str | Path]) -> list[dict]:
    """Read full-session files, CLI pages or record arrays, deduplicated by id."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    paths = [Path(path) for path in paths]
    records = []
    for supplied in paths:
        path = Path(supplied)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            for raw in _unwrap(document):
                records.append({**raw, "source_files": [str(path)]})
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"cannot read room {path}: {exc}") from exc
    return MessageList(normalise_messages(records), map(str, paths))


def _decode(value: Any) -> Any:
    while isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            break
        if decoded == value:
            break
        value = decoded
    return value


def _strings(value: Any) -> Iterable[str]:
    value = _decode(value)
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def tool_arguments(record: dict) -> tuple[str, list[str]]:
    """Decode nested argument strings; tool names and argument keys are excluded."""
    payload = _decode(record["content"])
    tool = record["tool_name"]
    if isinstance(payload, dict):
        tool = tool or str(payload.get("name", ""))
        arguments = payload.get("args", {})
    else:
        arguments = payload
    return tool, list(_strings(arguments))


def _path(value: str) -> str:
    collapsed = re.sub(r"/+", "/", value)
    return collapsed.rstrip("/") or "/"


def _patterns(forbidden: Iterable[str], forbidden_regex: Iterable[str]):
    supplied = [str(path) for path in forbidden]
    if any(not path.startswith("/") for path in supplied):
        raise ValueError("--forbidden must be an absolute directory path")
    paths = list(dict.fromkeys(_path(path) for path in supplied))
    regexes = list(dict.fromkeys(forbidden_regex))
    try:
        compiled = [re.compile(pattern) for pattern in regexes]
    except re.error as exc:
        raise ValueError(f"invalid forbidden regex: {exc}") from exc
    return paths, regexes, compiled


def _matches(values: Iterable[str], paths: list[str], regexes: list) -> list[str]:
    matches = []
    for value in values:
        collapsed = re.sub(r"/+", "/", value)
        for path in paths:
            aliases = [path]
            if re.match(r"^/Users/[^/]+(?:/|$)", path):
                aliases.append(re.sub(r"^/Users/[^/]+", "~", path, count=1))
            if any(collapsed == alias or
                   (alias + "/" if alias != "/" else "/") in collapsed
                   for alias in aliases):
                if path not in matches:
                    matches.append(path)
        for pattern in regexes:
            for match in pattern.finditer(value):
                found = match.group(0)
                if found not in matches:
                    matches.append(found)
    return matches


def content_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def seat_identity(record: dict) -> tuple[str, str]:
    return record["sender_name"], record["sender_type"]


def _dispatch(record: dict) -> dict:
    return {"id": record["id"], "time": record["time"], "sender": record["sender_name"]}


def _human_evidence(record: dict) -> dict:
    return {**_dispatch(record), "type": record["message_type"],
            "excerpt": content_text(record["content"])[:120]}


def _dispatch_rows(dispatch: dict | None) -> list:
    return [[dispatch["id"], dispatch["time"], dispatch["sender"]]] if dispatch else [[None, None, None]]


def _human_rows(items: Iterable[dict]) -> Iterable[list]:
    for item in items:
        yield [item["id"], item["time"], item["sender"], item["type"], item["excerpt"]]


def audit(messages: Iterable[dict], forbidden: Iterable[str] = (),
          forbidden_regex: Iterable[str] = (), builders: Iterable[str] | None = None) -> dict:
    """Count recorded evidence. Empty forbidden paths are allowed for API callers."""
    ordered = normalise_messages(messages)
    paths, regexes, compiled = _patterns(forbidden or (), forbidden_regex or ())
    builder_names = set(builders) if builders else None
    seats: dict[str, dict] = {}
    reads = []
    humans = []
    dispatch = None
    files = list(getattr(messages, "source_files", []))
    for record in ordered:
        for source in record["source_files"]:
            if source not in files:
                files.append(source)
        seat, seat_type = seat_identity(record)
        kind = record["message_type"]
        totals = seats.setdefault(seat, {"type": seat_type,
                                       "counts": dict.fromkeys(MESSAGE_TYPES, 0)})
        if totals["type"] != seat_type:
            totals["type"] = "mixed"
        totals["counts"][kind] = totals["counts"].get(kind, 0) + 1
        if seat_type != "agent":
            if dispatch is None:
                dispatch = _dispatch(record)
            else:
                humans.append(_human_evidence(record))
        is_builder = seat in builder_names if builder_names is not None else "builder" in seat.casefold()
        if seat_type == "agent" and is_builder and kind == "tool_call":
            tool, values = tool_arguments(record)
            matches = _matches(values, paths, compiled)
            if matches:
                reads.append({"id": record["id"], "time": record["time"],
                              "seat": seat, "tool": tool, "matches": matches})
    return {
        "input": {"files": files, "message_count": len(ordered),
                  "first_time": ordered[0]["time"] if ordered else None,
                  "last_time": ordered[-1]["time"] if ordered else None},
        "dispatch": dispatch,
        "seats": dict(sorted(seats.items())),
        "builder_test_reads": {"count": len(reads), "items": reads},
        "human_messages_after_dispatch": {"count": len(humans), "items": humans},
        "forbidden": {"paths": paths, "regex": regexes},
    }


def markdown_cell(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def markdown_table(headers: Iterable[str], rows: Iterable[Iterable[Any]]) -> str:
    headers = list(headers)
    lines = ["| " + " | ".join(map(markdown_cell, headers)) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(map(markdown_cell, row)) + " |" for row in rows)
    return "\n".join(lines)


def render_markdown(report: dict) -> str:
    source = report["input"]
    counts = list(MESSAGE_TYPES)
    counts += sorted({kind for seat in report["seats"].values() for kind in seat["counts"]}
                     - set(counts))
    sections = [
        "# Room audit",
        "## Input\n\n" + markdown_table(
            ["Files", "Messages", "First time", "Last time"],
            [[", ".join(source["files"]), source["message_count"], source["first_time"], source["last_time"]]]),
        "## Dispatch\n\n" + markdown_table(["Id", "Time", "Sender"], _dispatch_rows(report["dispatch"])),
        "## Seats\n\n" + markdown_table(["Seat", "Type", *counts],
            ([name, seat["type"], *(seat["counts"].get(kind, 0) for kind in counts)]
             for name, seat in report["seats"].items())),
        f"## Builder test reads: {report['builder_test_reads']['count']}\n\n" + markdown_table(
            ["Id", "Time", "Seat", "Tool", "Matching paths"],
            ([item["id"], item["time"], item["seat"], item["tool"], ", ".join(item["matches"])]
             for item in report["builder_test_reads"]["items"])),
        f"## Human messages after dispatch: {report['human_messages_after_dispatch']['count']}\n\n" + markdown_table(
            ["Id", "Time", "Sender", "Type", "Excerpt"], _human_rows(report["human_messages_after_dispatch"]["items"])),
        "## Forbidden patterns\n\n" + markdown_table(["Kind", "Pattern"],
            ([kind, value] for kind, values in report["forbidden"].items() for value in values)),
    ]
    return "\n\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="saved room JSON files or CLI pages")
    parser.add_argument("--forbidden", action="append", required=True, help="absolute shipped-test directory")
    parser.add_argument("--forbidden-regex", action="append", default=[], help="additional path regex")
    parser.add_argument("--builder", action="append", help="builder seat display name (repeatable)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--fail-on-reads", action="store_true")
    parser.add_argument("--fail-on-human", action="store_true")
    options = parser.parse_args(argv)
    try:
        report = audit(load_messages(options.paths), options.forbidden,
                       options.forbidden_regex, options.builder)
        report["input"]["files"] = list(dict.fromkeys(str(path) for path in options.paths))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        print(f"room_audit: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if options.format == "json"
          else render_markdown(report), end="\n" if options.format == "json" else "")
    return int((options.fail_on_reads and report["builder_test_reads"]["count"] > 0) or
               (options.fail_on_human and report["human_messages_after_dispatch"]["count"] > 0))


if __name__ == "__main__":
    raise SystemExit(main())
