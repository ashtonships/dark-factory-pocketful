import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import http.client
import json
import socket
import threading
import unittest
from urllib.parse import urlsplit


def loopback_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path not in {"", "/"}:
        raise argparse.ArgumentTypeError("Only isolated loopback HTTP servers are allowed")
    return value.rstrip("/")


def fixture(balances=(10000, 2500, 0, 0), currency="EUR", minor_units=2):
    return {
        "currency": currency,
        "minor_units": minor_units,
        "users": [
            {"id": "u_" + handle, "handle": handle, "email": handle + "@example.com", "password": "correct horse", "display_name": handle.title(), "balance": balance}
            for handle, balance in zip(("ada", "bob", "cy", "op"), balances)
        ],
        "payments": [],
        "requests": [],
        "settlement_operator_ids": ["u_op"],
    }


class Client:
    def __init__(self, base):
        self.url = urlsplit(base)

    def call(self, method, path, body=None, token=None, key=None, raw=None):
        connection = http.client.HTTPConnection(self.url.hostname, self.url.port or 80, timeout=10 if path.startswith("/_test/") else 5)
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if key is not None:
            headers["Idempotency-Key"] = key
        payload = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            content = response.read()
            result = json.loads(content) if content else None
            if response.status >= 500:
                raise AssertionError(f"Unexpected 5xx on {method} {path}: {response.status}")
            return response.status, result
        finally:
            connection.close()


class Attacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = Client(OPTIONS.base)
        cls.destination = Client(OPTIONS.destination or OPTIONS.base)

    def reset(self, balances=(10000, 2500, 0, 0), **kwargs):
        seeded = fixture(balances, **kwargs)
        self.assertEqual(self.client.call("POST", "/_test/reset", seeded)[0], 204)
        self.tokens = {}
        for handle in ("ada", "bob", "cy", "op"):
            status, session = self.client.call("POST", "/auth/login", {"email": handle + "@example.com", "password": "correct horse"})
            self.assertEqual(status, 200)
            self.tokens[handle] = session["token"]
        self.seeded_total = sum(balances)

    def setUp(self):
        self.reset()

    def require(self, work_item):
        if OPTIONS.item < work_item:
            self.skipTest(f"Requires W-{work_item}")

    def error(self, response, status, code):
        self.assertEqual(response[0], status)
        self.assertEqual(response[1]["error"]["code"], code)
        self.assertIsInstance(response[1]["error"]["message"], str)

    def balances(self, client=None):
        target = client or self.client
        values = []
        for token in self.tokens.values():
            status, me = target.call("GET", "/me", token=token)
            self.assertEqual(status, 200)
            self.assertIsInstance(me["balance"], int)
            self.assertGreaterEqual(me["balance"], 0)
            values.append(me["balance"])
        self.assertEqual(sum(values), self.seeded_total)
        return values

    def post(self, path, body, handle="ada", key="attack", client=None):
        return (client or self.client).call("POST", path, body, self.tokens[handle], key)

    def many(self, operations):
        barrier = threading.Barrier(len(operations))
        def execute(operation):
            barrier.wait(timeout=5)
            return operation()
        with ThreadPoolExecutor(max_workers=50) as executor:
            return list(executor.map(execute, operations))

    def feed(self, handle="ada", client=None):
        status, result = (client or self.client).call("GET", "/activity?limit=200", token=self.tokens[handle])
        self.assertEqual(status, 200)
        return result["payments"]

    def test_reset_failure_replacement_and_seeded_net_balance(self):
        seeded = fixture()
        seeded["payments"] = [{"id": "seeded", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500, "note": "already applied", "visibility": "public"}]
        self.assertEqual(self.client.call("POST", "/_test/reset", seeded)[0], 204)
        self.tokens = {handle: self.client.call("POST", "/auth/login", {"email": handle + "@example.com", "password": "correct horse"})[1]["token"] for handle in ("ada", "bob", "cy", "op")}
        bad = fixture()
        bad["users"][0]["balance"] = -1
        self.error(self.client.call("POST", "/_test/reset", bad), 422, "validation_failed")
        self.assertEqual(self.balances(), [10000, 2500, 0, 0])
        old_token = self.tokens["ada"]
        self.reset(currency="JPY", minor_units=0)
        self.error(self.client.call("GET", "/me", token=old_token), 401, "unauthenticated")
        self.assertEqual(self.client.call("GET", "/health"), (200, {"status": "ok"}))

    def test_auth_signup_collision_and_strict_json(self):
        body = {"email": "New.Person@example.com", "password": "correct horse", "display_name": "New", "ignored": {"anything": True}}
        results = self.many([lambda: self.client.call("POST", "/auth/signup", body)] * 50)
        self.assertEqual(sum(status == 201 for status, result in results), 1)
        for status, result in results:
            if status != 201:
                self.error((status, result), 409, "email_taken")
        token = next(result["token"] for status, result in results if status == 201)
        status, me = self.client.call("GET", "/me", token=token)
        self.assertEqual((status, me["handle"], me["balance"]), (200, "new_person", 0))
        self.error(self.client.call("POST", "/auth/signup", {"email": "new_person@other.example", "password": "correct horse", "display_name": "Collision"}), 409, "handle_taken")
        for raw in [b'{"email":NaN}', b'{"email":Infinity}', b'{"email":-Infinity}', b'{"email":"\xff"}', '{"email":"ada@example.com","password":"correct horse"}'.encode("utf-16")]:
            self.error(self.client.call("POST", "/auth/login", raw=raw), 400, "malformed_request")
        self.balances()

    def test_http_chunked_and_rejected_body_keepalive(self):
        connection = http.client.HTTPConnection(self.client.url.hostname, self.client.url.port, timeout=5)
        try:
            connection.request("POST", "/auth/login", body=iter([b'{"email":"ada@example.com",', b'"password":"correct horse"}']), headers={"Content-Type": "application/json"}, encode_chunked=True)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            session = json.loads(response.read())
            connection.request("POST", "/_test/reset", body=b"{", headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            connection.request("GET", "/me", headers={"Authorization": "Bearer " + session["token"]})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["balance"], 10000)
        finally:
            connection.close()

    def test_numeric_boundaries_notes_and_query_grammar(self):
        self.require(2)
        note = "😀" * 200
        for index, literal in enumerate(["1000", "1000.0", "1e3"]):
            raw = ('{"to_handle":"bob","amount":' + literal + ',"note":' + json.dumps(note) + '}').encode()
            status, payment = self.client.call("POST", "/payments", token=self.tokens["ada"], key=str(index), raw=raw)
            self.assertEqual(status, 201)
            self.assertEqual(payment["amount"], 1000)
            self.assertEqual(payment["note"], note)
        for invalid in [True, False, "1", None, 0, -1, 1.5, 1000000001]:
            self.error(self.post("/payments", {"to_handle": "bob", "amount": invalid}, key="invalid"), 422, "validation_failed")
        for field, value in [("note", None), ("note", 5), ("note", "😀" * 201), ("visibility", None), ("visibility", "PUBLIC")]:
            self.error(self.post("/payments", {"to_handle": "bob", "amount": 1, field: value}, key="invalid"), 422, "validation_failed")
        for endpoint in ["/activity", "/requests"]:
            for query in ["limit=1e2", "limit=4.0", "limit=%2B4", "limit=0", "limit=201", "offset=-1"]:
                self.error(self.client.call("GET", endpoint + "?" + query, token=self.tokens["ada"]), 422, "validation_failed")
            self.assertEqual(self.client.call("GET", endpoint + "?limit=1&offset=999&ignored=anything", token=self.tokens["ada"])[1]["has_more"], False)
        self.balances()

    def test_concurrent_identical_payment_and_conflicting_key(self):
        self.require(2)
        body = {"to_handle": "bob", "amount": 100, "note": "once"}
        results = self.many([lambda: self.post("/payments", body)] * 50)
        self.assertEqual([status for status, result in results].count(201), 1)
        self.assertEqual([status for status, result in results].count(200), 49)
        self.assertTrue(all(result == results[0][1] for status, result in results))
        self.assertEqual(self.balances(), [9900, 2600, 0, 0])
        self.assertEqual(len(self.feed()), 1)
        self.error(self.post("/payments", {"amount": False}), 409, "idempotency_key_reuse")
        self.reset()
        operations = [lambda amount=amount: self.post("/payments", {"to_handle": "bob", "amount": amount}) for amount in [1, 2] * 25]
        results = self.many(operations)
        statuses = [status for status, result in results]
        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(statuses.count(200), 24)
        self.assertEqual(statuses.count(409), 25)
        self.balances()

    def test_concurrent_overspend_and_request_terminal_race(self):
        self.require(2)
        self.reset((5000, 0, 0, 0))
        results = self.many([lambda index=index: self.post("/payments", {"to_handle": "bob", "amount": 1000}, key=str(index)) for index in range(50)])
        self.assertEqual(sum(status == 201 for status, result in results), 5)
        for status, result in results:
            if status != 201:
                self.error((status, result), 409, "insufficient_funds")
        self.assertEqual(self.balances(), [0, 5000, 0, 0])
        self.reset()
        status, request = self.post("/requests", {"payer_handle": "ada", "amount": 500}, handle="bob")
        self.assertEqual(status, 201)
        path = "/requests/" + request["request_id"]
        operations = []
        for index in range(48):
            kind = ["pay", "decline", "cancel"][index % 3]
            operations.append(lambda kind=kind, index=index: self.post(path + "/" + kind, {}, handle="bob" if kind == "cancel" else "ada", key=str(index)))
        self.many(operations)
        status, listing = self.client.call("GET", "/requests", token=self.tokens["ada"])
        terminal = listing["requests"][0]
        self.assertIn(terminal["status"], ["paid", "cancelled", "declined"])
        payments = self.feed()
        self.assertEqual(len(payments), int(terminal["status"] == "paid"))
        self.assertEqual(self.balances(), [9500, 3000, 0, 0] if terminal["status"] == "paid" else [10000, 2500, 0, 0])

    def test_retry_json_equality_user_path_scope_and_failed_key(self):
        self.require(2)
        body = {"to_handle": "bob", "amount": 1000, "unknown": {"nested": [True, None, 1]}}
        original = self.post("/payments", body)
        raw = b'{"unknown":{"nested":[true,null,1.0]},"amount":1e3,"to_handle":"bob"}'
        replay = self.client.call("POST", "/payments", token=self.tokens["ada"], key="attack", raw=raw)
        self.assertEqual(replay, (200, original[1]))
        changed = copy.deepcopy(body)
        changed["unknown"]["nested"][0] = 1
        self.error(self.post("/payments", changed), 409, "idempotency_key_reuse")
        self.assertEqual(self.post("/payments", {"to_handle": "ada", "amount": 1}, handle="bob")[0], 201)
        shared = {"to_handle": "bob", "payer_handle": "bob", "amount": 1}
        self.assertEqual(self.post("/payments", shared, key="paths")[0], 201)
        self.assertEqual(self.post("/requests", shared, key="paths")[0], 201)
        self.error(self.post("/payments", {"to_handle": "ada", "amount": 1}, key="failed"), 422, "self_payment")
        self.assertEqual(self.post("/payments", {"to_handle": "bob", "amount": 1}, key="failed")[0], 201)
        self.balances()

    def test_request_concurrent_pay_and_create_replay_after_cancel(self):
        self.require(2)
        body = {"payer_handle": "ada", "amount": 100, "note": "one request"}
        status, request = self.post("/requests", body, handle="bob", key="create")
        self.assertEqual(status, 201)
        pay_path = "/requests/" + request["request_id"] + "/pay"
        results = self.many([lambda: self.post(pay_path, {}, key="pay")] * 50)
        self.assertEqual(sum(status == 201 for status, result in results), 1)
        self.assertEqual(sum(status == 200 for status, result in results), 49)
        receipt = next(result for status, result in results if status == 201)
        self.assertTrue(all(result == receipt for status, result in results))
        self.assertEqual(self.balances(), [9900, 2600, 0, 0])
        status, pending = self.post("/requests", body, handle="bob", key="cancel-create")
        self.assertEqual(status, 201)
        self.assertEqual(self.post("/requests/" + pending["request_id"] + "/cancel", {}, handle="bob")[0], 200)
        self.assertEqual(self.post("/requests", body, handle="bob", key="cancel-create"), (200, pending))
        self.balances()

    def test_large_exact_balance_and_single_amount_maximum(self):
        self.require(2)
        initial = 2 ** 53 - 1000000000
        self.reset((initial, 1000000000, 0, 0))
        self.assertEqual(self.post("/payments", {"to_handle": "bob", "amount": 1000000000}, key="max")[0], 201)
        self.assertEqual(self.balances(), [initial - 1000000000, 2000000000, 0, 0])
        self.reset((2 ** 53, 0, 0, 0))
        self.assertEqual(self.balances(), [2 ** 53, 0, 0, 0])

    def test_concurrent_different_keys_pay_once(self):
        self.require(2)
        status, request = self.post("/requests", {"payer_handle": "ada", "amount": 100}, handle="bob", key="new-request")
        self.assertEqual(status, 201)
        path = "/requests/" + request["request_id"] + "/pay"
        results = self.many([lambda index=index: self.post(path, {}, key="pay-" + str(index)) for index in range(50)])
        self.assertEqual(sum(status == 201 for status, result in results), 1)
        for status, result in results:
            if status != 201:
                self.error((status, result), 409, "request_not_pending")
        self.assertEqual(self.balances(), [9900, 2600, 0, 0])
        self.assertEqual(len(self.feed()), 1)

    def test_overflow_failure_preserves_wallets_feed_and_failed_key(self):
        self.require(2)
        self.reset((10, 2 ** 53, 0, 0))
        self.error(self.post("/payments", {"to_handle": "bob", "amount": 1}, key="overflow"), 422, "validation_failed")
        self.assertEqual(self.balances(), [10, 2 ** 53, 0, 0])
        self.assertEqual(self.feed(), [])
        self.assertEqual(self.post("/payments", {"to_handle": "cy", "amount": 1}, key="overflow")[0], 201)
        self.assertEqual(self.balances(), [9, 2 ** 53, 1, 0])
        self.assertEqual(len(self.feed()), 1)

    def test_request_short_then_funded_paid_and_privacy(self):
        self.require(2)
        status, request = self.post("/requests", {"payer_handle": "cy", "amount": 10}, handle="bob", key="request")
        self.assertEqual(status, 201)
        pay_path = "/requests/" + request["request_id"] + "/pay"
        self.error(self.post(pay_path, {}, handle="cy", key="retry"), 409, "insufficient_funds")
        self.post("/payments", {"to_handle": "cy", "amount": 10, "visibility": "private"}, key="fund")
        status, payment = self.post(pay_path, {"visibility": "private"}, handle="cy", key="retry")
        self.assertEqual(status, 201)
        self.assertEqual(self.post(pay_path, {"visibility": "private"}, handle="cy", key="retry"), (200, payment))
        self.error(self.post(pay_path, {}, handle="cy", key="retry"), 409, "idempotency_key_reuse")
        self.assertEqual(len(self.feed("op")), 0)
        self.assertEqual(len(self.feed("bob")), 1)
        self.balances()

    def test_split_remainders_zero_requests_and_caller_omission(self):
        self.require(3)
        for amount in [1, 5, 10, 999, 1000, 1000000000]:
            for handles in [["ada", "bob", "cy"], ["cy", "bob", "ada"], ["bob", "cy"], ["ada"]]:
                key = str(amount) + ":" + ",".join(handles)
                status, split = self.post("/splits", {"amount": amount, "participant_handles": handles}, key=key)
                self.assertEqual(status, 201)
                expected = [{"handle": handle, "amount": amount // len(handles) + int(index < amount % len(handles))} for index, handle in enumerate(handles)]
                self.assertEqual(split["shares"], expected)
                self.assertEqual([request["payer_handle"] for request in split["requests"]], [handle for handle in handles if handle != "ada"])
                self.assertEqual(self.post("/splits", {"amount": amount, "participant_handles": handles}, key=key), (200, split))
                self.balances()
        self.reset()
        status, split = self.post("/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]})
        for request in split["requests"]:
            self.assertEqual(request["amount"], 0)
            path = "/requests/" + request["request_id"] + "/pay"
            self.assertEqual(self.post(path, {}, handle=request["payer_handle"], key=request["request_id"])[0], 201)
            self.balances()

    def test_settlement_net_funding_atomic_errors_and_replay(self):
        self.require(4)
        self.reset((0, 100, 0, 0))
        transfers = [{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "ada", "amount": 100, "visibility": "private"}]
        status, settlement = self.post("/settlements", {"transfers": transfers}, handle="op")
        self.assertEqual(status, 201)
        self.assertEqual(self.balances(), [0, 100, 0, 0])
        self.assertEqual([payment["from_handle"] for payment in settlement["payments"]], ["ada", "bob"])
        self.assertTrue(all(payment["created_at"] == settlement["committed_at"] and payment["settlement_id"] == settlement["settlement_id"] and payment["request_id"] is None for payment in settlement["payments"]))
        self.assertEqual(self.post("/settlements", {"transfers": transfers}, handle="op"), (200, settlement))
        results = self.many([lambda: self.post("/settlements", {"transfers": transfers}, handle="op", key="concurrent")] * 50)
        self.assertEqual(sum(status == 201 for status, result in results), 1)
        self.assertEqual(sum(status == 200 for status, result in results), 49)
        self.assertTrue(all(result == results[0][1] for status, result in results))
        before = self.feed()
        bad = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 101}, {"from_handle": "missing", "to_handle": "bob", "amount": 1}]}
        self.error(self.post("/settlements", bad, handle="op", key="bad"), 404, "not_found")
        self.assertEqual(self.feed(), before)
        self.assertEqual(self.post("/settlements", {"transfers": transfers}, handle="op", key="bad")[0], 201)
        self.error(self.post("/settlements", {"transfers": transfers}), 403, "forbidden")
        self.balances()

    def test_export_import_snapshot_receipts_credentials_and_failed_keys(self):
        self.require(4)
        writes = []
        def save(path, body, handle, key):
            status, result = self.post(path, body, handle=handle, key=key)
            self.assertEqual(status, 201)
            writes.append((path, body, handle, key, result))
            return result
        save("/payments", {"to_handle": "bob", "amount": 100, "visibility": "private"}, "ada", "lost-reply")
        request = save("/requests", {"payer_handle": "ada", "amount": 1}, "bob", "pending")
        paid = save("/requests", {"payer_handle": "ada", "amount": 2}, "bob", "paid-create")
        save("/requests/" + paid["request_id"] + "/pay", {}, "ada", "paid")
        save("/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]}, "ada", "split")
        save("/settlements", {"transfers": [{"from_handle": "bob", "to_handle": "cy", "amount": 1}]}, "op", "settlement")
        self.error(self.post("/payments", {"to_handle": "bob", "amount": 0}, key="failed"), 422, "validation_failed")
        balances = self.balances()
        feeds = {handle: self.feed(handle) for handle in self.tokens}
        status, snapshot = self.client.call("GET", "/_test/export")
        self.assertEqual(status, 200)
        self.assertEqual(snapshot["track"], "pocketful")
        self.assertEqual(snapshot["format_version"], 1)
        saved_snapshot = copy.deepcopy(snapshot)
        self.post("/payments", {"to_handle": "bob", "amount": 3}, key="after-export")
        self.assertEqual(snapshot, saved_snapshot)
        destination_fixture = fixture()
        destination_fixture["users"] = [{"id": "u_dest", "email": "dest@example.com", "password": "correct horse", "display_name": "Destination", "handle": "dest", "balance": 1}]
        destination_fixture["settlement_operator_ids"] = []
        self.assertEqual(self.destination.call("POST", "/_test/reset", destination_fixture)[0], 204)
        status, session = self.destination.call("POST", "/auth/login", {"email": "dest@example.com", "password": "correct horse"})
        self.assertEqual(status, 200)
        for iteration in range(2):
            self.assertEqual(self.destination.call("POST", "/_test/import", snapshot)[0], 204)
            self.assertEqual(self.balances(self.destination), balances)
            self.error(self.destination.call("GET", "/me", token=session["token"]), 401, "unauthenticated")
            for handle in self.tokens:
                self.assertEqual(self.feed(handle, self.destination), feeds[handle])
            for path, body, handle, key, receipt in writes:
                self.assertEqual(self.post(path, body, handle, key, self.destination), (200, receipt))
            self.assertEqual(self.destination.call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})[0], 200)
        invalid = copy.deepcopy(snapshot)
        invalid["track"] = "other"
        self.error(self.destination.call("POST", "/_test/import", invalid), 422, "validation_failed")
        self.assertEqual(self.balances(self.destination), balances)
        self.assertEqual(self.post("/payments", {"to_handle": "bob", "amount": 1}, key="failed", client=self.destination)[0], 201)
        self.assertEqual(self.post("/requests/" + request["request_id"] + "/pay", {}, key="after-upgrade", client=self.destination)[0], 201)
        self.balances(self.destination)

    def test_commit_with_dropped_response_retries_once(self):
        self.require(2)
        body = json.dumps({"to_handle": "bob", "amount": 100}).encode()
        request = ("POST /payments HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nAuthorization: Bearer " + self.tokens["ada"] + "\r\nIdempotency-Key: dropped\r\nContent-Length: " + str(len(body)) + "\r\nConnection: close\r\n\r\n").encode() + body
        with socket.create_connection((self.client.url.hostname, self.client.url.port), timeout=5) as connection:
            connection.sendall(request)
            connection.recv(1)
        status, receipt = self.post("/payments", {"to_handle": "bob", "amount": 100}, key="dropped")
        self.assertEqual(status, 200)
        self.assertEqual(receipt["amount"], 100)
        self.assertEqual(self.balances(), [9900, 2600, 0, 0])
        self.assertEqual(len(self.feed()), 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Destructive retained attacks against isolated services; never use production state")
    parser.add_argument("--base", type=loopback_url, required=True)
    parser.add_argument("--destination", type=loopback_url)
    parser.add_argument("--item", type=int, choices=[1, 2, 3, 4], default=4)
    parser.add_argument("--case", help="Exact unittest method name for one reproduction")
    OPTIONS = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromName(OPTIONS.case, Attacks) if OPTIONS.case else unittest.defaultTestLoader.loadTestsFromTestCase(Attacks)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
