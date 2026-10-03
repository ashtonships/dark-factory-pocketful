import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
from types import SimpleNamespace
import unittest

import attack_stage1


def reset_races(core, server, base):
    client = attack_stage1.Client(base)
    original_authenticate = server.PocketfulHandler.authenticate
    original_meta = server.get_meta
    for path in ("/payments", "/requests/rq_seed/pay", "/requests/rq_seed/cancel"):
        seeded = attack_stage1.fixture()
        seeded["requests"] = [{"id": "rq_seed", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 100, "note": "race", "status": "pending"}]
        assert client.call("POST", "/_test/reset", seeded)[0] == 204
        handle = "bob" if path.endswith("cancel") else "ada"
        token = client.call("POST", "/auth/login", {"email": handle + "@example.com", "password": "correct horse"})[1]["token"]
        authenticated = threading.Event()
        release = threading.Event()

        def paused_authenticate(handler, database):
            user = original_authenticate(handler, database)
            if handler.path == path:
                authenticated.set()
                if not release.wait(10):
                    raise AssertionError("Writer barrier timed out")
            return user

        server.PocketfulHandler.authenticate = paused_authenticate
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                body = {"to_handle": "bob", "amount": 100} if path == "/payments" else {}
                pending = executor.submit(client.call, "POST", path, body, token, "stale-token")
                assert authenticated.wait(5), "Writer did not authenticate"
                assert client.call("POST", "/_test/reset", seeded)[0] == 204
                release.set()
                result = pending.result(5)
                assert result[0] == 401 and result[1]["error"]["code"] == "unauthenticated", result
                with core.connection() as database:
                    assert database.execute("SELECT count(*) FROM payments").fetchone()[0] == 0
                    assert database.execute("SELECT count(*) FROM idempotency").fetchone()[0] == 0
                    assert database.execute("SELECT status FROM requests WHERE id = 'rq_seed'").fetchone()[0] == "pending"
            print("PASS reset invalidates authenticated-but-uncommitted", path)
        finally:
            release.set()
            server.PocketfulHandler.authenticate = original_authenticate

    seeded = attack_stage1.fixture()
    assert client.call("POST", "/_test/reset", seeded)[0] == 204
    token = client.call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[1]["token"]
    reading = threading.Event()
    release = threading.Event()

    def paused_meta(database):
        reading.set()
        if not release.wait(10):
            raise AssertionError("Read barrier timed out")
        return original_meta(database)

    server.get_meta = paused_meta
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(client.call, "GET", "/me", None, token)
            assert reading.wait(5), "Read did not authenticate"
            assert client.call("POST", "/_test/reset", attack_stage1.fixture((7, 0, 0, 0), currency="JPY", minor_units=0))[0] == 204
            release.set()
            status, me = pending.result(5)
            assert status == 200 and (me["balance"], me["currency"], me["minor_units"]) == (10000, "EUR", 2), me
            assert client.call("GET", "/me", token=token)[0] == 401
        print("PASS /me holds one consistent pre-reset snapshot; subsequent reads reject old token")
    finally:
        release.set()
        server.get_meta = original_meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    if not Path("/Volumes/SSD").is_mount():
        raise SystemExit("SSD not mounted; no source-copy fallback")
    with tempfile.TemporaryDirectory(prefix="pf-api-source-", dir="/Volumes/SSD/overflow/darkfactory") as source_directory, tempfile.TemporaryDirectory(prefix="pf-api-state-", dir="/tmp") as state_directory:
        archive = subprocess.Popen(["git", "-C", str(args.repo), "archive", args.revision, "stage-1"], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=archive.stdout, mode="r|") as stream:
            stream.extractall(source_directory, filter="data")
        if archive.wait() != 0:
            raise SystemExit("Pinned source archive failed")
        sys.path.insert(0, str(Path(source_directory) / "stage-1"))
        core = importlib.import_module("core")
        server = importlib.import_module("server")
        core.DATABASE_PATH = str(Path(state_directory) / "wallet.sqlite3")
        core.initialize()
        instance = server.PocketfulServer(("127.0.0.1", 0), server.PocketfulHandler)
        worker = threading.Thread(target=instance.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{instance.server_port}"
        try:
            attack_stage1.OPTIONS = SimpleNamespace(base=base, destination=None, item=2)
            result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(attack_stage1.Attacks))
            reset_races(core, server, base)
            raise SystemExit(0 if result.wasSuccessful() else 1)
        finally:
            instance.shutdown()
            instance.server_close()
            worker.join(5)


if __name__ == "__main__":
    main()
