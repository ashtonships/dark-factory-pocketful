#!/usr/bin/env python3
"""Count full spec sentences, ledger quotes, and checker-authored check references."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

HEAD = re.compile(r"^(?:[-*] )?(?:\[(?:E-?)?(\d+)\]|(?:E-?)?(\d+)[.)])\s+(.+)$", re.I)
REF = re.compile(r"\b(?:ledger|entr(?:y|ies)|requirement(?:s)?)\s*[:#=-]\s*((?:(?:E-?)?\d+\s*[,;/ ]\s*)*(?:E-?)?\d+)", re.I)
MARKER = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
FENCE = re.compile(r"^(`{3,}|~{3,})")


@dataclass
class Evidence:
    references: dict[int, set[str]]
    kind: str


def source_files(folder: Path):
    return sorted(p for p in folder.rglob("*") if p.is_file()
                  and p.suffix.lower() in {".md", ".txt"}
                  and not any(x.startswith(".") for x in p.relative_to(folder).parts))


def split_sentences(text: str):
    start = 0
    for boundary in re.finditer(r"(?<=[.!?])\s+(?=\S)", text):
        yield text[start:boundary.start()].strip(), start
        start = boundary.end()
    yield text[start:].strip(), start


def obligations(folder: Path):
    found = []
    for path in source_files(folder):
        paragraph, start = [], 0
        fence_char, fence_len = "", 0
        table_body = False

        def emit(value, line, row=False):
            parts = [(value, 0)] if row else split_sentences(value)
            for sentence, offset in parts:
                sentence = re.sub(r"\s+", " ", sentence).strip()
                if sentence:
                    found.append({"file": str(path.relative_to(folder)),
                                  "line": line + value.count("\n", 0, offset), "text": sentence})

        def flush():
            nonlocal paragraph
            if paragraph:
                emit("\n".join(paragraph), start)
                paragraph = []

        for line_no, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = raw.strip()
            fence = FENCE.match(line)
            if fence:
                flush()
                if not fence_char:
                    fence_char, fence_len = fence.group(1)[0], len(fence.group(1))
                elif fence.group(1)[0] == fence_char and len(fence.group(1)) >= fence_len:
                    fence_char, fence_len = "", 0
                continue
            if fence_char:
                continue
            if not line or line.startswith("#"):
                flush()
                table_body = False
                continue
            if line.startswith("|"):
                flush()
                if re.fullmatch(r"[|\s:-]+", line):
                    table_body = True
                elif table_body:
                    emit(" | ".join(c.strip() for c in line.strip("|").split("|")), line_no, True)
                continue
            table_body = False
            marker = MARKER.match(line)
            if marker:
                flush()
                emit(line[marker.end():], line_no)
                continue
            if not paragraph:
                start = line_no
            paragraph.append(line)
        flush()
    return found


def _quote(body: str):
    openings = [(body.find(mark), mark, close) for mark, close in (("\"", "\""), ("“", "”"))]
    for start, opening, closing in sorted(openings):
        if start >= 0:
            end = body.rfind(closing)
            if end > start:
                return body[start + 1:end].strip(), body[end + 1:].strip()
    for line in body.splitlines():
        if line.lstrip().startswith("> "):
            return line.lstrip()[2:].strip(), ""
    return "", ""


def ledger_entries(path: Path):
    entries, waivers, current = [], [], None

    def finish():
        if not current:
            return
        quote, tail = _quote(current.pop("body"))
        current["quote"] = quote
        if current.pop("waiver"):
            current["reason"] = tail.lstrip("—–-: ").strip()
            if not quote or not current["reason"]:
                raise ValueError("N/A waiver requires a quote and a reason")
            waivers.append(current)
        else:
            entries.append(current)

    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        head = HEAD.match(line)
        waiver = re.match(r"^N/A:\s*(.+)$", line, re.I)
        if head or waiver:
            finish()
            current = {"line": line_no, "body": waiver.group(1) if waiver else head.group(3),
                       "waiver": bool(waiver)}
            if head:
                current["id"] = int(head.group(1) or head.group(2))
        elif current and line.strip() and not line.lstrip().startswith("#"):
            current["body"] += "\n" + line
    finish()
    ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("ledger entry ids must be unique")
    return entries, waivers


def normalize(value: str):
    value = re.sub(r"(?m)^\s*>\s?", "", value)
    return " ".join(value.casefold().replace("`", "").replace("*", "").split())


def _span(obligation: str, quote: str):
    quote = normalize(quote)
    if not quote:
        return None
    if obligation in quote:
        return (0, len(obligation))
    start = obligation.find(quote)
    return (start, start + len(quote)) if start >= 0 else None


def _fully_quoted(obligation: str, quotes: list[str]):
    value = normalize(obligation)
    covered = [False] * len(value)
    for quote in quotes:
        span = _span(value, quote)
        if span:
            for i in range(*span):
                covered[i] = True
    return bool(value) and all(not c.isalnum() or covered[i] for i, c in enumerate(value))


def _test_source(path: Path):
    name = path.name.lower()
    return (name.startswith("test_") or "_test." in name or ".test." in name
            or ".spec." in name or name.endswith("test.java"))


def _checker_authored(path: Path, root: Path):
    try:
        relative = str(path.resolve().relative_to(root))
    except ValueError:
        return False
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", relative],
                            capture_output=True, text=True, check=False)
    if status.returncode or status.stdout.strip():
        return False
    log = subprocess.run(["git", "-C", str(root), "log", "--follow", "--format=%an%x09%ae", "--", relative],
                         capture_output=True, text=True, check=False)
    authors = [line.split("\t", 1) for line in log.stdout.splitlines()]
    return (log.returncode == 0 and bool(authors)
            and all(a == ["Checker", "checker@factory.invalid"] for a in authors))


def evidence_from_checks(folder: Path):
    refs = defaultdict(set)
    git_root = subprocess.run(["git", "-C", str(folder), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=False)
    if git_root.returncode:
        return Evidence(refs, "checker")
    root = Path(git_root.stdout.strip()).resolve()
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.is_symlink() or not _test_source(path):
            continue
        if any(x.startswith(".") for x in path.relative_to(folder).parts):
            continue
        if not _checker_authored(path, root):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        for line in content.splitlines():
            if re.search(r"\b(?:TODO|FIXME|planned|not written)\b", line, re.I):
                continue
            for match in REF.finditer(line):
                for number in re.findall(r"\d+", match.group(1)):
                    refs[int(number)].add(str(path.relative_to(folder)))
    return Evidence(refs, "checker")


def evidence_from_csv(path: Path):
    refs = defaultdict(set)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "check" not in reader.fieldnames or not ({"entry_id", "entry_ids"} & set(reader.fieldnames)):
            raise ValueError("CSV requires check and entry_id or entry_ids columns")
        for row in reader:
            check = (row.get("check") or "").strip()
            ids = row.get("entry_id") or row.get("entry_ids") or ""
            if check:
                for number in re.findall(r"\d+", ids):
                    refs[int(number)].add(check)
    return Evidence(refs, "csv_assertion")


def _measure(covered, total):
    return {"covered": covered, "total": total, "ratio": covered / total if total else 0}


def build_report(spec: Path, ledger: Path, evidence: Evidence):
    obs = obligations(spec)
    entries, waivers = ledger_entries(ledger)
    checked = evidence.references if evidence.kind == "checker" else {}
    claimed = evidence.references if evidence.kind == "csv_assertion" else {}
    for entry in entries:
        entry["checker_authored_check_references"] = sorted(checked.get(entry["id"], []))
        entry["csv_asserted_references"] = sorted(claimed.get(entry["id"], []))
    ledgered = waived = referenced_obligations = 0
    for ob in obs:
        ob["entries"] = [e["id"] for e in entries if _span(normalize(ob["text"]), e["quote"])]
        ob["waivers"] = [w["line"] for w in waivers if _fully_quoted(ob["text"], [w["quote"]])]
        ob["ledgered"] = _fully_quoted(ob["text"], [e["quote"] for e in entries])
        ob["waived"] = bool(ob["waivers"]) and not ob["ledgered"]
        ob["checker_authored_check_reference"] = (ob["ledgered"] and _fully_quoted(ob["text"],
            [e["quote"] for e in entries if e["checker_authored_check_references"]]))
        ledgered += ob["ledgered"]
        waived += ob["waived"]
        referenced_obligations += ob["checker_authored_check_reference"]
    return {
        "ledger_completeness": {**_measure(ledgered + waived, len(obs)), "ledgered": ledgered, "waived": waived},
        "checker_authored_check_reference_coverage": _measure(sum(bool(e["checker_authored_check_references"]) for e in entries), len(entries)),
        "obligation_checker_authored_check_reference_coverage": _measure(referenced_obligations, len(obs)),
        "csv_asserted_reference_coverage": _measure(sum(bool(e["csv_asserted_references"]) for e in entries), len(entries)),
        "uncovered_obligations": [ob for ob in obs if not ob["ledgered"] and not ob["waived"]],
        "obligations": obs, "ledger_entries": entries, "waivers": waivers,
    }


def markdown(report):
    rows = [
        ("Ledger completeness (entries + waivers)", report["ledger_completeness"]),
        ("Checker-authored check-reference coverage of entries", report["checker_authored_check_reference_coverage"]),
        ("Obligations with checker-authored check references", report["obligation_checker_authored_check_reference_coverage"]),
        ("CSV-asserted references (unverified)", report["csv_asserted_reference_coverage"]),
    ]
    return "\n".join(["| Measure | Covered | Total | Rate |", "|---|---:|---:|---:|"] +
                     [f"| {label} | {v['covered']} | {v['total']} | {v['ratio']:.0%} |" for label, v in rows])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--checks", type=Path)
    source.add_argument("--evidence-csv", type=Path)
    parser.add_argument("--format", choices=("json", "markdown", "both"), default="both")
    args = parser.parse_args(argv)
    if not args.spec.is_dir() or not args.ledger.is_file():
        parser.error("--spec must be a folder and --ledger must be a file")
    if args.checks and not args.checks.is_dir():
        parser.error("--checks must be a folder")
    if args.evidence_csv and not args.evidence_csv.is_file():
        parser.error("--evidence-csv must be a file")
    try:
        evidence = evidence_from_checks(args.checks) if args.checks else evidence_from_csv(args.evidence_csv)
        report = build_report(args.spec, args.ledger, evidence)
    except ValueError as exc:
        parser.error(str(exc))
    if args.format in ("json", "both"):
        print(json.dumps(report, indent=2))
    if args.format in ("markdown", "both"):
        print(markdown(report))


if __name__ == "__main__":
    main()
