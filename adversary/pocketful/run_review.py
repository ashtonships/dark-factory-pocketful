import argparse
import os
from pathlib import Path
import socket
import subprocess
import tarfile
import tempfile
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("--revision", default="73beaa0")
    parser.add_argument("--d11", action="store_true")
    parser.add_argument("--modules", default="/Volumes/SSD/overflow/darkfactory/b2-pw/node_modules")
    args = parser.parse_args()
    if not Path("/Volumes/SSD").is_mount():
        raise SystemExit("External SSD is not mounted; no source-copy fallback")
    scripts = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="pf-review-", dir="/Volumes/SSD/overflow/darkfactory") as directory:
        archive = subprocess.Popen(["git", "-C", str(args.repo), "archive", args.revision, "ui-core"], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
            stream.extractall(directory, filter="data")
        if archive.wait() != 0:
            raise SystemExit("Cannot extract pinned source")
        with socket.socket() as connection:
            connection.bind(("127.0.0.1", 0))
            port = connection.getsockname()[1]
        source = Path(directory) / "ui-core"
        stub = subprocess.Popen(["python3", str(source / "devstub.py"), "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{port}"
        try:
            for attempt in range(100):
                try:
                    with urllib.request.urlopen(base + "/_test/export", timeout=1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise SystemExit("Review stub did not become healthy")
            env = dict(os.environ, NODE_PATH=args.modules)
            command = ["node", str(scripts / "review_browser.js"), base]
            if args.d11:
                command.append("--d11")
            result = subprocess.run(command, env=env)
            raise SystemExit(result.returncode)
        finally:
            stub.terminate()
            stub.wait(timeout=5)


if __name__ == "__main__":
    main()
