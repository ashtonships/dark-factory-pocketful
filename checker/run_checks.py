#!/usr/bin/env python3
"""The Checker's acceptance checks for Pocketful.

    <harness python> checker/run_checks.py --repo <clean checkout> --stage N --out <folder>
    <harness python> checker/run_checks.py --base-url http://127.0.0.1:8080 --stage N --out <folder>

With --repo it builds stage-N/ with its own Dockerfile, starts the image the way RUN.md
describes (one container, -e PORT and a port mapping, 2 vCPU, 2 GiB), times the first
healthy response, checks that the default port is 8080, and runs every check whose work
item is in force (checker/items.json) and binds stage N. JUnit XML goes to --out.
Exit 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

HERE = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_healthy(url: str, deadline: float) -> tuple[bool, str]:
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/health", timeout=2) as r:
                body = r.read()
                if r.status == 200:
                    return True, body.decode("utf-8", "replace")
                last = f"status {r.status}"
        except Exception as e:  # not ready yet
            last = repr(e)
        time.sleep(0.25)
    return False, last


def docker(*args, timeout=900, check=False) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=check)


def junit(path: Path, suite: str, cases: list[dict]) -> None:
    fails = sum(1 for c in cases if c.get("failure"))
    rows = []
    for c in cases:
        inner = ""
        if c.get("failure"):
            inner = f"<failure message={quoteattr(c['failure'][:300])}>{escape(c['failure'])}</failure>"
        rows.append(f'  <testcase classname={quoteattr(suite)} name={quoteattr(c["name"])} '
                    f'time="{c.get("time", 0):.2f}">{inner}</testcase>')
    path.write_text(f'<?xml version="1.0" encoding="utf-8"?>\n<testsuite name={quoteattr(suite)} '
                    f'tests="{len(cases)}" failures="{fails}" errors="0" skipped="0">\n'
                    + "\n".join(rows) + "\n</testsuite>\n")


def items_in_force(stage: int) -> list[str]:
    cfg = json.loads((HERE / "items.json").read_text())
    return sorted(k for k, first in cfg["items"].items() if int(first) <= stage)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--base-url")
    ap.add_argument("--stage", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--items", help="comma-separated override of checker/items.json")
    ap.add_argument("-k", dest="keyword")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items = a.items.split(",") if a.items else items_in_force(a.stage)
    print(f"checker: stage {a.stage}, items in force {items}", flush=True)

    cases: list[dict] = []
    containers: list[str] = []
    tag = f"pf-checker-s{a.stage}-{uuid.uuid4().hex[:8]}"
    base = a.base_url
    facts: dict = {}
    base2 = None
    try:
        if a.repo:
            folder = Path(a.repo) / f"stage-{a.stage}"
            facts["dockerfile"] = (folder / "Dockerfile").is_file()
            run_md = (folder / "RUN.md").read_text(errors="replace") if (folder / "RUN.md").is_file() else ""
            facts["run_md_build_and_run"] = "docker build" in run_md and "docker run" in run_md
            for f in ("Dockerfile", "RUN.md"):
                cases.append({"name": f"delivery: stage-{a.stage}/{f} exists (ledger: 15)",
                              "failure": None if (folder / f).is_file() else f"{f} missing"})
            t = time.monotonic()
            b = docker("build", "-t", tag, str(folder), timeout=1800)
            cases.append({"name": "delivery: docker build succeeds (ledger: 15, 18, 32, 34)",
                          "time": time.monotonic() - t,
                          "failure": None if b.returncode == 0 else (b.stdout + b.stderr)[-4000:]})
            facts["build_ok"] = b.returncode == 0
            if b.returncode != 0:
                return finish(out, cases, 1)
            port, inner = free_port(), 9137
            name = f"{tag}-main"
            t = time.monotonic()
            r = docker("run", "-d", "--rm", "--name", name, "--cpus", "2", "--memory", "2g",
                       "-e", f"PORT={inner}", "-p", f"127.0.0.1:{port}:{inner}", tag)
            containers.append(name)
            base = f"http://127.0.0.1:{port}"
            facts["limits"] = {"cpus": 2, "memory": "2g", "env": f"PORT={inner}"}
            ok, detail = wait_healthy(base, t + 60) if r.returncode == 0 else (False, r.stderr)
            facts["port_env_healthy_seconds"] = round(time.monotonic() - t, 2) if ok else None
            cases.append({"name": "runtime: honours -e PORT and is healthy within 60 s on 2 vCPU/2 GiB "
                                  "(ledger: 22, 27, 28, 29, 36, 37)",
                          "time": time.monotonic() - t,
                          "failure": None if ok else f"not healthy: {detail}"})
            if ok:
                try:
                    body = json.loads(detail)
                    bad = None if body == {"status": "ok"} else f"health body {detail!r}"
                except ValueError:
                    bad = f"health body not JSON: {detail!r}"
                cases.append({"name": "runtime: GET /health body is {\"status\": \"ok\"} (ledger: 37)",
                              "failure": bad})
            else:
                logs = docker("logs", name).stdout[-3000:]
                cases[-1]["failure"] += "\n" + logs
                return finish(out, cases, 1)
            # default port 8080 when PORT is unset
            port2, name2 = free_port(), f"{tag}-default"
            t = time.monotonic()
            r2 = docker("run", "-d", "--rm", "--name", name2, "-p", f"127.0.0.1:{port2}:8080", tag)
            containers.append(name2)
            ok2, d2 = wait_healthy(f"http://127.0.0.1:{port2}", t + 60) if r2.returncode == 0 else (False, r2.stderr)
            facts["default_port_healthy"] = ok2
            cases.append({"name": "runtime: listens on 0.0.0.0:8080 when PORT is unset (ledger: 36)",
                          "time": time.monotonic() - t, "failure": None if ok2 else d2})
            # kept running as an independent second instance (export/import across processes)
            base2 = f"http://127.0.0.1:{port2}" if ok2 else None
        if not base:
            print("need --repo or --base-url", file=sys.stderr)
            return 2
        env = dict(os.environ, PF_BASE_URL=base, PF_ITEMS=",".join(items), PF_STAGE=str(a.stage))
        if a.repo:
            (out / "runtime.json").write_text(json.dumps(facts, indent=2))
            env["PF_RUNTIME"] = str(out / "runtime.json")
        if base2:
            env["PF_BASE_URL_2"] = base2
        cmd = [sys.executable, "-m", "pytest", str(HERE / "tests"), "-q", "-p", "no:cacheprovider",
               "--junitxml", str(out / "checks.xml"), "-o", "junit_family=xunit1"]
        if a.keyword:
            cmd += ["-k", a.keyword]
        p = subprocess.run(cmd, env=env, cwd=HERE)
        rc = p.returncode
        if a.repo:
            # the service must survive the whole run: still healthy, no crash
            ok3, d3 = wait_healthy(base, time.monotonic() + 5)
            cases.append({"name": "runtime: still healthy after every check (ledger: 116)",
                          "failure": None if ok3 else d3})
            logs = docker("logs", containers[0])
            (out / "service.log").write_text(logs.stdout + logs.stderr)
        return finish(out, cases, rc)
    finally:
        for c in containers:
            docker("rm", "-f", c)
        if a.repo:
            docker("rmi", "-f", tag)


def finish(out: Path, cases: list[dict], rc: int) -> int:
    if cases:
        junit(out / "runtime.xml", "runtime", cases)
    bad = [c["name"] for c in cases if c.get("failure")]
    for c in cases:
        print(("FAIL " if c.get("failure") else "ok   ") + c["name"])
    return 0 if rc == 0 and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
