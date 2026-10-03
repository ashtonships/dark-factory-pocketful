import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", required=True)
    parser.add_argument("--item", type=int, choices=[5, 6], required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if not Path("/Volumes/SSD").is_mount():
        raise SystemExit("SSD not mounted")
    overflow = Path("/Volumes/SSD/overflow/darkfactory")
    overflow.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pf-mutants-", dir=overflow) as directory:
        archive = subprocess.Popen(["git", "archive", args.revision, "ui-core"], cwd=root, stdout=subprocess.PIPE)
        with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
            stream.extractall(directory, filter="data")
        if archive.wait() != 0:
            raise SystemExit("Pinned source archive failed")
        command = ["python3", "tools/seeded_faults.py", "--product", str(Path(directory) / "ui-core"), "--count", "20", "--seed", str(args.item), "--timeout", "120", "--build-command", "node --check pocketful-core.js", "--exclude", "selftest.js", "--exclude", "devstub.py", "--exclude", "browser-drill.js", "--exclude", "run-drill.sh", "--test-command"]
        command += ["node", "selftest.js"] if args.item == 5 else ["python3", str(Path(__file__).with_name("browser_measure.py"))]
        env = dict(os.environ, TMPDIR=directory, PW_MODULES="/Volumes/SSD/overflow/darkfactory/b2-pw/node_modules")
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
        report = overflow / f"pf-w{args.item}-{args.revision}-mutants.json"
        report.write_text(result.stdout)
        print(result.stderr)
        try:
            details = json.loads(result.stdout)
            print(json.dumps({key: details.get(key) for key in ["status", "seed", "generated", "valid", "invalid", "killed", "catch_rate"]}, indent=2))
            for survivor in details.get("survivors", []):
                print("SURVIVOR", survivor["id"], survivor["file"], survivor["line"], survivor["diff"])
        except json.JSONDecodeError:
            print(result.stdout[-3000:])
        print("Report:", report)
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
