import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal


DATABASE_PATH = os.environ.get("POCKETFUL_DB", "/tmp/pocketful.sqlite3")
WRITE_LOCK = threading.RLock()
HANDLE_PATTERN = re.compile(r"^[a-z0-9_]{1,20}$")
MAX_BALANCE = 2**53
PASSWORD_ITERATIONS = 5000
TABLES = ("idempotency", "tokens", "wallet_openings", "payment_revisions", "authorization_history_baselines", "authorization_events", "authorizations", "payments", "requests", "splits", "settlements", "operators", "users", "meta")
CLOCK_HIGH_WATER = None


class APIError(Exception):
    def __init__(self, status, code, message=None):
        self.status = status
        self.code = code
        self.message = message or code.replace("_", " ")
        super().__init__(self.message)


def validation(message="Invalid value"):
    raise APIError(422, "validation_failed", message)


def malformed(message="Malformed request"):
    raise APIError(400, "malformed_request", message)


def timestamp():
    return server_clock().isoformat(timespec="microseconds")


def server_clock():
    global CLOCK_HIGH_WATER
    with WRITE_LOCK:
        now = datetime.now(timezone.utc)
        if CLOCK_HIGH_WATER is not None and now <= CLOCK_HIGH_WATER:
            now = CLOCK_HIGH_WATER + timedelta(microseconds=1)
        CLOCK_HIGH_WATER = now
        return now


def retain_clock(value):
    global CLOCK_HIGH_WATER
    with WRITE_LOCK:
        if CLOCK_HIGH_WATER is None or value > CLOCK_HIGH_WATER:
            CLOCK_HIGH_WATER = value


def new_id(prefix):
    return prefix + uuid.uuid4().hex


def new_token():
    return secrets.token_urlsafe(32)


def email_key(email):
    return email.casefold()


def valid_email(email):
    return isinstance(email, str) and email.count("@") == 1 and all(email.split("@"))


def derived_handle(email):
    local = email.split("@", 1)[0].lower()
    return re.sub(r"[^a-z0-9_]", "_", local)[:20]


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return salt.hex(), f"pbkdf2_sha256${PASSWORD_ITERATIONS}${digest.hex()}"


def check_password(password, salt_hex, digest_hex):
    # Keep earlier exports readable; new records carry their KDF work factor.
    iterations = 120000
    if digest_hex.startswith("pbkdf2_sha256$"):
        _, iterations_text, digest_hex = digest_hex.split("$")
        iterations = int(iterations_text)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
    return hmac.compare_digest(digest.hex(), digest_hex)


def connection():
    db = sqlite3.connect(DATABASE_PATH, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 5000")
    db.execute("PRAGMA synchronous = NORMAL")
    return db


@contextmanager
def write_transaction(db, serialize=True):
    with WRITE_LOCK if serialize else nullcontext():
        db.execute("BEGIN IMMEDIATE")
        try:
            yield
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise


def initialize():
    with connection() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, email TEXT NOT NULL, email_key TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL, handle TEXT NOT NULL UNIQUE,
                balance INTEGER NOT NULL CHECK(balance >= 0 AND balance <= 9007199254740992),
                password_salt TEXT NOT NULL, password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tokens (
                token TEXT PRIMARY KEY, user_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS statement_snapshots (
                token TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                generation TEXT NOT NULL, snapshot_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operators (
                user_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS payments (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                from_user_id TEXT NOT NULL, to_user_id TEXT NOT NULL,
                amount INTEGER NOT NULL, note TEXT NOT NULL, visibility TEXT NOT NULL,
                request_id TEXT, settlement_id TEXT, created_at TEXT NOT NULL,
                authorization_id TEXT, refund_of TEXT
            );
            CREATE INDEX IF NOT EXISTS payments_feed ON payments(created_at DESC, seq DESC);
            CREATE TABLE IF NOT EXISTS requests (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                requester_id TEXT NOT NULL, payer_id TEXT NOT NULL, amount INTEGER NOT NULL,
                note TEXT NOT NULL, status TEXT NOT NULL, payment_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS requests_feed ON requests(created_at DESC, seq DESC);
            CREATE TABLE IF NOT EXISTS authorizations (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                from_user_id TEXT NOT NULL, to_user_id TEXT NOT NULL,
                amount INTEGER NOT NULL, captured_amount INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL, visibility TEXT NOT NULL, status TEXT NOT NULL,
                expires_at TEXT NOT NULL, payment_id TEXT, payment_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS authorizations_parties ON authorizations(from_user_id, to_user_id);
            CREATE TABLE IF NOT EXISTS authorization_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                authorization_id TEXT NOT NULL, kind TEXT NOT NULL, event_at TEXT NOT NULL,
                payment_id TEXT, remaining_amount INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS authorization_event_order ON authorization_events(authorization_id, seq);
            CREATE TABLE IF NOT EXISTS wallet_openings (
                user_id TEXT PRIMARY KEY, opening_amount INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payment_revisions (
                payment_id TEXT NOT NULL, revision INTEGER NOT NULL, amount INTEGER NOT NULL,
                effective_at TEXT NOT NULL, recorded_at TEXT NOT NULL, reason TEXT NOT NULL,
                correction_batch_id TEXT,
                PRIMARY KEY(payment_id, revision)
            );
            CREATE INDEX IF NOT EXISTS revisions_known ON payment_revisions(payment_id, recorded_at);
            CREATE TABLE IF NOT EXISTS authorization_history_baselines (
                authorization_id TEXT PRIMARY KEY, baseline_at TEXT NOT NULL,
                held_amount INTEGER NOT NULL, provenance TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS splits (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                creator_id TEXT NOT NULL, amount INTEGER NOT NULL, note TEXT NOT NULL,
                shares_json TEXT NOT NULL, request_ids_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settlements (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                operator_id TEXT NOT NULL, committed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS idempotency (
                user_id TEXT NOT NULL, key TEXT NOT NULL, method TEXT NOT NULL,
                path TEXT NOT NULL, body_json TEXT NOT NULL, response_json TEXT NOT NULL,
                PRIMARY KEY(user_id, key, method, path)
            );
        """)
        db.executemany("INSERT OR IGNORE INTO meta(key, value) VALUES(?, ?)", (("currency", "EUR"), ("minor_units", "2"), ("seed_total", "0"), ("authorization_ttl_seconds", "600")))
        db.executemany("INSERT OR IGNORE INTO meta(key, value) VALUES(?, ?)", (("reset_generation",new_id("generation_")),("clock_high_water",timestamp())))
        retain_clock(datetime.fromisoformat(get_meta(db)["clock_high_water"]))


def required_string(obj, key, fixture=False):
    value = obj.get(key)
    if value is None and key not in obj:
        validation(f"Missing {key}")
    if not isinstance(value, str):
        if fixture:
            validation(f"Invalid {key}")
        malformed(f"{key} must be a string")
    return value


def optional_string(obj, key, default="", fixture=False):
    if key not in obj:
        return default
    value = obj[key]
    if not isinstance(value, str):
        if fixture or key == "note":
            validation(f"Invalid {key}")
        malformed(f"{key} must be a string")
    return value


def identifier(value):
    return isinstance(value, str) and 1 <= len(value) <= 64


def number_as_integer(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    if isinstance(value, Decimal) and value != value.to_integral_value():
        return None
    if not minimum <= value <= maximum:
        return None
    return int(value)


def amount(obj, key="amount", minimum=1):
    value = number_as_integer(obj.get(key), minimum, 1000000000)
    if value is None:
        validation(f"Invalid {key}")
    return value


def note(obj, fixture=False):
    value = optional_string(obj, "note", fixture=fixture)
    if len(value) > 200:
        validation("Note is too long")
    return value


def visibility(obj, fixture=False):
    value = obj.get("visibility", "public")
    if not isinstance(value, str) or value not in ("public", "private"):
        validation("Invalid visibility")
    return value


def canonical_value(value):
    if isinstance(value, dict):
        return ["object", [[key, canonical_value(item)] for key, item in sorted(value.items())]]
    if isinstance(value, list):
        return ["array", [canonical_value(item) for item in value]]
    if isinstance(value, bool):
        return ["boolean", value]
    if value is None:
        return ["null"]
    if isinstance(value, (int, Decimal)):
        parts = Decimal(value).as_tuple()
        digits = "".join(str(digit) for digit in parts.digits)
        coefficient = digits.rstrip("0")
        if not coefficient:
            return ["number", "0"]
        exponent = parts.exponent + len(digits) - len(coefficient)
        return ["number", f"{'-' if parts.sign else ''}{coefficient}e{exponent}"]
    return ["string", value]


def canonical_body(value):
    return json.dumps(canonical_value(value), ensure_ascii=False, separators=(",", ":"))


def fixture_record_id(record, key="id"):
    value = record.get(key)
    if not identifier(value):
        validation(f"Invalid {key}")
    return value


def validate_fixture(fixture):
    if not isinstance(fixture, dict):
        malformed("Fixture must be an object")
    currency = required_string(fixture, "currency", fixture=True)
    minor_units = number_as_integer(fixture.get("minor_units"), 0, 3)
    if not currency or minor_units not in (0, 2, 3):
        validation("Invalid currency or minor units")
    users = fixture.get("users")
    if not isinstance(users, list):
        validation("Invalid users")
    payments = fixture.get("payments", [])
    requests = fixture.get("requests", [])
    operators = fixture.get("settlement_operator_ids", [])
    if not all(isinstance(items, list) for items in (payments, requests, operators)):
        validation("Invalid fixture array")
    user_ids = set()
    handles = set()
    emails = set()
    prepared_users = []
    total = 0
    for item in users:
        if not isinstance(item, dict):
            validation("Invalid user")
        user_id = fixture_record_id(item)
        email = required_string(item, "email", fixture=True)
        password = required_string(item, "password", fixture=True)
        display_name = required_string(item, "display_name", fixture=True)
        handle = required_string(item, "handle", fixture=True)
        balance = number_as_integer(item.get("balance"), 0, MAX_BALANCE)
        if not valid_email(email) or not HANDLE_PATTERN.fullmatch(handle) or balance is None:
            validation("Invalid user")
        if user_id in user_ids or handle in handles or email_key(email) in emails:
            validation("Duplicate user")
        user_ids.add(user_id)
        handles.add(handle)
        emails.add(email_key(email))
        total += balance
        salt, digest = hash_password(password)
        prepared_users.append((user_id, email, email_key(email), display_name, handle, balance, salt, digest))
    prepared_payments = []
    payment_ids = set()
    for item in payments:
        if not isinstance(item, dict):
            validation("Invalid payment")
        payment_id = fixture_record_id(item)
        source = required_string(item, "from_user_id", fixture=True)
        target = required_string(item, "to_user_id", fixture=True)
        value = amount(item, minimum=0)
        if source not in user_ids or target not in user_ids or source == target or payment_id in payment_ids:
            validation("Invalid payment")
        payment_ids.add(payment_id)
        request_id = item.get("request_id")
        settlement_id = item.get("settlement_id")
        if request_id is not None and not identifier(request_id):
            validation("Invalid request_id")
        if settlement_id is not None and not identifier(settlement_id):
            validation("Invalid settlement_id")
        prepared_payments.append((payment_id, source, target, value, note(item, fixture=True), visibility(item, fixture=True), request_id, settlement_id))
    prepared_requests = []
    request_ids = set()
    for item in requests:
        if not isinstance(item, dict):
            validation("Invalid request")
        request_id = fixture_record_id(item)
        requester = required_string(item, "requester_id", fixture=True)
        payer = required_string(item, "payer_id", fixture=True)
        value = amount(item, minimum=0)
        status = required_string(item, "status", fixture=True)
        payment_id = item.get("payment_id")
        if requester not in user_ids or payer not in user_ids or requester == payer or request_id in request_ids:
            validation("Invalid request")
        if status not in ("pending", "paid", "declined", "cancelled"):
            validation("Invalid status")
        if payment_id is not None and (not identifier(payment_id) or payment_id not in payment_ids):
            validation("Invalid payment_id")
        request_ids.add(request_id)
        prepared_requests.append((request_id, requester, payer, value, note(item, fixture=True), status, payment_id))
    if any(payment[6] is not None and payment[6] not in request_ids for payment in prepared_payments):
        validation("Unknown request_id")
    if any(not isinstance(operator, str) or operator not in user_ids for operator in operators):
        validation("Unknown operator")
    if len(set(operators)) != len(operators):
        validation("Duplicate operator")
    return currency, minor_units, prepared_users, prepared_payments, prepared_requests, operators, total


def reset(db, fixture):
    from history import parse_instant, instant
    from history_store import seed
    now = server_clock()
    currency, minor_units, users, payments, requests, operators, total = validate_fixture(fixture)
    from holds import prepare_fixture_authorizations
    ttl, authorizations, payment_authorizations = prepare_fixture_authorizations(fixture, users, payments, now)
    created_at = now.isoformat()
    payment_times = {item["id"]:item.get("created_at",created_at) for item in fixture.get("payments",[])}
    authorization_times = {item["id"]:item.get("created_at",created_at) for item in fixture.get("authorizations",[])}
    for value in list(payment_times.values()) + list(authorization_times.values()):
        if parse_instant(value) > instant(now):
            validation("Seeded creation cannot be in the future")
    with write_transaction(db):
        db.execute("DELETE FROM statement_snapshots")
        for table in TABLES:
            db.execute(f"DELETE FROM {table}")
        db.executemany("INSERT INTO meta(key, value) VALUES(?, ?)", (("currency", currency), ("minor_units", str(minor_units)), ("seed_total", str(total)), ("authorization_ttl_seconds", str(ttl))))
        db.executemany("INSERT INTO meta(key,value) VALUES(?,?)", (("reset_generation",new_id("generation_")),("clock_high_water",created_at)))
        db.executemany("INSERT INTO users VALUES(?, ?, ?, ?, ?, ?, ?, ?)", users)
        db.executemany("INSERT INTO operators(user_id) VALUES(?)", ((user_id,) for user_id in operators))
        db.executemany("INSERT INTO payments(id, from_user_id, to_user_id, amount, note, visibility, request_id, settlement_id, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)", (payment + (payment_times[payment[0]],) for payment in payments))
        db.executemany("INSERT INTO requests(id, requester_id, payer_id, amount, note, status, payment_id, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)", (request + (created_at,) for request in requests))
        db.executemany("INSERT INTO authorizations(id, from_user_id, to_user_id, amount, captured_amount, note, visibility, status, expires_at, payment_id, payment_ids_json, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (row + (authorization_times[row[0]],) for row in authorizations))
        db.executemany("UPDATE payments SET authorization_id = ? WHERE id = ?", payment_authorizations)
        seed(db,now)


def get_meta(db):
    return {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM meta")}


def payment_body(db, row):
    source = db.execute("SELECT handle FROM users WHERE id = ?", (row["from_user_id"],)).fetchone()
    target = db.execute("SELECT handle FROM users WHERE id = ?", (row["to_user_id"],)).fetchone()
    return {
        "payment_id": row["id"], "from_user_id": row["from_user_id"], "from_handle": source["handle"],
        "to_user_id": row["to_user_id"], "to_handle": target["handle"], "amount": row["amount"],
        "currency": get_meta(db)["currency"], "note": row["note"], "visibility": row["visibility"],
        "request_id": row["request_id"], "settlement_id": row["settlement_id"], "created_at": row["created_at"],
        "authorization_id": row["authorization_id"], "refund_of": row["refund_of"],
    }


def request_body(db, row):
    requester = db.execute("SELECT handle FROM users WHERE id = ?", (row["requester_id"],)).fetchone()
    payer = db.execute("SELECT handle FROM users WHERE id = ?", (row["payer_id"],)).fetchone()
    return {
        "request_id": row["id"], "requester_id": row["requester_id"], "requester_handle": requester["handle"],
        "payer_id": row["payer_id"], "payer_handle": payer["handle"], "amount": row["amount"],
        "currency": get_meta(db)["currency"], "note": row["note"], "status": row["status"],
        "payment_id": row["payment_id"], "created_at": row["created_at"],
    }
