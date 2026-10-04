import json
import os
import re
import socket
from datetime import timedelta
from pathlib import Path
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from core import (
    APIError, HANDLE_PATTERN, MAX_BALANCE, WRITE_LOCK, amount, canonical_body, check_password,
    connection, derived_handle, email_key, get_meta, hash_password, initialize,
    malformed, new_id, new_token, note, payment_body, request_body, required_string,
    reset, timestamp, valid_email, validation, visibility, write_transaction,
)
from state import export_state, import_state
from history_store import baseline, original
from corrections import correct, revisions
from history import instant, parse_instant
from holds import STATUSES, authorization_body, capture_value, clock, effective_status, expiry, lifetime, record_event, wallet_funds


MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_OFFSET = 2**63 - 1
REQUEST_ACTION = re.compile(r"^/requests/([^/]+)/(pay|decline|cancel)$")
AUTHORIZATION_ACTION = re.compile(r"^/authorizations/([^/]+)/(capture|void)$")
PAYMENT_HISTORY = re.compile(r"^/payments/([^/]+)/(corrections|revisions)$")
UI_ROOT = Path(__file__).resolve().parent / "ui"
PAGES = {"/": "index.html", "/requests": "requests.html", "/split": "split.html", "/signup": "signup.html", "/login": "login.html", "/authorizations": "authorizations.html"}
ASSETS = {"/ui/pocketful-core.js": ("pocketful-core.js", "text/javascript; charset=utf-8"), "/ui/app.js": ("app.js", "text/javascript; charset=utf-8"), "/ui/theme.css": ("theme.css", "text/css; charset=utf-8")}
ROUTES = {
    "/health": {"GET"},
    "/_test/reset": {"POST"},
    "/_test/export": {"GET"},
    "/_test/import": {"POST"},
    "/auth/signup": {"POST"},
    "/auth/login": {"POST"},
    "/me": {"GET"},
    "/payments": {"POST"},
    "/requests": {"GET", "POST"},
    "/splits": {"POST"},
    "/activity": {"GET"},
    "/settlements": {"POST"},
    "/authorizations": {"GET", "POST"},
}


def json_body(data):
    try:
        decoded = data.decode("utf-8", errors="strict")
        value = json.loads(decoded, parse_int=Decimal, parse_float=Decimal, parse_constant=lambda _: malformed())
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError, InvalidOperation, RecursionError):
        malformed()
    if not isinstance(value, dict):
        malformed("Body must be a JSON object")
    def contains_surrogate(item):
        if isinstance(item, str):
            return any(0xD800 <= ord(character) <= 0xDFFF for character in item)
        if isinstance(item, list):
            return any(contains_surrogate(element) for element in item)
        if isinstance(item, dict):
            return any(contains_surrogate(key) or contains_surrogate(element) for key, element in item.items())
        return False
    if contains_surrogate(value):
        malformed("Invalid Unicode")
    return value


class PocketfulHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Pocketful/3"

    def serve_ui(self, path):
        asset = ASSETS.get(path)
        if asset is None and path in PAGES and "text/html" in self.headers.get("Accept", "").lower():
            asset = (PAGES[path], "text/html; charset=utf-8")
        if asset is None:
            return False
        filename, content_type = asset
        try:
            payload = (UI_ROOT / filename).read_bytes()
        except FileNotFoundError:
            raise APIError(404, "not_found")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        return True

    def log_message(self, format_string, *args):
        return

    def send_json(self, status, value=None):
        payload = b"" if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if payload and self.command != "HEAD":
            self.wfile.write(payload)

    def send_api_error(self, error):
        self.send_json(error.status, {"error": {"code": error.code, "message": error.message}})

    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        self.send_api_error(APIError(405 if code == 501 else code, "method_not_allowed" if code == 501 else "malformed_request", message))

    def _read_exact(self, length):
        data = self.rfile.read(length)
        if len(data) != length:
            self.close_connection = True
            malformed("Incomplete request body")
        return data

    def read_body(self):
        self.body_too_large = False
        transfer_encoding = self.headers.get("Transfer-Encoding", "").lower()
        if transfer_encoding:
            encodings = [part.strip() for part in transfer_encoding.split(",")]
            if encodings != ["chunked"]:
                self.close_connection = True
                malformed("Unsupported transfer encoding")
            chunks = []
            total = 0
            too_large = False
            while True:
                line = self.rfile.readline(8193)
                if not line.endswith(b"\r\n") or len(line) > 8192:
                    self.close_connection = True
                    malformed("Invalid chunk header")
                try:
                    chunk_size = int(line[:-2].split(b";", 1)[0], 16)
                except ValueError:
                    self.close_connection = True
                    malformed("Invalid chunk size")
                if chunk_size < 0:
                    self.close_connection = True
                    malformed("Invalid chunk size")
                if chunk_size == 0:
                    while True:
                        trailer = self.rfile.readline(8193)
                        if trailer == b"\r\n":
                            break
                        if not trailer.endswith(b"\r\n") or len(trailer) > 8192:
                            self.close_connection = True
                            malformed("Invalid chunk trailer")
                    break
                remaining = chunk_size
                while remaining:
                    piece = self._read_exact(min(remaining, 65536))
                    total += len(piece)
                    if total <= MAX_BODY_BYTES:
                        chunks.append(piece)
                    else:
                        too_large = True
                    remaining -= len(piece)
                if self._read_exact(2) != b"\r\n":
                    self.close_connection = True
                    malformed("Invalid chunk terminator")
            if too_large:
                self.body_too_large = True
            return b"".join(chunks)
        length_text = self.headers.get("Content-Length")
        if length_text is None:
            return b""
        if len(length_text) > 20 or not re.fullmatch(r"[0-9]+", length_text):
            self.close_connection = True
            malformed("Invalid Content-Length")
        length = int(length_text)
        chunks = []
        remaining = length
        while remaining:
            piece = self._read_exact(min(remaining, 65536))
            if length <= MAX_BODY_BYTES:
                chunks.append(piece)
            remaining -= len(piece)
        if length > MAX_BODY_BYTES:
            self.body_too_large = True
        return b"".join(chunks)

    def route_info(self, path):
        if path in ROUTES:
            return ROUTES[path]
        if REQUEST_ACTION.fullmatch(path) or AUTHORIZATION_ACTION.fullmatch(path):
            return {"POST"}
        history_action = PAYMENT_HISTORY.fullmatch(path)
        if history_action:
            return {"GET"} if history_action.group(2) == "revisions" else {"POST"}
        if path in PAGES or path in ASSETS:
            return {"GET"}
        return None

    def authenticate(self, db):
        authorization = self.headers.get("Authorization", "")
        match = re.fullmatch(r"Bearer ([A-Za-z0-9_-]+)", authorization)
        if not match:
            raise APIError(401, "unauthenticated")
        user = db.execute("SELECT users.* FROM users JOIN tokens ON tokens.user_id = users.id WHERE tokens.token = ?", (match.group(1),)).fetchone()
        if user is None:
            raise APIError(401, "unauthenticated")
        return user

    def current_user(self, db, user):
        authorization = self.headers.get("Authorization", "")
        token = authorization.removeprefix("Bearer ")
        current = db.execute(
            "SELECT users.* FROM users JOIN tokens ON tokens.user_id = users.id WHERE users.id = ? AND tokens.token = ?",
            (user["id"], token),
        ).fetchone()
        if current is None:
            raise APIError(401, "unauthenticated")
        return current

    def idempotent(self, db, user, path, body, operation):
        key = self.headers.get("Idempotency-Key")
        if key is None or key == "":
            raise APIError(400, "missing_idempotency_key")
        if len(key) > 255:
            validation("Idempotency key is too long")
        body_json = canonical_body(body)
        with write_transaction(db):
            user = self.current_user(db, user)
            prior = db.execute(
                "SELECT body_json, response_json FROM idempotency WHERE user_id = ? AND key = ? AND method = ? AND path = ?",
                (user["id"], key, self.command, path),
            ).fetchone()
            if prior is not None:
                if prior["body_json"] != body_json:
                    raise APIError(409, "idempotency_key_reuse")
                result = json.loads(prior["response_json"])
                status = 200
            else:
                self.now = clock()
                result = operation(db, user, body)
                db.execute("UPDATE meta SET value=? WHERE key='clock_high_water'", (self.now.isoformat(),))
                db.execute(
                    "INSERT INTO idempotency VALUES(?, ?, ?, ?, ?, ?)",
                    (user["id"], key, self.command, path, body_json, json.dumps(result, ensure_ascii=False, separators=(",", ":"))),
                )
                status = 201
        self.send_json(status, result)

    def pagination(self):
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        limit_text = query.get("limit", ["50"])[-1]
        offset_text = query.get("offset", ["0"])[-1]
        if not re.fullmatch(r"[0-9]+", limit_text) or not re.fullmatch(r"[0-9]+", offset_text):
            validation("Invalid pagination")
        significant_limit = limit_text.lstrip("0") or "0"
        if len(significant_limit) > 3 or not 1 <= int(significant_limit) <= 200:
            validation("Invalid limit")
        limit = int(significant_limit)
        significant_offset = offset_text.lstrip("0") or "0"
        offset = min(int(significant_offset), MAX_OFFSET) if len(significant_offset) <= len(str(MAX_OFFSET)) else MAX_OFFSET
        return query, limit, offset

    def dispatch(self):
        self.connection.settimeout(10 if urlsplit(self.path).path in ("/_test/reset", "/_test/import", "/_test/export") else 5)
        try:
            try:
                raw_body = self.read_body()
            finally:
                # Body deadlines must not expire an idle reusable connection.
                self.connection.settimeout(None)
            path = urlsplit(self.path).path
            methods = self.route_info(path)
            if methods is None:
                raise APIError(404, "not_found")
            if self.command not in methods:
                raise APIError(405, "method_not_allowed")
            if self.command == "GET" and self.serve_ui(path):
                return
            db = connection()
            try:
                if path == "/health":
                    db.execute("SELECT 1 FROM meta LIMIT 1").fetchone()
                    self.send_json(200, {"status": "ok"})
                    return
                if path == "/_test/reset":
                    if self.body_too_large:
                        validation("Body is too large")
                    reset(db, json_body(raw_body))
                    self.send_json(204)
                    return
                if path == "/_test/export":
                    self.send_json(200, export_state(db))
                    return
                if path == "/_test/import":
                    if self.body_too_large:
                        validation("Body is too large")
                    import_state(db, json_body(raw_body))
                    self.send_json(204)
                    return
                if path in ("/auth/signup", "/auth/login"):
                    if self.body_too_large:
                        validation("Body is too large")
                    body = json_body(raw_body)
                    if path == "/auth/signup":
                        self.signup(db, body)
                    else:
                        self.login(db, body)
                    return
                if self.command == "GET":
                    WRITE_LOCK.acquire()
                    try:
                        db.execute("BEGIN")
                        try:
                            user = self.authenticate(db)
                            self.now = clock()
                            if path == "/me":
                                meta = get_meta(db)
                                result = {
                                    "user_id": user["id"], "display_name": user["display_name"],
                                    "handle": user["handle"], "balance": user["balance"],
                                    "currency": meta["currency"], "minor_units": int(meta["minor_units"]),
                                }
                                result.update(wallet_funds(db, user["id"], user["balance"], self.now))
                            elif path == "/requests":
                                result = self.list_requests(db, user)
                            elif path == "/activity":
                                result = self.activity(db, user)
                            elif path == "/authorizations":
                                result = self.list_authorizations(db, user)
                            elif PAYMENT_HISTORY.fullmatch(path):
                                result = revisions(db,user,PAYMENT_HISTORY.fullmatch(path).group(1))
                            else:
                                raise APIError(404, "not_found")
                            db.execute("COMMIT")
                        except BaseException:
                            db.execute("ROLLBACK")
                            raise
                    finally:
                        WRITE_LOCK.release()
                    self.send_json(200, result)
                    return
                user = self.authenticate(db)
                if self.body_too_large:
                    validation("Body is too large")
                action = REQUEST_ACTION.fullmatch(path)
                authorization_action = AUTHORIZATION_ACTION.fullmatch(path)
                if authorization_action and authorization_action.group(2) == "void":
                    if raw_body:
                        json_body(raw_body)
                    self.void_authorization(db, user, authorization_action.group(1))
                    return
                if action and action.group(2) in ("decline", "cancel"):
                    if raw_body:
                        json_body(raw_body)
                    self.transition_request(db, user, action.group(1), action.group(2))
                    return
                body = json_body(raw_body)
                history_action = PAYMENT_HISTORY.fullmatch(path)
                if history_action:
                    self.idempotent(db,user,path,body,lambda db,user,body:correct(self,db,user,body,history_action.group(1)))
                    return
                if path == "/authorizations":
                    self.idempotent(db, user, path, body, self.create_authorization)
                    return
                if authorization_action and authorization_action.group(2) == "capture":
                    self.idempotent(db, user, path, body, lambda db, user, body: self.capture_authorization(db, user, body, authorization_action.group(1)))
                    return
                if path == "/payments":
                    self.idempotent(db, user, path, body, self.create_payment)
                    return
                if path == "/requests":
                    self.idempotent(db, user, path, body, self.create_request)
                    return
                if path == "/splits":
                    self.idempotent(db, user, path, body, self.create_split)
                    return
                if path == "/settlements":
                    if db.execute("SELECT 1 FROM operators WHERE user_id = ?", (user["id"],)).fetchone() is None:
                        raise APIError(403, "forbidden")
                    self.idempotent(db, user, path, body, self.create_settlement)
                    return
                if action and action.group(2) == "pay":
                    self.idempotent(db, user, path, body, lambda db, user, body: self.pay_request(db, user, body, action.group(1)))
                    return
                raise APIError(404, "not_found")
            finally:
                db.close()
        except APIError as error:
            self.send_api_error(error)
        except RecursionError:
            self.send_api_error(APIError(400, "malformed_request", "JSON nesting is too deep"))
        except (socket.timeout, TimeoutError):
            self.close_connection = True
            self.send_api_error(APIError(400, "malformed_request", "Timed out reading request"))
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def signup(self, db, body):
        email = required_string(body, "email")
        password = required_string(body, "password")
        display_name = required_string(body, "display_name")
        if not valid_email(email) or len(password) < 8:
            validation("Invalid email or password")
        handle = derived_handle(email)
        if not HANDLE_PATTERN.fullmatch(handle):
            validation("Email cannot form a handle")
        salt, digest = hash_password(password)
        with write_transaction(db):
            if db.execute("SELECT 1 FROM users WHERE email_key = ?", (email_key(email),)).fetchone():
                raise APIError(409, "email_taken")
            if db.execute("SELECT 1 FROM users WHERE handle = ?", (handle,)).fetchone():
                raise APIError(409, "handle_taken")
            user_id = new_id("u_")
            token = new_token()
            db.execute("INSERT INTO users VALUES(?, ?, ?, ?, ?, 0, ?, ?)", (user_id, email, email_key(email), display_name, handle, salt, digest))
            db.execute("INSERT INTO tokens VALUES(?, ?)", (token, user_id))
            db.execute("INSERT INTO wallet_openings VALUES(?,0)", (user_id,))
        self.send_json(201, {"user_id": user_id, "display_name": display_name, "token": token})

    def login(self, db, body):
        email = required_string(body, "email")
        password = required_string(body, "password")
        if not valid_email(email):
            validation("Invalid email")
        user = db.execute("SELECT * FROM users WHERE email_key = ?", (email_key(email),)).fetchone()
        if user is None or not check_password(password, user["password_salt"], user["password_hash"]):
            raise APIError(401, "unauthenticated")
        token = new_token()
        # SQLite excludes reset/import writers; recheck credentials before insertion.
        # No process lock is needed for this token-only transaction.
        with write_transaction(db, serialize=False):
            current = db.execute("SELECT 1 FROM users WHERE id = ? AND password_hash = ?", (user["id"], user["password_hash"])).fetchone()
            if current is None:
                raise APIError(401, "unauthenticated")
            db.execute("INSERT INTO tokens VALUES(?, ?)", (token, user["id"]))
        self.send_json(200, {"user_id": user["id"], "display_name": user["display_name"], "token": token})

    def create_payment(self, db, user, body):
        to_handle = required_string(body, "to_handle")
        value = amount(body)
        payment_note = note(body)
        payment_visibility = visibility(body)
        if not HANDLE_PATTERN.fullmatch(to_handle):
            validation("Invalid handle")
        if to_handle == user["handle"]:
            raise APIError(422, "self_payment")
        target = db.execute("SELECT * FROM users WHERE handle = ?", (to_handle,)).fetchone()
        if target is None:
            raise APIError(404, "not_found")
        if wallet_funds(db, user["id"], user["balance"], self.now)["available"] < value:
            raise APIError(409, "insufficient_funds")
        if target["balance"] + value > MAX_BALANCE:
            validation("Balance limit exceeded")
        db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (value, user["id"]))
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (value, target["id"]))
        payment_id = new_id("p_")
        db.execute(
            "INSERT INTO payments(id, from_user_id, to_user_id, amount, note, visibility, request_id, settlement_id, created_at) VALUES(?, ?, ?, ?, ?, ?, NULL, NULL, ?)",
            (payment_id, user["id"], target["id"], value, payment_note, payment_visibility, self.now.isoformat()),
        )
        original(db,payment_id)
        row = db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        return payment_body(db, row)

    def create_request(self, db, user, body):
        payer_handle = required_string(body, "payer_handle")
        value = amount(body)
        request_note = note(body)
        if not HANDLE_PATTERN.fullmatch(payer_handle):
            validation("Invalid handle")
        if payer_handle == user["handle"]:
            raise APIError(422, "self_request")
        payer = db.execute("SELECT * FROM users WHERE handle = ?", (payer_handle,)).fetchone()
        if payer is None:
            raise APIError(404, "not_found")
        request_id = new_id("rq_")
        db.execute(
            "INSERT INTO requests(id, requester_id, payer_id, amount, note, status, payment_id, created_at) VALUES(?, ?, ?, ?, ?, 'pending', NULL, ?)",
            (request_id, user["id"], payer["id"], value, request_note, self.now.isoformat()),
        )
        row = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        return request_body(db, row)

    def pay_request(self, db, user, body, request_id):
        payment_visibility = visibility(body)
        request = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if request is None:
            raise APIError(404, "not_found")
        if request["payer_id"] != user["id"]:
            raise APIError(403, "forbidden")
        if request["status"] != "pending":
            raise APIError(409, "request_not_pending")
        if wallet_funds(db, user["id"], user["balance"], self.now)["available"] < request["amount"]:
            raise APIError(409, "insufficient_funds")
        receiver = db.execute("SELECT * FROM users WHERE id = ?", (request["requester_id"],)).fetchone()
        if receiver is None:
            raise APIError(404, "not_found")
        if receiver["balance"] + request["amount"] > MAX_BALANCE:
            validation("Balance limit exceeded")
        db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (request["amount"], user["id"]))
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (request["amount"], receiver["id"]))
        payment_id = new_id("p_")
        db.execute(
            "INSERT INTO payments(id, from_user_id, to_user_id, amount, note, visibility, request_id, settlement_id, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, NULL, ?)",
            (payment_id, user["id"], receiver["id"], request["amount"], request["note"], payment_visibility, request_id, self.now.isoformat()),
        )
        original(db,payment_id)
        db.execute("UPDATE requests SET status = 'paid', payment_id = ? WHERE id = ?", (payment_id, request_id))
        row = db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        return payment_body(db, row)

    def transition_request(self, db, user, request_id, action):
        desired_status = "declined" if action == "decline" else "cancelled"
        owner_field = "payer_id" if action == "decline" else "requester_id"
        with write_transaction(db):
            user = self.current_user(db, user)
            request = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            if request is None:
                raise APIError(404, "not_found")
            if request[owner_field] != user["id"]:
                raise APIError(403, "forbidden")
            if request["status"] not in ("pending", desired_status):
                raise APIError(409, "request_not_pending")
            if request["status"] == "pending":
                db.execute("UPDATE requests SET status = ? WHERE id = ?", (desired_status, request_id))
            updated = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
            result = request_body(db, updated)
        self.send_json(200, result)

    def create_split(self, db, user, body):
        participants = body.get("participant_handles")
        if "participant_handles" not in body:
            validation("Missing participants")
        if not isinstance(participants, list):
            malformed("Participants must be an array")
        if any(not isinstance(handle, str) for handle in participants):
            malformed("Participant handles must be strings")
        value = amount(body)
        split_note = note(body)
        if not participants or len(set(participants)) != len(participants):
            validation("Participants must be nonempty and unique")
        if any(not HANDLE_PATTERN.fullmatch(handle) for handle in participants):
            validation("Invalid handle")
        targets = []
        for handle in participants:
            target = db.execute("SELECT * FROM users WHERE handle = ?", (handle,)).fetchone()
            if target is None:
                raise APIError(404, "not_found")
            targets.append(target)
        quotient, remainder = divmod(value, len(participants))
        created_at = self.now.isoformat()
        shares = []
        requests = []
        for index, target in enumerate(targets):
            share = quotient + (1 if index < remainder else 0)
            shares.append({"handle": target["handle"], "amount": share})
            if target["id"] != user["id"]:
                request_id = new_id("rq_")
                db.execute(
                    "INSERT INTO requests(id, requester_id, payer_id, amount, note, status, payment_id, created_at) VALUES(?, ?, ?, ?, ?, 'pending', NULL, ?)",
                    (request_id, user["id"], target["id"], share, split_note, created_at),
                )
                requests.append(request_body(db, db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()))
        split_id = new_id("sp_")
        db.execute(
            "INSERT INTO splits(id, creator_id, amount, note, shares_json, request_ids_json, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (split_id, user["id"], value, split_note, json.dumps(shares), json.dumps([request["request_id"] for request in requests]), created_at),
        )
        return {"split_id": split_id, "amount": value, "currency": get_meta(db)["currency"], "note": split_note,
                "shares": shares, "requests": requests, "created_at": created_at}

    def create_settlement(self, db, user, body):
        if db.execute("SELECT 1 FROM operators WHERE user_id = ?", (user["id"],)).fetchone() is None:
            raise APIError(403, "forbidden")
        transfers = body.get("transfers")
        if not isinstance(transfers, list) or not 1 <= len(transfers) <= 32:
            validation("Transfers must contain 1 to 32 objects")
        prepared = []
        net = {}
        for transfer in transfers:
            if not isinstance(transfer, dict):
                validation("Invalid transfer object")
            source_handle = transfer.get("from_handle")
            target_handle = transfer.get("to_handle")
            if not isinstance(source_handle, str) or not isinstance(target_handle, str):
                validation("Invalid transfer handles")
            value = amount(transfer)
            transfer_note = note(transfer)
            transfer_visibility = visibility(transfer)
            if not HANDLE_PATTERN.fullmatch(source_handle) or not HANDLE_PATTERN.fullmatch(target_handle):
                validation("Invalid transfer handle")
            if source_handle == target_handle:
                raise APIError(422, "self_payment")
            source = db.execute("SELECT * FROM users WHERE handle = ?", (source_handle,)).fetchone()
            target = db.execute("SELECT * FROM users WHERE handle = ?", (target_handle,)).fetchone()
            if source is None or target is None:
                raise APIError(404, "not_found")
            prepared.append((source["id"], target["id"], value, transfer_note, transfer_visibility))
            net[source["id"]] = net.get(source["id"], 0) - value
            net[target["id"]] = net.get(target["id"], 0) + value
        final_balances = {}
        for user_id, delta in net.items():
            balance = db.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()["balance"] + delta
            if wallet_funds(db, user_id, balance, self.now)["available"] < 0:
                raise APIError(409, "insufficient_funds")
            if balance > MAX_BALANCE:
                validation("Balance limit exceeded")
            final_balances[user_id] = balance
        # Assign net balances directly: no transient overdrafts even for cycles.
        db.executemany("UPDATE users SET balance = ? WHERE id = ?", ((balance, user_id) for user_id, balance in final_balances.items()))
        settlement_id = new_id("st_")
        committed_at = self.now.isoformat()
        db.execute("INSERT INTO settlements(id, operator_id, committed_at) VALUES(?, ?, ?)", (settlement_id, user["id"], committed_at))
        payments = []
        for source_id, target_id, value, transfer_note, transfer_visibility in prepared:
            payment_id = new_id("p_")
            db.execute(
                "INSERT INTO payments(id, from_user_id, to_user_id, amount, note, visibility, request_id, settlement_id, created_at) VALUES(?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (payment_id, source_id, target_id, value, transfer_note, transfer_visibility, settlement_id, committed_at),
            )
            original(db,payment_id)
            payments.append(payment_body(db, db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()))
        return {"settlement_id": settlement_id, "committed_at": committed_at, "payments": payments}

    def create_authorization(self, db, user, body):
        to_handle = required_string(body, "to_handle")
        value = amount(body)
        hold_note = note(body)
        hold_visibility = visibility(body)
        if not HANDLE_PATTERN.fullmatch(to_handle):
            validation("Invalid handle")
        if to_handle == user["handle"]:
            raise APIError(422, "self_payment")
        target = db.execute("SELECT * FROM users WHERE handle = ?", (to_handle,)).fetchone()
        if target is None:
            raise APIError(404, "not_found")
        if wallet_funds(db, user["id"], user["balance"], self.now)["available"] < value:
            raise APIError(409, "insufficient_funds")
        ttl = lifetime(Decimal(get_meta(db)["authorization_ttl_seconds"]), self.now)
        created_at = self.now.isoformat()
        expires_at = (self.now + timedelta(seconds=ttl)).isoformat()
        authorization_id = new_id("a_")
        db.execute(
            "INSERT INTO authorizations(id, from_user_id, to_user_id, amount, captured_amount, note, visibility, status, expires_at, payment_id, payment_ids_json, created_at) VALUES(?, ?, ?, ?, 0, ?, ?, 'open', ?, NULL, '[]', ?)",
            (authorization_id, user["id"], target["id"], value, hold_note, hold_visibility, expires_at, created_at),
        )
        baseline(db,authorization_id)
        return authorization_body(db, db.execute("SELECT * FROM authorizations WHERE id = ?", (authorization_id,)).fetchone(), self.now)

    def capture_authorization(self, db, user, body, authorization_id):
        requested = capture_value(body)
        final = body.get("final", True)
        if not isinstance(final, bool):
            malformed("Final must be boolean")
        hold = db.execute("SELECT * FROM authorizations WHERE id = ?", (authorization_id,)).fetchone()
        if hold is None:
            raise APIError(404, "not_found")
        if hold["to_user_id"] != user["id"]:
            raise APIError(403, "forbidden")
        if hold["status"] != "open":
            raise APIError(409, "authorization_not_open")
        if parse_instant(hold["expires_at"]) <= instant(self.now):
            raise APIError(409, "authorization_expired")
        remainder = hold["amount"] - hold["captured_amount"]
        if requested is not None and requested > remainder:
            raise APIError(422, "capture_exceeds_authorization")
        value = remainder if requested is None else int(requested)
        if user["balance"] + value > MAX_BALANCE:
            validation("Balance limit exceeded")
        payment_id = new_id("p_")
        db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (value, hold["from_user_id"]))
        db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (value, user["id"]))
        db.execute(
            "INSERT INTO payments(id, from_user_id, to_user_id, amount, note, visibility, request_id, settlement_id, authorization_id, created_at) VALUES(?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)",
            (payment_id, hold["from_user_id"], user["id"], value, hold["note"], hold["visibility"], authorization_id, self.now.isoformat()),
        )
        original(db,payment_id)
        payment_ids = json.loads(hold["payment_ids_json"])
        payment_ids.append(payment_id)
        status = "captured" if final or value == remainder else "open"
        db.execute("UPDATE authorizations SET captured_amount = captured_amount + ?, status = ?, payment_id = ?, payment_ids_json = ? WHERE id = ?",
                   (value, status, payment_id, json.dumps(payment_ids), authorization_id))
        record_event(db, authorization_id, "capture", self.now.isoformat(), remainder - value if status == "open" else 0, payment_id)
        return payment_body(db, db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone())

    def void_authorization(self, db, user, authorization_id):
        with write_transaction(db):
            user = self.current_user(db, user)
            self.now = clock()
            hold = db.execute("SELECT * FROM authorizations WHERE id = ?", (authorization_id,)).fetchone()
            if hold is None:
                raise APIError(404, "not_found")
            if hold["from_user_id"] != user["id"]:
                raise APIError(403, "forbidden")
            if effective_status(hold, self.now) not in ("open", "voided"):
                raise APIError(409, "authorization_not_open")
            if hold["status"] == "open":
                db.execute("UPDATE authorizations SET status = 'voided' WHERE id = ?", (authorization_id,))
                record_event(db, authorization_id, "void", self.now.isoformat())
            result = authorization_body(db, db.execute("SELECT * FROM authorizations WHERE id = ?", (authorization_id,)).fetchone(), self.now)
        self.send_json(200, result)

    def list_authorizations(self, db, user):
        query, limit, offset = self.pagination()
        direction = query.get("direction", [None])[-1]
        status = query.get("status", [None])[-1]
        if direction not in (None, "incoming", "outgoing"):
            validation("Invalid direction")
        if status is not None and status not in STATUSES:
            validation("Invalid status")
        if direction == "incoming":
            clause, parties = "to_user_id = ?", (user["id"],)
        elif direction == "outgoing":
            clause, parties = "from_user_id = ?", (user["id"],)
        else:
            clause, parties = "(from_user_id = ? OR to_user_id = ?)", (user["id"], user["id"])
        rows = sorted(db.execute("SELECT * FROM authorizations WHERE " + clause, parties).fetchall(), key=lambda row:(parse_instant(row["created_at"]),row["seq"]),reverse=True)
        visible = [row for row in rows if status is None or effective_status(row, self.now) == status]
        page = visible[offset:offset + limit]
        return {"authorizations": [authorization_body(db, row, self.now) for row in page], "has_more": len(visible) > offset + limit}

    def list_requests(self, db, user):
        query, limit, offset = self.pagination()
        direction = query.get("direction", [None])[-1]
        status = query.get("status", [None])[-1]
        if direction not in (None, "incoming", "outgoing"):
            validation("Invalid direction")
        if status not in (None, "pending", "paid", "declined", "cancelled"):
            validation("Invalid status")
        clauses = []
        parameters = []
        if direction == "incoming":
            clauses.append("payer_id = ?")
            parameters.append(user["id"])
        elif direction == "outgoing":
            clauses.append("requester_id = ?")
            parameters.append(user["id"])
        else:
            clauses.append("(requester_id = ? OR payer_id = ?)")
            parameters.extend((user["id"], user["id"]))
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        rows = db.execute(
            "SELECT * FROM requests WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC, seq DESC LIMIT ? OFFSET ?",
            (*parameters, limit + 1, offset),
        ).fetchall()
        return {"requests": [request_body(db, row) for row in rows[:limit]], "has_more": len(rows) > limit}

    def activity(self, db, user):
        _, limit, offset = self.pagination()
        rows = db.execute(
            "SELECT * FROM payments WHERE visibility = 'public' OR from_user_id = ? OR to_user_id = ?",
            (user["id"], user["id"]),
        ).fetchall()
        rows = sorted(rows,key=lambda row:(parse_instant(row["created_at"]),row["seq"]),reverse=True)[offset:offset+limit+1]
        return {"payments": [payment_body(db, row) for row in rows[:limit]], "has_more": len(rows) > limit}

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_PUT(self):
        self.dispatch()

    def do_PATCH(self):
        self.dispatch()

    def do_DELETE(self):
        self.dispatch()

    def do_OPTIONS(self):
        self.dispatch()

    def do_HEAD(self):
        self.dispatch()

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self.dispatch
        raise AttributeError(name)


class PocketfulServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128


if __name__ == "__main__":
    initialize()
    port = int(os.environ.get("PORT", "8080"))
    PocketfulServer(("0.0.0.0", port), PocketfulHandler).serve_forever()
