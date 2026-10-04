import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import uuid


def command(arguments, **kwargs):
    result = subprocess.run(arguments, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def ready_host(report):
    deadline = time.monotonic() + 300
    report["host_samples"] = []
    while True:
        load = os.getloadavg()[0]
        started = time.monotonic()
        try:
            command(["docker", "version", "--format", "{{.Server.Version}}"], timeout=3)
            latency = time.monotonic() - started
        except Exception:
            latency = None
        report["host_samples"].append({"load_1min": load, "docker_version_seconds": latency})
        if load < 40 and latency is not None and latency < 3:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Host preflight not ready within 300s; no product runtime finding")
        time.sleep(15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="9332b9f")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    root = scripts.parents[1]
    if not Path("/Volumes/SSD").is_mount():
        raise SystemExit("SSD not mounted")
    image = "pf-adversary-real-" + uuid.uuid4().hex[:10]
    container = image + "-service"
    report = {"revision": args.revision, "load_start": command(["uptime"]), "container_resources": {"cpus": 2, "memory": "2g"}, "devstub": False}
    return_code = 1
    created = False
    try:
        ready_host(report)
        with tempfile.TemporaryDirectory(prefix="pf-real-review-", dir="/Volumes/SSD/overflow/darkfactory") as directory:
            archive = subprocess.Popen(["git", "archive", args.revision, "stage-2"], cwd=root, stdout=subprocess.PIPE)
            with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
                stream.extractall(directory, filter="data")
            assert archive.wait() == 0
            product = Path(directory) / "stage-2"
            report["tree"] = command(["git", "rev-parse", args.revision + ":stage-2"], cwd=root)
            print(command(["docker", "build", "-t", image, str(product)], timeout=180), flush=True)
            with socket.socket() as connection:
                connection.bind(("127.0.0.1", 0))
                port = connection.getsockname()[1]
            command(["docker", "run", "-d", "--name", container, "--cpus", "2", "--memory", "2g", "-e", "PORT=8080", "-p", f"127.0.0.1:{port}:8080", image], timeout=120)
            created = True
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 60
            while True:
                try:
                    with urllib.request.urlopen(base + "/health", timeout=5) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("No healthy response within 60s")
                time.sleep(0.1)
            env = dict(os.environ, NODE_PATH="/Volumes/SSD/overflow/darkfactory/b2-pw/node_modules", TMPDIR="/tmp", NODE_OPTIONS="--require=" + str(scripts / "chrome_cleanup.js"))
            result = subprocess.run(["node", str(scripts / "review_browser.js"), base, "--d11", "--presence"], capture_output=True, text=True, env=env, timeout=240)
            report.update({"browser_exit_code": result.returncode, "browser_output": result.stdout + result.stderr})
            print(report["browser_output"], flush=True)
            return_code = result.returncode
    except Exception as error:
        report["runner_error"] = str(error)
        print("RUNNER ERROR", str(error), flush=True)
    finally:
        report["cleanup_errors"] = []
        cleanups = [["docker", "image", "rm", image]]
        if created:
            cleanups.insert(0, ["docker", "rm", "-f", container])
        for cleanup in cleanups:
            try:
                subprocess.run(cleanup, capture_output=True, timeout=120)
            except subprocess.TimeoutExpired:
                report["cleanup_errors"].append(" ".join(cleanup))
        report["load_end"] = command(["uptime"])
        args.report.write_text(json.dumps(report, indent=2))
        print("Report:", args.report, flush=True)
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
