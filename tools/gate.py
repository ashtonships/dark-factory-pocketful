#!/usr/bin/env python3
"""The stage gate: code owns acceptance.

    python3 tools/gate.py run --stage N [--rev REV] [--checks-rev REV] [--level stage|item]
    python3 tools/gate.py verify [--branch main]
    python3 tools/gate.py install-hook
    python3 tools/gate.py show [--last K]

`run` takes a clean clone of the result repository at one commit and, holding the shared
check lock, runs in order (stopping at the first red step):

  1. export    a clean checkout of `--rev` (product) and of `--checks-rev` (the Checker's
               checks and tools/gate.json; default main, which only the Checker merges into,
               so a builder's branch cannot change how it is judged); records the git tree
               hash of every stage-K/ folder;
  2. mandates  the event's mandate scan (harness line, model line, every track's vocabulary)
               and its credential scan, over the whole checkout;
  3. overfit   overfit_scan.py over stage-N/ against the specification and the shipped tests;
               a high finding is red unless the config allows that token with a reason;
  4. harness   the event harness in isolated mode (internal network, no outbound, 2 vCPU,
               2 GiB) on stage-N/: every suite up to N, plus the overshoot probe;
  5. checker   the Checker's own checks, by the command the config names.

Then it appends one receipt to the hash chain (receipts/chain.jsonl in the repository's main
checkout). Each receipt carries the sha256 of the previous one, so an edited or deleted line
breaks every hash after it. Exit 0 = green, 1 = red, 2 = could not run.

Levels: `stage` (default) is green only when the folder claims stage N on the harness and no
earlier result regressed. `item` is for a work item that does not finish a stage: earlier
suites must still claim and not regress, and the Checker's checks must pass, but suite N may be
incomplete. Once a stage has a green `stage` receipt it is frozen: main accepts a new tree for it
only with another green `stage` receipt.

`install-hook` points core.hooksPath at tools/hooks, whose reference-transaction hook refuses
any update of main that changes a stage-K/ tree without a green receipt for that exact tree.

Standard library only. Track-specific values live in the config (tools/gate.json), never here.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ZERO = "0" * 64
ZERO_OID = re.compile(r"^0+$")
STAGE_DIR = re.compile(r"^stage-(\d+)$")
PASS_BAR = 0.5
SCHEMA = 1


class GateError(Exception):
    """The gate could not run (configuration, git, lock). Not a verdict."""


# ---------------------------------------------------------------- git helpers

def git(*args, cwd=None, check=True, env=None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    if check and proc.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def repo_root(path: str | None) -> Path:
    return Path(git("rev-parse", "--show-toplevel", cwd=path or os.getcwd()))


def main_root(repo: Path) -> Path:
    """The main checkout (where main lives), from any linked worktree."""
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=repo))
    return common.parent


def stage_trees(repo: Path, rev: str) -> dict[str, str]:
    """{stage number: tree hash} for every stage-K/ folder at `rev`."""
    out = git("ls-tree", rev, cwd=repo, check=False)
    trees = {}
    for line in out.splitlines():
        meta, _, name = line.partition("\t")
        parts = meta.split()
        m = STAGE_DIR.match(name)
        if m and len(parts) == 3 and parts[1] == "tree":
            trees[m.group(1)] = parts[2]
    return trees


# ---------------------------------------------------------------- receipt chain

def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def receipt_hash(receipt: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in receipt.items() if k != "hash"})).hexdigest()


def read_chain(path: Path) -> tuple[list[dict], str | None]:
    """(verified receipts, problem). Receipts after the first broken line are not returned."""
    if not path.exists():
        return [], None
    receipts, prev = [], ZERO
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            return receipts, f"line {number} is not JSON"
        if r.get("prev_hash") != prev:
            return receipts, f"line {number}: prev_hash does not match the receipt before it"
        if r.get("hash") != receipt_hash(r):
            return receipts, f"line {number}: hash does not match its content"
        if r.get("seq") != len(receipts) + 1:
            return receipts, f"line {number}: seq {r.get('seq')} out of order"
        receipts.append(r)
        prev = r["hash"]
    return receipts, None


def append_receipt(path: Path, receipt: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            receipts, problem = read_chain(path)
            if problem:
                raise GateError(
                    f"receipt chain {path} is broken ({problem}). Nothing was appended. Move the "
                    f"file aside (keep it as evidence: receipts/chain-broken-<time>.jsonl), record "
                    f"why in the room, and rerun the gate")
            receipt["seq"] = len(receipts) + 1
            receipt["prev_hash"] = receipts[-1]["hash"] if receipts else ZERO
            receipt["hash"] = receipt_hash(receipt)
            handle.seek(0, os.SEEK_END)
            handle.write(canonical(receipt).decode() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    return receipt


def latest_green(receipts: list[dict], stage: str, level: str | None = None) -> dict | None:
    for r in reversed(receipts):
        if (r.get("verdict") == "green" and str(r.get("stage")) == str(stage)
                and (level is None or r.get("level") == level)):
            return r
    return None


def green_for_tree(receipts, stage: str, tree: str, levels) -> dict | None:
    for r in reversed(receipts):
        if (r.get("verdict") == "green" and str(r.get("stage")) == str(stage)
                and r.get("stage_tree") == tree and r.get("level") in levels):
            return r
    return None


# ---------------------------------------------------------------- config

def load_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise GateError(f"cannot read the gate config {path}: {exc}")
    missing = [k for k in ("track", "harness_dir", "python", "spec", "shipped_tests",
                           "checker_command") if not config.get(k)]
    if missing:
        raise GateError(f"gate config {path} lacks {', '.join(missing)}")
    return config


def fill(template, values: dict):
    if isinstance(template, list):
        return [fill(t, values) for t in template]
    return str(template).format(**values)


# ---------------------------------------------------------------- the check lock

def _ancestors() -> set[int]:
    pids, pid = set(), os.getpid()
    for _ in range(64):
        pids.add(pid)
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True,
                             text=True).stdout.strip()
        if not out.isdigit() or int(out) <= 1:
            break
        pid = int(out)
    return pids


@contextlib.contextmanager
def check_lock(lock: Path, wait_seconds: int = 2700):
    """The band's shared lock (same protocol as with-check-lock). Re-entrant for a gate that
    was itself started under with-check-lock: the holder is then one of our ancestors."""
    holder = lock / "holder"
    try:
        held_by = int(holder.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        held_by = None
    if held_by and held_by in _ancestors():
        yield "inherited"
        return
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            lock.mkdir(parents=False)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise GateError(f"check lock {lock} busy for {wait_seconds // 60} minutes; "
                                f"holder: {holder.read_text() if holder.exists() else '?'}")
            time.sleep(5)
    try:
        holder.write_text(f"{os.getpid()} {now()} gate.py\n")
        yield "acquired"
    finally:
        with contextlib.suppress(OSError):
            holder.unlink()
        with contextlib.suppress(OSError):
            lock.rmdir()


# ---------------------------------------------------------------- steps

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_cmd(cmd: list[str], cwd, log: Path, timeout: int) -> tuple[int, str, float]:
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                              start_new_session=True)
        code, text = proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        text = f"timed out after {timeout}s\n{exc.stdout or ''}{exc.stderr or ''}"
    log.write_text(f"$ {' '.join(cmd)}\n(cwd {cwd})\n\n{text}")
    return code, text, round(time.monotonic() - start, 1)


def clone_at(repo: Path, rev: str, dest: Path) -> None:
    git("clone", "--quiet", "--no-checkout", "--no-hardlinks", str(repo), str(dest))
    git("checkout", "--quiet", "--detach", rev, cwd=dest)
    git("config", "core.hooksPath", "/dev/null", cwd=dest)  # the copy is never gated itself


def step_mandates(cfg, checkout: Path, out: Path) -> dict:
    code = (
        "import json,pathlib,sys\n"
        "from harness import check, vocabulary\n"
        "root=pathlib.Path(sys.argv[1])\n"
        "problems=[]\n"
        "for track in sorted(vocabulary.TRACK_VOCABULARY):\n"
        "    problems += [p for p in check._mandates(root, track) if p not in problems]\n"
        "problems += check._credentials(root)\n"
        "print(json.dumps(problems))\n")
    rc, text, secs = run_cmd([cfg["python"], "-c", code, str(checkout)], cfg["harness_dir"],
                             out / "mandates.log", 300)
    try:
        problems = json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"name": "mandates", "ok": False, "seconds": secs,
                "reason": f"mandate scan did not run (exit {rc}); see mandates.log"}
    return {"name": "mandates", "ok": rc == 0 and not problems, "seconds": secs,
            "problems": problems,
            "reason": f"{len(problems)} mandate/credential problem(s): {problems[:3]}" if problems else ""}


def step_overfit(cfg, checkout: Path, stage: str, out: Path) -> dict:
    product = checkout / f"stage-{stage}"
    cmd = [sys.executable, str(TOOLS / "overfit_scan.py"), "--spec", cfg["spec"],
           "--tests", cfg["shipped_tests"], "--product", str(product)]
    rc, text, secs = run_cmd(cmd, checkout, out / "overfit.log", 600)
    try:
        report = json.loads(text[text.index("{"):])
    except ValueError:
        return {"name": "overfit", "ok": False, "seconds": secs,
                "reason": f"overfit scan did not produce JSON (exit {rc}); see overfit.log"}
    (out / "overfit.json").write_text(json.dumps(report, indent=2))
    allowed = {a["token"] for a in cfg.get("overfit_allow", []) if a.get("reason")}
    high = [f for f in report.get("findings", []) if f.get("severity") == "high"]
    blocking = [f for f in high if f.get("token") not in allowed]
    return {"name": "overfit", "ok": not blocking, "seconds": secs,
            "candidates": report.get("candidate_count"), "findings": report.get("finding_count"),
            "high": len(high), "high_allowed": len(high) - len(blocking),
            "blocking": [{k: f.get(k) for k in ("file", "line", "token", "kind")} for f in blocking][:20],
            "reason": (f"{len(blocking)} high test-fitting finding(s) not allowed by the config, "
                       f"e.g. {blocking[0].get('token')!r} in {blocking[0].get('file')}:{blocking[0].get('line')}"
                       if blocking else "")}


def _suite_counts(report: dict) -> dict:
    counts = {}
    for suite, c in (report.get("checks") or {}).items():
        files = c.get("files") or {}
        rates = [f["passed"] / f["total"] for f in files.values() if f.get("total")]
        counts[suite] = {"passed": c.get("passed", 0), "failed": c.get("failed", 0),
                         "errors": c.get("errors", 0), "skipped": c.get("skipped", 0),
                         "total": c.get("collected", 0),
                         "rate": round(sum(rates) / len(rates), 4) if rates else 0.0}
    return counts


def step_harness(cfg, checkout: Path, stage: str, level: str, out: Path, receipts) -> dict:
    hout = out / "harness"
    cmd = [cfg["python"], "-m", "harness", "run", "--track", cfg["track"], "--repo", str(checkout),
           "--stage", stage, "--mode", "isolated", "--out", str(hout)]
    rc, text, secs = run_cmd(cmd, cfg["harness_dir"], out / "harness.log",
                             int(cfg.get("harness_timeout", 3600)))
    try:
        report = json.loads((hout / "report.json").read_text())
    except (OSError, ValueError):
        return {"name": "harness", "ok": False, "seconds": secs, "exit": rc,
                "reason": f"the harness wrote no report (exit {rc}); see harness.log"}
    counts = _suite_counts(report)
    last = [l for l in text.splitlines() if l.startswith("claimed stage:")]
    reasons = []
    if report.get("state") != "completed":
        reasons.append(f"harness run state {report.get('state')!r} (see harness.log / startup.log)")
    missing = [s for s in (report.get("stages") or {}) if int(s) <= int(stage) and s not in counts]
    if missing:
        reasons.append(f"no check counts for suite(s) {', '.join(missing)}: the suite errored or its "
                       f"counts file never reached {hout} (Docker must be able to mount that folder; "
                       f"keep checks_out under the home folder)")
    for suite in sorted(counts, key=int):
        if int(suite) > int(stage):
            continue
        c = counts[suite]
        if int(suite) < int(stage) and c["rate"] < PASS_BAR:
            reasons.append(f"suite {suite} fell to {c['rate']:.0%} (< {PASS_BAR:.0%}): an earlier stage broke")
        # No regression against the accepted record of that suite.
        refs = [latest_green(receipts, stage, "stage")]
        if int(suite) < int(stage):
            refs.append(latest_green(receipts, suite, "stage"))
        for ref in filter(None, refs):
            before = next((s for s in ref.get("steps", []) if s.get("name") == "harness"), {})
            was = ((before.get("counts") or {}).get(suite) or {}).get("passed")
            if was is not None and c["passed"] < was:
                reasons.append(f"suite {suite} regressed: {c['passed']} passed, the accepted "
                               f"receipt #{ref['seq']} had {was}")
    if level == "stage":
        if report.get("overshoot"):
            reasons.append(f"stage-{stage}/ also passes suite {report['overshoot']}: it is a later "
                           f"answer and claims nothing")
        elif str(report.get("claimed_stage")) != stage:
            reasons.append(f"stage-{stage}/ does not claim stage {stage} "
                           f"({last[-1] if last else 'no claim line'})")
    reasons = list(dict.fromkeys(reasons))
    return {"name": "harness", "ok": not reasons, "seconds": secs, "exit": rc,
            "mode": report.get("mode"), "claimed_stage": report.get("claimed_stage"),
            "overshoot": report.get("overshoot"), "highest_contiguous": report.get("highest_contiguous"),
            "suite_digest": report.get("suite_digest"), "counts": counts,
            "claim_line": last[-1] if last else "", "out": str(hout),
            "reason": "; ".join(reasons)}


def _junit_counts(folder: Path) -> dict | None:
    total = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "total": 0}
    found = False
    for path in glob.glob(str(folder / "**" / "*.xml"), recursive=True):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        for s in suites:
            found = True
            t, f, e, k = (int(s.get(a, 0)) for a in ("tests", "failures", "errors", "skipped"))
            total["total"] += t
            total["failed"] += f
            total["errors"] += e
            total["skipped"] += k
            total["passed"] += t - f - e - k
    return total if found else None


def _pytest_counts(text: str) -> dict | None:
    lines = [l for l in text.splitlines() if re.search(r"\d+ (passed|failed)", l)]
    if not lines:
        return None
    line = lines[-1]
    get = lambda word: sum(int(n) for n in re.findall(rf"(\d+) {word}", line))
    c = {"passed": get("passed"), "failed": get("failed"), "errors": get(r"errors?"),
         "skipped": get("skipped")}
    c["total"] = sum(c.values())
    return c


def step_checker(cfg, product: Path, checks: Path, stage: str, out: Path) -> dict:
    values = {"python": cfg["python"], "checkout": str(product), "checks": str(checks),
              "stage": stage, "out": str(out), "track": cfg["track"],
              "harness": cfg["harness_dir"], "tools": str(TOOLS)}
    cmd = fill(cfg["checker_command"], values)
    rc, text, secs = run_cmd(cmd, checks, out / "checker.log", int(cfg.get("checker_timeout", 3600)))
    counts = _junit_counts(out / "checker") if (out / "checker").exists() else None
    counts = counts or _pytest_counts(text)
    ok = rc == 0 and bool(counts) and counts["total"] > 0 and not counts["failed"] and not counts["errors"]
    reason = ""
    if not ok:
        reason = (f"the Checker's checks failed (exit {rc}"
                  + (f", {counts['failed']} failed, {counts['errors']} errors" if counts else
                     ", no test counts found") + "); see checker.log")
    return {"name": "checker", "ok": ok, "seconds": secs, "exit": rc, "command": cmd,
            "counts": counts, "reason": reason}


# ---------------------------------------------------------------- run

def cmd_run(a) -> int:
    repo = repo_root(a.repo)
    mroot = main_root(repo)
    stage = str(a.stage)
    rev = git("rev-parse", "--verify", f"{a.rev}^{{commit}}", cwd=repo)
    default_checks = "main" if git("rev-parse", "-q", "--verify", "refs/heads/main", cwd=repo,
                                   check=False) else rev
    checks_rev = git("rev-parse", "--verify", f"{a.checks_rev or default_checks}^{{commit}}", cwd=repo)
    trees = stage_trees(repo, rev)
    if stage not in trees:
        raise GateError(f"stage-{stage}/ does not exist at {rev[:12]}")
    receipts_path = Path(a.receipts) if a.receipts else mroot / "receipts" / "chain.jsonl"
    receipts, problem = read_chain(receipts_path)
    if problem:
        raise GateError(f"receipt chain {receipts_path} is broken ({problem}); move it aside "
                        f"(keep it as evidence) and rerun")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # The clean checkouts are kept, never deleted by the gate: they are exactly the trees
    # that were judged. They live under the home folder (Docker on macOS mounts only that,
    # not the system temp folder), outside every repository.
    work_root = Path(os.environ.get("GATE_WORK") or Path.home() / ".cache" / "factory-gate")
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"gate-s{stage}-{rev[:10]}-", dir=work_root))
    product, checks = work / "product", work / "checks"
    started = now()
    steps, cfg_path = [], None
    try:
        t = time.monotonic()
        clone_at(repo, rev, product)
        if checks_rev == rev:
            checks = product
        else:
            clone_at(repo, checks_rev, checks)
        cfg_path = Path(a.config) if a.config else checks / "tools" / "gate.json"
        cfg = load_config(cfg_path)
        out_root = Path(cfg.get("checks_out") or (mroot.parent / "checks"))
        out = out_root / f"gate-s{stage}-{rev[:10]}-{stamp}"
        out.mkdir(parents=True, exist_ok=False)
        steps.append({"name": "export", "ok": True, "seconds": round(time.monotonic() - t, 1),
                      "product": rev, "checks": checks_rev, "trees": trees})
        lock = Path(cfg.get("lock") or os.environ.get("CHECK_LOCK")
                    or Path.home() / "DarkFactory" / ".check-lock")
        plan = [lambda: step_mandates(cfg, product, out),
                lambda: step_overfit(cfg, product, stage, out),
                lambda: step_harness(cfg, product, stage, a.level, out, receipts),
                lambda: step_checker(cfg, product, checks, stage, out)]
        names = ["mandates", "overfit", "harness", "checker"]
        print(f"gate: stage {stage} ({a.level}) at {rev[:12]}, checks {checks_rev[:12]}; out {out}",
              flush=True)
        with check_lock(lock) as how:
            steps[0]["lock"] = how
            for name, step in zip(names, plan):
                if a.skip_after_red and not all(s["ok"] for s in steps):
                    steps.append({"name": name, "ok": False, "skipped": True, "seconds": 0,
                                  "reason": "skipped after an earlier red step"})
                    continue
                result = step()
                steps.append(result)
                print(f"  {name}: {'ok' if result['ok'] else 'RED'} ({result['seconds']}s)"
                      + (f" - {result['reason']}" if result.get("reason") else ""), flush=True)
    finally:
        print(f"clean checkouts kept at {work}", flush=True)

    reasons = [s["reason"] for s in steps if not s["ok"] and s.get("reason") and not s.get("skipped")]
    verdict = "green" if all(s["ok"] for s in steps) else "red"
    receipt = {
        "schema": SCHEMA, "time": now(), "started": started, "verdict": verdict,
        "level": a.level, "stage": int(stage), "track": cfg["track"], "rev": rev,
        "checks_rev": checks_rev, "stage_tree": trees[stage], "trees": trees,
        "by": a.by or os.environ.get("GIT_AUTHOR_NAME") or git("config", "user.name", cwd=repo, check=False),
        "config": str(cfg_path), "config_sha256": hashlib.sha256(cfg_path.read_bytes()).hexdigest(),
        "out": str(out), "steps": steps, "reasons": reasons,
    }
    receipt = append_receipt(receipts_path, receipt)
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2))
    head = (f"GATE {verdict.upper()} #{receipt['seq']} stage {stage} {a.level} rev {rev[:12]} "
            f"tree {trees[stage][:12]} hash {receipt['hash'][:12]}")
    h = next((s for s in steps if s["name"] == "harness"), {})
    if h.get("counts"):
        head += " | " + " ".join(f"s{k} {v['passed']}/{v['total']}" for k, v in sorted(h["counts"].items()))
    c = next((s for s in steps if s["name"] == "checker"), {})
    if c.get("counts"):
        head += f" | checker {c['counts']['passed']}/{c['counts']['total']}"
    print(head)
    for r in reasons:
        print(f"  red: {r}")
    print(f"receipt: {receipts_path} (line {receipt['seq']}); evidence: {out}")
    return 0 if verdict == "green" else 1


# ---------------------------------------------------------------- hook support

def refusals_for_update(repo: Path, receipts: list[dict], old: str, new: str) -> list[dict]:
    """Every stage tree that `old -> new` on main changes without a green receipt."""
    if ZERO_OID.match(new) or old == new:
        return []
    before = {} if ZERO_OID.match(old) else stage_trees(repo, old)
    after = stage_trees(repo, new)
    refused = []
    for stage in sorted(set(before) | set(after), key=int):
        tree = after.get(stage)
        if tree == before.get(stage):
            continue
        if tree is None:
            refused.append({"stage": stage, "tree": None,
                            "reason": f"removes stage-{stage}/, which main never loses"})
            continue
        frozen = latest_green(receipts, stage, "stage") is not None
        levels = ("stage",) if frozen else ("stage", "item")
        if not green_for_tree(receipts, stage, tree, levels):
            refused.append({"stage": stage, "tree": tree, "reason": (
                f"stage-{stage}/ would become tree {tree[:12]}, which has no green "
                f"{'stage' if frozen else 'stage or item'} receipt"
                + (f" (stage {stage} is frozen: it needs a green stage-level receipt)" if frozen else ""))})
    return refused


def hook_main(state: str, lines: list[str], protected=("refs/heads/main",)) -> int:
    if state != "prepared":
        return 0
    updates = []
    for line in lines:
        parts = line.split()
        if len(parts) == 3 and parts[2] in protected:
            updates.append(parts)
    if not updates:
        return 0
    repo = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    receipts_path = repo / "receipts" / "chain.jsonl"
    receipts, problem = read_chain(receipts_path)
    refused = []
    for old, new, ref in updates:
        for r in refusals_for_update(repo, receipts, old, new):
            refused.append({"time": now(), "ref": ref, "old": old, "new": new, **r})
    if not refused:
        return 0
    with contextlib.suppress(OSError):
        (repo / "receipts").mkdir(exist_ok=True)
        with open(repo / "receipts" / "refusals.jsonl", "a") as log:
            for r in refused:
                log.write(json.dumps(r, sort_keys=True) + "\n")
    print("GATE REFUSED: main does not accept a stage folder without a green receipt for its "
          "exact tree.", file=sys.stderr)
    for r in refused:
        print(f"  - {r['reason']}", file=sys.stderr)
    if problem:
        print(f"  (the receipt chain is broken after its last good line: {problem})", file=sys.stderr)
    print("  main is unchanged, but this checkout may still hold the refused files. Restore it:\n"
          "    git merge --abort      (after a refused merge commit)\n"
          "    git reset --hard HEAD  (after a refused fast-forward or reset; untracked receipts/ stay)\n"
          "  A refused commit leaves your changes staged; move them to a branch.\n"
          "  Fix: run the gate on the commit whose stage tree you are merging, e.g.\n"
          "    python3 tools/gate.py run --stage N --rev <branch or sha>\n"
          "  and merge only after it prints GATE GREEN. When two branches change the same stage, "
          "merge them on a branch first, gate that commit, then merge it into main.", file=sys.stderr)
    return 1


def cmd_verify(a) -> int:
    repo = repo_root(a.repo)
    mroot = main_root(repo)
    path = Path(a.receipts) if a.receipts else mroot / "receipts" / "chain.jsonl"
    receipts, problem = read_chain(path)
    problems = [f"chain: {problem}"] if problem else []
    revs = git("rev-list", "--first-parent", "--reverse", a.branch, cwd=repo).split()
    prev = None
    for rev in revs:
        if prev is not None:
            for r in refusals_for_update(repo, receipts, prev, rev):
                problems.append(f"{rev[:12]}: {r['reason']}")
        prev = rev
    green = sum(r["verdict"] == "green" for r in receipts)
    print(f"receipts: {len(receipts)} verified ({green} green, {len(receipts) - green} red); "
          f"{len(revs)} first-parent commits on {a.branch} checked")
    for p in problems:
        print(f"  - {p}")
    print("verify: ok" if not problems else f"verify: {len(problems)} problem(s)")
    return 0 if not problems else 1


def cmd_show(a) -> int:
    repo = repo_root(a.repo)
    path = Path(a.receipts) if a.receipts else main_root(repo) / "receipts" / "chain.jsonl"
    receipts, problem = read_chain(path)
    for r in receipts[-a.last:]:
        print(f"#{r['seq']} {r['time']} {r['verdict'].upper():5} stage {r['stage']} {r['level']:5} "
              f"rev {r['rev'][:12]} tree {r['stage_tree'][:12]} by {r.get('by')}"
              + (f" | {'; '.join(r['reasons'])[:160]}" if r.get("reasons") else ""))
    if problem:
        print(f"chain broken: {problem}")
    return 1 if problem else 0


def cmd_install_hook(a) -> int:
    repo = repo_root(a.repo)
    hooks = (TOOLS / "hooks").resolve()
    hook = hooks / "reference-transaction"
    if not hook.is_file():
        raise GateError(f"{hook} is missing")
    hook.chmod(0o755)
    git("config", "core.hooksPath", str(hooks), cwd=repo)
    print(f"core.hooksPath = {hooks} (applies to every worktree of {main_root(repo)})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="gate.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="gate one stage at one commit and append a receipt")
    r.add_argument("--stage", required=True, type=int)
    r.add_argument("--rev", default="HEAD", help="product commit (default HEAD)")
    r.add_argument("--checks-rev", help="commit holding the Checker's checks and tools/gate.json "
                                        "(default: main; a builder's branch never judges itself)")
    r.add_argument("--level", choices=("stage", "item"), default="stage")
    r.add_argument("--config", help="gate config (default: tools/gate.json at --checks-rev)")
    r.add_argument("--by", help="seat running the gate (default: git user.name)")
    r.add_argument("--no-skip", dest="skip_after_red", action="store_false",
                   help="run every step even after a red one")
    v = sub.add_parser("verify", help="check the chain, and that every stage tree main ever "
                                      "held had a green receipt")
    v.add_argument("--branch", default="main")
    s = sub.add_parser("show", help="list the last receipts")
    s.add_argument("--last", type=int, default=20)
    sub.add_parser("install-hook", help="set core.hooksPath to tools/hooks")
    for q in (r, v, s, sub.choices["install-hook"]):
        q.add_argument("--repo", help="result repository (default: the current one)")
        q.add_argument("--receipts", help="receipt chain (default: receipts/chain.jsonl in the "
                                          "main checkout)")
    a = p.parse_args(argv)
    try:
        return {"run": cmd_run, "verify": cmd_verify, "show": cmd_show,
                "install-hook": cmd_install_hook}[a.cmd](a)
    except GateError as exc:
        print(f"gate: could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
