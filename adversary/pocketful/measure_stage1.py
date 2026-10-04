import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    revision = "57cc82e90338f6ffa0f26ea7d16fb0a4c1913b91"
    tree = subprocess.check_output(["git", "rev-parse", "HEAD:stage-1"], cwd=root, text=True).strip()
    expected = subprocess.check_output(["git", "rev-parse", revision + ":stage-1"], cwd=root, text=True).strip()
    if tree != expected:
        raise SystemExit("Stage-1 tree is not the accepted revision")
    checker = "/Users/ashton/DarkFactory/band-work/pf-a/checker/run_checks.py"
    cache = Path.home() / ".cache" / "pf-adversary-mutants"
    cache.mkdir(parents=True, exist_ok=True)
    private = Path(tempfile.mkdtemp(prefix="pf-s1-mutation-evidence-", dir=cache))
    before = subprocess.check_output(["uptime"], text=True).strip()
    command = ["python3.12", "-B", "tools/seeded_faults.py", "--product", "stage-1", "--count", "20", "--seed", "1", "--timeout", "2400", "--test-command", "/Users/ashton/DarkFactory/dark-factory-wearedevs/.venv/bin/python", checker, "--stage", "1", "--stage-dir", "{product}", "--out", str(private / "checks") + "{product}-checker-out"]
    result = subprocess.run(command, cwd=root, env=dict(os.environ, TMPDIR=str(private)), capture_output=True, text=True)
    (private / "mutation.json").write_text(result.stdout)
    (private / "stderr.txt").write_text(result.stderr)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {"status": "runner_failed", "exit_code": result.returncode, "catch_rate": None}
    summary = {key: report.get(key) for key in ("status", "seed", "requested", "generated", "valid", "invalid", "killed", "catch_rate")}
    summary.update({"revision": revision, "tree": tree, "load_before": before, "load_after": subprocess.check_output(["uptime"], text=True).strip(), "private_evidence": str(private), "checker_command_source": "Checker message69c782ec: main2bba408, full stage1 W1-W4; Docker build inside checker, no subset", "test_command": command[command.index("--test-command") + 1:]})
    summary["survivors"] = [{key: survivor[key] for key in ("id", "kind", "file", "line", "diff")} for survivor in report.get("survivors", [])]
    args.report.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
