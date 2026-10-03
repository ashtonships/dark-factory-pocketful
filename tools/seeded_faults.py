#!/usr/bin/env python3
"""Measure whether a test command catches small, independent product faults.

This is a mutation *sample*, not proof that the whole specification is tested.
The unmodified copy must pass before any mutant is scored.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import fnmatch
import json
import os
from pathlib import Path
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass


SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".java", ".go", ".rs", ".c", ".cc", ".cpp", ".cs", ".php", ".rb", ".sh", ".swift", ".kt"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "coverage"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "e2e"}
TEST_NAMES = ("*.test.*", "*.spec.*", "*_test.*", "test_*", "*Test.*", "*_spec.*", "conftest.py")
COMPARISON_FLIPS = {"===": "!==", "!==": "===", "==": "!=", "!=": "==", "<=": ">", ">=": "<", "<": ">=", ">": "<="}
COMPARE_RE = re.compile(r"(?<![<>=!])(?:===|!==|==|!=|<=|>=|<|>)(?!=)")
NUMBER_RE = re.compile(r"(?<![\w.])\d+(?![\w.])")
RETURN_BOOL_RE = re.compile(r"\breturn\s+(True|False|true|false)\b")
DUPLICATE_RE = re.compile(r"duplicate|idempoten|already|exists|\bseen\b|\bby_\w+\b", re.I)
STATUS_RE = re.compile(r"\b(?:status|status_code|statusCode|http_status|httpStatus|response_code)\b", re.I)


@dataclass(frozen=True)
class Mutation:
    path: str
    start: int
    end: int
    replacement: str
    kind: str
    line: int


def _offsets(source: str) -> list[int]:
    starts = [0]
    for match in re.finditer("\n", source):
        starts.append(match.end())
    return starts


def _at(starts: list[int], line: int, column: int) -> int:
    return starts[line - 1] + column


def _at_ast(source: str, starts: list[int], line: int, byte_column: int) -> int:
    """AST columns are UTF-8 bytes; source offsets and tokenize columns are characters."""
    line_text = source[starts[line - 1]:].split("\n", 1)[0]
    return starts[line - 1] + len(line_text.encode("utf-8")[:byte_column].decode("utf-8"))


def _python_mask(source: str) -> str:
    """Keep offsets while blanking comments and literals for lexical mutations."""
    import io
    import tokenize

    chars = list(source)
    starts = _offsets(source)
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.STRING, tokenize.COMMENT, getattr(tokenize, "FSTRING_MIDDLE", -1)):
                for index in range(_at(starts, *token.start), _at(starts, *token.end)):
                    if chars[index] != "\n":
                        chars[index] = " "
    except tokenize.TokenError:
        return ""  # An unparseable source file is not a safe mutation target.
    return "".join(chars)


def _c_mask(source: str, suffix: str) -> str:
    """Blank C-family quoted strings and comments, preserving character positions."""
    chars = list(source)
    comments = r"//[^\n]*|/\*[\s\S]*?\*/"
    if suffix in {".rb", ".php", ".sh"}:
        comments += r"|\#[^\n]*"
    pattern = re.compile(comments + r"|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")
    for match in pattern.finditer(source):
        for index in range(*match.span()):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _python_structural(source: str, relative: str) -> list[Mutation]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    starts = _offsets(source)
    found: list[Mutation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_start = _at_ast(source, starts, node.test.lineno, node.test.col_offset)
        test_end = _at_ast(source, starts, node.test.end_lineno, node.test.end_col_offset)
        test = source[test_start:test_end]
        if STATUS_RE.search(test) and re.search(r"==|!=|<=|>=|<|>", test):
            found.append(Mutation(relative, test_start, test_end, "False", "drop_status_check", node.lineno))
        if DUPLICATE_RE.search(test):
            found.append(Mutation(relative, test_start, test_end, "False", "remove_duplicate_check", node.lineno))
        # Swapping the bodies preserves their own indentation. Exclude elif chains.
        if node.body and node.orelse and not (isinstance(node.orelse[0], ast.If) and node.orelse[0].col_offset == node.col_offset):
            body_start = _at_ast(source, starts, node.body[0].lineno, node.body[0].col_offset)
            body_end = _at_ast(source, starts, node.body[-1].end_lineno, node.body[-1].end_col_offset)
            else_start = _at_ast(source, starts, node.orelse[0].lineno, node.orelse[0].col_offset)
            else_end = _at_ast(source, starts, node.orelse[-1].end_lineno, node.orelse[-1].end_col_offset)
            # Whole-line replacement includes indentation and avoids needing two edits.
            line_body = starts[node.body[0].lineno - 1]
            line_else = starts[node.orelse[0].lineno - 1]
            if source[line_body:body_start].strip() or source[line_else:else_start].strip():
                continue
            body_text = source[line_body:body_end]
            else_text = source[line_else:else_end]
            middle = source[body_end:line_else]
            # The middle contains the else header. Keep it in place.
            if re.search(r"\belse\s*:\s*$", middle):
                found.append(Mutation(relative, line_body, else_end,
                                      else_text + middle + body_text.lstrip("\n"),
                                      "swap_branches", node.lineno))
    return found


def mutations_for_file(path: Path, relative: str) -> list[Mutation]:
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeError, OSError):
        return []
    if not source or len(source) > 1_000_000:
        return []
    mask = _python_mask(source) if path.suffix == ".py" else _c_mask(source, path.suffix)
    if not mask:
        return []
    found = _python_structural(source, relative) if path.suffix == ".py" else []
    if path.suffix != ".py":
        # A deliberately narrow C-family pattern: single-line conditions only.
        # More complex conditions are left for the comparison/numeric operators.
        for match in re.finditer(r"\bif\s*\(\s*([^()\n]+?)\s*\)", mask):
            test = match.group(1)
            kind = ("drop_status_check" if STATUS_RE.search(test) else
                    "remove_duplicate_check" if DUPLICATE_RE.search(test) else None)
            if kind:
                replacement = "(0)" if path.suffix in {".c", ".cc", ".cpp"} else "false"
                found.append(Mutation(relative, match.start(1), match.end(1), replacement,
                                      kind, source.count("\n", 0, match.start()) + 1))
    for match in COMPARE_RE.finditer(mask):
        operator = match.group()
        if operator in {"<", ">"} and path.suffix != ".py":
            # Bare angle brackets are often generic parameters or markup.
            if not (match.start() > 0 and mask[match.start() - 1].isspace()
                    and match.end() < len(mask) and mask[match.end()].isspace()):
                continue
        found.append(Mutation(relative, *match.span(), COMPARISON_FLIPS[operator], "flip_comparison", source.count("\n", 0, match.start()) + 1))
    for match in NUMBER_RE.finditer(mask):
        value = match.group()
        if len(value) > 1 and value.startswith("0"):
            continue
        found.append(Mutation(relative, *match.span(), str(int(value) + 1), "off_by_one", source.count("\n", 0, match.start()) + 1))
    for match in RETURN_BOOL_RE.finditer(mask):
        value = match.group(1)
        flipped = {"True": "False", "False": "True", "true": "false", "false": "true"}[value]
        found.append(Mutation(relative, match.start(1), match.end(1), flipped, "invert_boolean_return", source.count("\n", 0, match.start()) + 1))
    return found


def _excluded(relative: Path, globs: list[str]) -> bool:
    name = relative.name
    return (bool(TEST_DIRS.intersection(relative.parts[:-1]))
            or any(fnmatch.fnmatchcase(name, pattern) for pattern in TEST_NAMES)
            or any(fnmatch.fnmatchcase(relative.as_posix(), pattern)
                   or fnmatch.fnmatchcase(name, pattern) for pattern in globs))


def _check_link(path: Path, product: Path) -> None:
    if path.is_symlink() and not path.resolve().is_relative_to(product.resolve()):
        raise ValueError(f"symlink resolves outside product folder: {path}")


def collect_mutations(product: Path, exclude: list[str] | None = None) -> list[Mutation]:
    found: list[Mutation] = []
    exclude = exclude or []
    for directory, dirs, files in os.walk(product, followlinks=False):
        relative_dir = Path(directory).relative_to(product)
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS
                         and name not in TEST_DIRS
                         and not any(fnmatch.fnmatchcase((relative_dir / name).as_posix(), pattern)
                                     or fnmatch.fnmatchcase(name, pattern) for pattern in exclude))
        for name in dirs:
            _check_link(Path(directory) / name, product)
        for name in sorted(files):
            path = Path(directory) / name
            relative_path = path.relative_to(product)
            if _excluded(relative_path, exclude):
                continue
            _check_link(path, product)
            # A symlink target may be inside the product, but editing it in a copied
            # tree would still edit the original if the link is absolute.
            if path.is_symlink() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative = relative_path.as_posix()
            found.extend(mutations_for_file(path, relative))
    # Every class gets a chance before a second site of the same class.
    priorities = {name: index for index, name in enumerate(("flip_comparison", "off_by_one", "invert_boolean_return", "drop_status_check", "swap_branches", "remove_duplicate_check"))}
    groups: dict[str, list[Mutation]] = {}
    for mutation in found:
        groups.setdefault(mutation.kind, []).append(mutation)
    ordered: list[Mutation] = []
    while any(groups.values()):
        for kind in sorted(groups, key=lambda key: priorities[key]):
            if groups[kind]:
                ordered.append(groups[kind].pop(0))
    valid: list[Mutation] = []
    for mutation in ordered:
        if mutation.path.endswith(".py"):
            source = (product / mutation.path).read_text(encoding="utf-8")
            changed = source[:mutation.start] + mutation.replacement + source[mutation.end:]
            try:
                ast.parse(changed)
            except SyntaxError:
                continue
            if source == changed:
                continue
        valid.append(mutation)
    return valid


def _stop_group(process: subprocess.Popen) -> str | None:
    """Stop only the process group created by this Popen, including descendants."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        return None
    except OSError as error:
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return str(error)
    return None


def _run(command: list[str], working: Path, timeout: float) -> dict:
    argv = [argument.replace("{product}", str(working)) for argument in command]
    # Files let communicate finish when the command exits even if an orphaned
    # child inherited stdout/stderr. The group is then stopped unconditionally.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(argv, cwd=working, stdout=out, stderr=err,
                                   start_new_session=(os.name == "posix"))
        timed_out = False
        cleanup_error = None
        try:
            process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            cleanup_error = _stop_group(process)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                cleanup_error = cleanup_error or "command remained live after group stop"
        finally:
            cleanup_error = _stop_group(process) or cleanup_error
        out.seek(max(0, out.seek(0, os.SEEK_END) - 2000))
        stdout = out.read().decode("utf-8", "replace")
        err.seek(max(0, err.seek(0, os.SEEK_END) - 2000))
        stderr = err.read().decode("utf-8", "replace")
        return {"exit_code": None if timed_out else process.returncode,
                "timed_out": timed_out, "stdout_tail": stdout,
                "stderr_tail": stderr, "cleanup_error": cleanup_error}


def _remove_temp(path: Path) -> None:
    def make_writable(function, name, _error):
        try:
            os.chmod(name, 0o700)
            function(name)
        except OSError as error:
            print(f"seeded_faults: temporary cleanup failed: {name}: {error}", file=sys.stderr)

    try:
        shutil.rmtree(path, onerror=make_writable)
    except OSError as error:
        print(f"seeded_faults: temporary cleanup failed: {path}: {error}", file=sys.stderr)


def _copy_product(product: Path, destination: Path) -> None:
    shutil.copytree(product, destination, symlinks=True)
    # Absolute links pointing into the original product must point into the
    # copy, or a check command could write the original through the link.
    origin = product.resolve()
    for directory, dirs, files in os.walk(destination, followlinks=False):
        for name in dirs + files:
            link = Path(directory) / name
            if not link.is_symlink() or not os.path.isabs(os.readlink(link)):
                continue
            resolved = link.resolve()
            if resolved.is_relative_to(origin):
                copied_target = destination / resolved.relative_to(origin)
                is_dir = resolved.is_dir()
                link.unlink()
                link.symlink_to(os.path.relpath(copied_target, link.parent),
                                target_is_directory=is_dir)


def scan(product: Path, count: int, command: list[str], timeout: float,
         *, build_command: list[str] | None = None, seed: int = 0,
         all_mutants: bool = False, exclude: list[str] | None = None,
         reverify_every: int = 10) -> dict:
    if not product.is_dir():
        raise ValueError(f"product folder does not exist: {product}")
    if count < 1 or timeout <= 0 or not command or reverify_every < 1:
        raise ValueError("count and timeout must be positive, and test command cannot be empty")
    candidates = collect_mutations(product, exclude)
    selected = candidates if all_mutants else random.Random(seed).sample(candidates, min(count, len(candidates)))
    common = {"requested": count, "seed": seed, "candidates_total": len(candidates),
              "candidates_by_kind": dict(sorted(Counter(item.kind for item in candidates).items())),
              "mutated_files": sorted({item.path for item in selected})}
    if any(item.path.rsplit(".", 1)[-1] != "py" for item in selected) and not build_command:
        return {**common, "status": "build_required", "generated": 0, "valid": 0,
                "invalid": 0, "killed": 0, "catch_rate": None, "mutants": [], "survivors": []}
    root = Path(tempfile.mkdtemp(prefix="seeded-faults-"))
    try:
        def baseline_check(index: int) -> dict:
            baseline_dir = root / f"baseline-{index}"
            _copy_product(product, baseline_dir)
            build = _run(build_command, baseline_dir, timeout) if build_command else None
            test = (_run(command, baseline_dir, timeout)
                    if build is None or (build["exit_code"] == 0 and not build["timed_out"]
                                         and not build["cleanup_error"]) else None)
            return {"build": build, "test": test}

        def baseline_ok(check: dict) -> bool:
            return all(run is None or (run["exit_code"] == 0 and not run["timed_out"]
                                       and not run["cleanup_error"])
                       for run in (check["build"], check["test"])) and check["test"] is not None

        baseline = baseline_check(0)
        if not baseline_ok(baseline):
            return {**common, "status": "baseline_failed", "baseline": baseline,
                    "generated": 0, "valid": 0, "invalid": 0, "killed": 0,
                    "catch_rate": None, "mutants": [], "survivors": []}
        results: list[dict] = []
        reverifications = []
        for index, mutation in enumerate(selected, 1):
            target = root / f"mutant-{index}"
            _copy_product(product, target)
            file = target / mutation.path
            original = file.read_text(encoding="utf-8")
            changed = original[:mutation.start] + mutation.replacement + original[mutation.end:]
            file.write_text(changed, encoding="utf-8")
            build = _run(build_command, target, timeout) if build_command else None
            valid = build is None or (build["exit_code"] == 0 and not build["timed_out"]
                                      and not build["cleanup_error"])
            run = _run(command, target, timeout) if valid else None
            diff = "".join(difflib.unified_diff(original.splitlines(keepends=True), changed.splitlines(keepends=True),
                                                fromfile=f"a/{mutation.path}", tofile=f"b/{mutation.path}"))
            outcome = ("invalid" if not valid else "killed" if run["timed_out"]
                       or run["exit_code"] != 0 else "survived")
            results.append({"id": index, "kind": mutation.kind, "file": mutation.path,
                            "line": mutation.line, "outcome": outcome, "killed": outcome == "killed",
                            "diff": diff, "build": build, "test": run})
            if index % reverify_every == 0 or index == len(selected):
                reverifications.append({"after_mutant": index, **baseline_check(index)})
                if not baseline_ok(reverifications[-1]):
                    break
        if not selected:
            reverifications.append({"after_mutant": 0, **baseline_check(1)})
        unstable = any(not baseline_ok(check) for check in reverifications)
        unstable |= any((result["build"] and result["build"]["cleanup_error"])
                        or (result["test"] and result["test"]["cleanup_error"])
                        for result in results)
        kills = sum(result["outcome"] == "killed" for result in results)
        invalid = sum(result["outcome"] == "invalid" for result in results)
        valid = len(results) - invalid
        return {**common, "status": "environment_unstable" if unstable else "ok",
                "baseline": baseline, "baseline_rechecks": reverifications,
                "generated": len(results), "valid": valid, "invalid": invalid,
                "killed": kills, "catch_rate": None if unstable or not valid else kills / valid,
                "mutants": results, "survivors": [item for item in results if item["outcome"] == "survived"]}
    finally:
        _remove_temp(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", type=Path, required=True, help="product source folder (never changed)")
    parser.add_argument("--count", type=int, default=10, help="maximum single-edit mutants to run (default: 10)")
    parser.add_argument("--all", action="store_true", help="run every candidate")
    parser.add_argument("--seed", type=int, default=0, help="random sample seed (default: 0)")
    parser.add_argument("--exclude", action="append", default=[], help="glob for paths or names to exclude; repeatable")
    parser.add_argument("--timeout", type=float, default=60, help="seconds allowed per test command")
    parser.add_argument("--build-command", type=shlex.split,
                        help="quoted build command split into argv and run without a shell")
    parser.add_argument("--test-command", nargs=argparse.REMAINDER, required=True,
                        help="argv to run from each copied product folder; use {product} for its absolute path")
    args = parser.parse_args(argv)
    command = args.test_command
    if command and command[0] == "--":
        command = command[1:]
    try:
        report = scan(args.product.resolve(), args.count, command, args.timeout,
                      build_command=args.build_command, seed=args.seed,
                      all_mutants=args.all, exclude=args.exclude)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
