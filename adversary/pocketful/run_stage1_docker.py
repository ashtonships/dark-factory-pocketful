import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid


RELAY = """
import socket, socketserver, sys, threading
class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection((sys.argv[1], 8080), timeout=5) as upstream:
            upstream.settimeout(None)
            def forward(source, target):
                try:
                    while True:
                        chunk = source.recv(65536)
                        if not chunk: break
                        target.sendall(chunk)
                except OSError: pass
                try: target.shutdown(socket.SHUT_WR)
                except OSError: pass
            worker = threading.Thread(target=forward, args=(self.request, upstream))
            worker.start()
            forward(upstream, self.request)
            worker.join()
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
Server(('0.0.0.0',8080), Handler).serve_forever()
"""


def command(arguments, **kwargs):
    result = subprocess.run(arguments, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def free_port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def host_load():
    return command(["uptime"])


def latency_probe(client, module):
    samples = []
    for repetition in range(3):
        seeded = module.fixture((10000, 2500, 0, 0))
        assert client.call("POST", "/_test/reset", seeded)[0] == 204
        status, session = client.call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
        assert status == 200
        barrier = threading.Barrier(50)
        def write(index):
            started = time.monotonic()
            try:
                barrier.wait(timeout=5)
                response = client.call("POST", "/payments", {"to_handle": "bob", "amount": 1}, session["token"], f"burst-{repetition}-{index}")
                return {"status": response[0], "seconds": time.monotonic() - started}
            except Exception as error:
                return {"error": type(error).__name__, "seconds": time.monotonic() - started}
        before = host_load()
        with ThreadPoolExecutor(max_workers=50) as executor:
            writes = list(executor.map(write, range(50)))
        started = time.monotonic()
        try:
            status, body = client.call("POST", "/_test/reset", seeded)
            reset_result = {"status": status}
        except Exception as error:
            reset_result = {"error": type(error).__name__}
        elapsed = time.monotonic() - started
        samples.append({"repetition": repetition + 1, "load_before": before, "load_after": host_load(), "writes": writes, "reset": {**reset_result, "seconds": elapsed, "budget_seconds": 10}})
        print("RESET SAMPLE", json.dumps(samples[-1]), flush=True)
    return samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revision", default="57cc82e90338f6ffa0f26ea7d16fb0a4c1913b91")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    overflow = Path("/Volumes/SSD/overflow/darkfactory")
    if not Path("/Volumes/SSD").is_mount():
        raise SystemExit("SSD not mounted")
    spec = importlib.util.spec_from_file_location("retained_attacks", Path(__file__).with_name("attack_stage1.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suffix = uuid.uuid4().hex[:10]
    image = "pf-adversary-stage1-" + suffix
    network = "pf-adversary-internal-" + suffix
    containers = []
    report = {"revision": args.revision, "load_start": host_load(), "resource_limits": {"cpus": 2, "memory": "2g"}, "runs": []}
    return_code = 1
    try:
        with tempfile.TemporaryDirectory(prefix="pf-s1-pinned-", dir=overflow) as directory:
            archive = subprocess.Popen(["git", "archive", args.revision, "stage-1"], cwd=root, stdout=subprocess.PIPE)
            with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
                stream.extractall(directory, filter="data")
            assert archive.wait() == 0
            product = Path(directory) / "stage-1"
            report["tree"] = command(["git", "rev-parse", args.revision + ":stage-1"], cwd=root)
            print(command(["docker", "build", "-t", image, str(product)], timeout=180), flush=True)
            command(["docker", "network", "create", "--internal", network], timeout=120)
            report["network_internal"] = json.loads(command(["docker", "network", "inspect", network]))[0]["Internal"]
            bases = []
            for index in range(2):
                port = free_port()
                name = image + "-" + str(index)
                command(["docker", "run", "-d", "--name", name, "--cpus", "2", "--memory", "2g", "--network", network, "-e", "PORT=8080", image], timeout=120)
                containers.append(name)
                address = json.loads(command(["docker", "inspect", name]))[0]["NetworkSettings"]["Networks"][network]["IPAddress"]
                relay = name + "-relay"
                command(["docker", "run", "-d", "--name", relay, "--network", "bridge", "-p", f"127.0.0.1:{port}:8080", image, "python", "-u", "-c", RELAY, address], timeout=120)
                containers.append(relay)
                command(["docker", "network", "connect", network, relay], timeout=120)
                base = f"http://127.0.0.1:{port}"
                client = module.Client(base)
                deadline = time.monotonic() + 60
                while True:
                    try:
                        if client.call("GET", "/health") == (200, {"status": "ok"}):
                            break
                    except Exception:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError("Container not healthy within 60s")
                    time.sleep(0.1)
                bases.append(base)
            for item in range(1, 5):
                before = host_load()
                started = time.monotonic()
                result = subprocess.run([sys.executable, "-B", str(Path(__file__).with_name("attack_stage1.py")), "--base", bases[0], "--destination", bases[1], "--item", str(item)], capture_output=True, text=True, timeout=240)
                evidence = {"item": item, "exit_code": result.returncode, "seconds": time.monotonic() - started, "load_before": before, "load_after": host_load(), "output": result.stdout + result.stderr}
                report["runs"].append(evidence)
                print("ITEM", item, evidence["exit_code"], evidence["seconds"], flush=True)
                print(evidence["output"], flush=True)
            report["reset_samples"] = latency_probe(module.Client(bases[0]), module)
            return_code = int(any(run["exit_code"] for run in report["runs"]))
    except Exception as error:
        report["runner_error"] = str(error)
        print("RUNNER ERROR", str(error), flush=True)
    finally:
        report["cleanup_errors"] = []
        for name in containers:
            try:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=120)
            except subprocess.TimeoutExpired:
                report["cleanup_errors"].append(name)
        for cleanup in (["docker", "network", "rm", network], ["docker", "image", "rm", image]):
            try:
                subprocess.run(cleanup, capture_output=True, timeout=120)
            except subprocess.TimeoutExpired:
                report["cleanup_errors"].append(" ".join(cleanup))
        report["load_end"] = host_load()
        args.report.write_text(json.dumps(report, indent=2))
        print("Report:", args.report, flush=True)
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
