#!/usr/bin/env python3
"""Flag test-only tokens that also appear in shipped product files.

This is a review aid: a match is a possible instance of test fitting, not proof.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


IDENTIFIER = re.compile(r"(?<![\w])(?:[A-Za-z_][A-Za-z_0-9]*)(?![\w])")
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
ROUTE = re.compile(r"(?<![<\w/])/(?:[A-Za-z_0-9{}:.-]+/?)+")
QUOTED = re.compile(r'''(?P<quote>["'`])(?P<value>(?:\\.|(?!\1).)*?)(?P=quote)''')

# Includes code syntax across common languages and test vocabulary. Filtering is
# deliberately conservative: an unknown identifier is kept for human review.
COMMON = set("""
a an and are as at be been by can do does for from has have if in into is it
its of on or our out per should that the their then there these this to under
using was were when where which while with without would you your true false
file files folder folders spec specification harness well
null none nil undefined class const def else elif end enum except export extends
finally fn function go import include interface let match module new package private
protected public return static struct super switch throw try type var void yield
async await break case catch continue default delete do double float int integer
long short string bool boolean number object dict list map set self this print
raise pass lambda not and or in is for while from as assert require expect test
tests testing pytest unittest fixture fixtures parametrize monkeypatch mock stub
response request result expected actual status code value values data body json
http get post put patch head options path url api client server app main read write
open close equal equals size length count index item items first second third
ok error success fail failed valid invalid empty content headers header text
testid testname setup teardown describe it should fixture sample assertstatus
classname node document window console process promise array math
""".split())
COMMON_NUMBERS = {"0", "1", "2", "3", "4", "5", "10", "100", "200", "201", "204", "400", "401", "403", "404", "500"}
SKIP_PARTS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv"}
SYSTEM_ROUTE_ROOTS = {"usr", "bin", "dev", "etc", "tmp"}
IMPORT_LINE = re.compile(r"^\s*(?:import\b|from\b|.*\brequire\s*\()")
BRANCH_OR_COMPARISON = re.compile(r"\b(?:if|elif|while|case|switch)\b|===?|!==?|<=?|>=?|\?")


def text_files(folder: Path):
    if not folder.is_dir():
        raise ValueError(f"not a directory: {folder}")
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.is_symlink() or any(part in SKIP_PARTS or part.startswith(".") for part in path.relative_to(folder).parts):
            continue
        try:
            raw = path.read_bytes()
            if b"\0" not in raw:
                yield path, raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue


def tokens(source: str):
    """Yield (kind, normalized value, original value) from arbitrary source text."""
    quoted_spans = []
    for match in QUOTED.finditer(source):
        quoted_spans.append((match.start(), match.end()))
        value = match.group("value")
        # A CSS class in JSX/HTML is presentation syntax, not a test fixture.
        before = source[max(0, match.start() - 32):match.start()]
        class_attribute = re.search(r"\bclass(?:Name)?\s*=\s*$", before, re.IGNORECASE)
        if (len(value.strip()) >= 2 and not value.isspace()
                and not class_attribute
                and not ROUTE.fullmatch(value) and value.casefold() not in COMMON):
            yield "literal", value.casefold(), value
    for match in ROUTE.finditer(source):
        if source[max(0, match.start() - 2):match.start()] == "#!":
            continue
        value = match.group().rstrip("/")
        if len(value) > 1 and value[1:].split("/", 1)[0].casefold() not in SYSTEM_ROUTE_ROOTS:
            yield "route", value.casefold(), value
    for match in IDENTIFIER.finditer(source):
        if any(start <= match.start() < end for start, end in quoted_spans):
            continue
        value = match.group()
        if len(value) >= 4 and value.casefold() not in COMMON and not value.startswith("__"):
            yield "identifier", value.casefold(), value
    for match in NUMBER.finditer(source):
        if any(start <= match.start() < end for start, end in quoted_spans):
            continue
        value = match.group()
        if value not in COMMON_NUMBERS:
            yield "number", value, value


def _matches(kind: str, value: str, line: str) -> bool:
    escaped = re.escape(value)
    if kind in {"identifier", "number"}:
        pattern = rf"(?<![\w.]){escaped}(?!\w|\.\d)"
    elif kind == "route":
        pattern = rf"(?<![<\w/]){escaped}(?![\w/])"
    else:
        pattern = escaped
    return re.search(pattern, line, re.IGNORECASE) is not None


def _severity(kind: str, value: str, line: str) -> str:
    if kind == "route" or (kind in {"number", "literal"} and BRANCH_OR_COMPARISON.search(line)):
        return "high"
    if kind == "literal" and (" " in value or len(value) >= 12):
        return "high"
    if kind == "literal" or (kind == "number" and len(value) >= 3):
        return "medium"
    return "low"


def _product_import_tokens(product_files: list[tuple[Path, str]]) -> set[tuple[str, str]]:
    """Names on the product's import lines are ordinary dependencies, not fixture clues."""
    imported = set()
    for _, body in product_files:
        for line in body.splitlines():
            if IMPORT_LINE.search(line):
                imported.update((kind, normalized) for kind, normalized, _ in tokens(line))
    return imported


def scan(spec_folder: Path, test_folder: Path, product_folder: Path) -> dict:
    """Return distinct candidate count and located possible test-fitting matches."""
    spec_files = list(text_files(spec_folder))
    test_files = list(text_files(test_folder))
    product_files = list(text_files(product_folder))
    imported = _product_import_tokens(product_files)
    spec_text = "\n".join(body for _, body in spec_files).casefold()
    candidates = defaultdict(set)
    for path, body in test_files:
        for kind, normalized, original in tokens(body):
            # Presence anywhere in the spec is enough to remove a candidate. For
            # identifiers and numbers, use token boundaries so 12 != 123.
            if (kind, normalized) in imported or _matches(kind, original, spec_text):
                continue
            candidates[(kind, normalized)].add(path.relative_to(test_folder).as_posix())

    by_kind = {kind: set() for kind in ("identifier", "number", "route", "literal")}
    for kind, normalized in candidates:
        by_kind[kind].add(normalized)
    # One alternation replaces one regex search per literal per product line.
    literal_pattern = (re.compile("(?=(" + "|".join(re.escape(value) for value in
                           sorted(by_kind["literal"], key=lambda value: (-len(value), value))) + "))", re.IGNORECASE)
                       if by_kind["literal"] else None)
    findings = []
    for path, body in product_files:
        relative = path.relative_to(product_folder).as_posix()
        for line_number, line in enumerate(body.splitlines(), 1):
            present = set()
            present.update(("identifier", match.group().casefold()) for match in IDENTIFIER.finditer(line))
            present.update(("number", match.group()) for match in NUMBER.finditer(line))
            present.update(("route", normalized) for kind, normalized, _ in tokens(line) if kind == "route")
            if literal_pattern:
                # Lookahead finds overlapping starts. Check prefixes of the longest
                # match so shorter candidates at the same start are not hidden.
                for match in literal_pattern.finditer(line):
                    value = match.group(1).casefold()
                    present.update(("literal", value[:end]) for end in range(1, len(value) + 1)
                                   if value[:end] in by_kind["literal"])
            for kind, normalized in present & candidates.keys():
                findings.append({
                    "file": relative,
                    "line": line_number,
                    "token": normalized,
                    "kind": kind,
                    "severity": _severity(kind, normalized, line),
                    "test_sources": sorted(candidates[(kind, normalized)]),
                })
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda item: (severity_rank[item["severity"]], item["file"], item["line"], item["kind"], item["token"]))
    return {
        "candidate_count": len(candidates),
        "finding_count": len(findings),
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="Specification folder")
    parser.add_argument("--tests", type=Path, required=True, help="Shipped-test folder")
    parser.add_argument("--product", type=Path, required=True, help="Product-code folder")
    args = parser.parse_args(argv)
    try:
        report = scan(args.spec, args.tests, args.product)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
