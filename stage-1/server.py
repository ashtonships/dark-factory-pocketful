import json
import os
import re
import socket
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from core import (
    APIError, HANDLE_PATTERN, check_password, connection, derived_handle, email_key,
    get_meta, hash_password, initialize, malformed, new_id, new_token,
    required_string, reset, valid_email, validation, write_transaction,
)


MAX_BODY_BYTES = 8 * 1024 * 1024
REQUEST_ACTION = re.compile(r"^/requests/([^/]+)/(pay|decline|cancel)$")
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
}


def json_body(data):
    try:
        decoded = data.decode("utf-8", errors="strict")
        value = json.loads(decoded, parse_float=Decimal, parse_constant=lambda _: malformed())
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError, InvalidOperation):
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
    server_version = "Pocketful/1"

    def log_message(self, format_string, *args):
        return

    def send_json(self, status, value=None):
        payload = b"" if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
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
        if REQUEST_ACTION.fullmatch(path):
            return {"POST"}
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

    def dispatch(self):
        self.connection.settimeout(10 if self.command == "POST" and urlsplit(self.path).path in ("/_test/reset", "/_test/import") else 5)
        try:
            raw_body = self.read_body()
            path = urlsplit(self.path).path
            methods = self.route_info(path)
            if methods is None:
                raise APIError(404, "not_found")
            if self.command not in methods:
                raise APIError(405, "method_not_allowed")
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
                if path in ("/auth/signup", "/auth/login"):
                    if self.body_too_large:
                        validation("Body is too large")
                    body = json_body(raw_body)
                    if path == "/auth/signup":
                        self.signup(db, body)
                    else:
                        self.login(db, body)
                    return
                user = self.authenticate(db)
                if self.body_too_large:
                    validation("Body is too large")
                if self.command == "POST":
                    json_body(raw_body)
                if path == "/me":
                    meta = get_meta(db)
                    self.send_json(200, {
                        "user_id": user["id"], "display_name": user["display_name"],
                        "handle": user["handle"], "balance": user["balance"],
                        "currency": meta["currency"], "minor_units": int(meta["minor_units"]),
                    })
                    return
                raise APIError(404, "not_found")
            finally:
                db.close()
        except APIError as error:
            self.send_api_error(error)
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
        with write_transaction(db):
            current = db.execute("SELECT 1 FROM users WHERE id = ? AND password_hash = ?", (user["id"], user["password_hash"])).fetchone()
            if current is None:
                raise APIError(401, "unauthenticated")
            db.execute("INSERT INTO tokens VALUES(?, ?)", (token, user["id"]))
        self.send_json(200, {"user_id": user["id"], "display_name": user["display_name"], "token": token})

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
