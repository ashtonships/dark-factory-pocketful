"""Portable snapshots of application rows; callers never supply SQL or a database file."""
import json
import re
import sqlite3
from datetime import datetime
from decimal import Decimal

from core import APIError, HANDLE_PATTERN, MAX_BALANCE, PASSWORD_ITERATIONS, TABLES, email_key, get_meta, identifier, number_as_integer, retain_clock, valid_email, validation, write_transaction
from holds import STATUSES, clock, expiry, lifetime, record_expiries, remaining
from history_store import HISTORY_TABLES, upgrade_tables, validate as validate_history
from history import instant, parse_instant


NULLABLE = {("payments", "request_id"), ("payments", "settlement_id"), ("payments", "authorization_id"), ("requests", "payment_id"), ("authorizations", "payment_id"), ("authorization_events", "payment_id")}


def export_state(db):
    with write_transaction(db):
        record_expiries(db, clock())
        tables = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in TABLES}
    return {"track": "pocketful", "format_version": 1, "state": {"schema_version": 1, "tables": tables}}


def valid_time(value):
    try:
        parse_instant(value)
        return True
    except APIError:
        return False


def stored_json(value, expected_type):
    try:
        parsed = json.loads(value, parse_constant=lambda _: validation("Invalid stored JSON"))
        # Reject strings which could not be sent in a UTF-8 JSON response.
        json.dumps(parsed, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if not isinstance(parsed, expected_type):
            validation("Invalid stored JSON shape")
        return parsed
    except (ValueError, TypeError, UnicodeError, RecursionError):
        validation("Invalid stored JSON")


def validate_state(db, envelope, now):
    if envelope.get("track") != "pocketful" or number_as_integer(envelope.get("format_version"), 1, 1) != 1:
        validation("Unsupported export format")
    state = envelope.get("state")
    if not isinstance(state, dict) or number_as_integer(state.get("schema_version"), 1, 1) != 1:
        validation("Invalid state")
    tables = state.get("tables")
    prior = set(TABLES) - HISTORY_TABLES
    if not isinstance(tables, dict) or set(tables) not in (set(TABLES), prior, prior - {"authorization_events"}, prior - {"authorization_events", "authorizations"}):
        validation("Invalid state tables")
    missing_history = not HISTORY_TABLES <= set(tables)
    legacy = "authorizations" not in tables
    tables = dict(tables)
    tables.setdefault("authorization_events", [])
    for table in HISTORY_TABLES:
        tables.setdefault(table, [])
    if legacy:
        tables["authorizations"] = []
        tables["payments"] = [dict(row, authorization_id=None) if isinstance(row, dict) else row for row in tables.get("payments", [])] if isinstance(tables.get("payments"), list) else tables.get("payments")
        if isinstance(tables.get("meta"), list):
            tables["meta"] = list(tables["meta"]) + [{"key": "authorization_ttl_seconds", "value": "600"}]
    prepared = {}
    for table in TABLES:
        schema = db.execute(f"PRAGMA table_info({table})").fetchall()
        columns = {column["name"]: column["type"] for column in schema}
        rows = tables[table]
        if not isinstance(rows, list):
            validation("Invalid table rows")
        prepared[table] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns):
                validation("Invalid row columns")
            normalized = {}
            for name, kind in columns.items():
                value = row[name]
                if value is None and (table, name) in NULLABLE:
                    normalized[name] = None
                elif kind == "INTEGER":
                    integer = number_as_integer(value, -(2**63), 2**63 - 1)
                    if integer is None:
                        validation("Invalid stored integer")
                    normalized[name] = integer
                elif isinstance(value, str):
                    normalized[name] = value
                else:
                    validation("Invalid stored text")
            if "id" in normalized and not identifier(normalized["id"]):
                validation("Invalid record identity")
            if "seq" in normalized and normalized["seq"] < 1:
                validation("Invalid sequence")
            for field in ("created_at", "committed_at", "expires_at", "event_at", "effective_at", "recorded_at", "baseline_at"):
                if field in normalized and not valid_time(normalized[field]):
                    validation("Invalid timestamp")
            prepared[table].append(normalized)

    meta = {row["key"]: row["value"] for row in prepared["meta"]}
    if len(meta) != len(prepared["meta"]) or not {"currency", "minor_units", "seed_total"} <= set(meta):
        validation("Invalid metadata")
    if not meta["currency"] or meta["minor_units"] not in ("0", "2", "3") or not re.fullmatch(r"[0-9]+", meta["seed_total"]):
        validation("Invalid currency or total")
    ttl = meta.get("authorization_ttl_seconds", "")
    if not re.fullmatch(r"[0-9]+", ttl):
        validation("Invalid authorization lifetime")
    lifetime(Decimal(ttl),now)
    users = {row["id"]: row for row in prepared["users"]}
    if len(users) != len(prepared["users"]):
        validation("Duplicate user")
    handles = set()
    emails = set()
    for user in users.values():
        if not valid_email(user["email"]) or user["email_key"] != email_key(user["email"]) or not HANDLE_PATTERN.fullmatch(user["handle"]):
            validation("Invalid user")
        if user["handle"] in handles or user["email_key"] in emails or not 0 <= user["balance"] <= MAX_BALANCE:
            validation("Invalid wallet")
        if not re.fullmatch(r"[0-9a-f]{32}", user["password_salt"]) or not re.fullmatch(rf"(?:pbkdf2_sha256\$(?:{PASSWORD_ITERATIONS}|20000)\$)?[0-9a-f]{{64}}", user["password_hash"]):
            validation("Invalid password hash")
        handles.add(user["handle"])
        emails.add(user["email_key"])
    # Compare decimal strings, without parsing an unbounded supplied integer.
    if str(sum(user["balance"] for user in users.values())) != (meta["seed_total"].lstrip("0") or "0"):
        validation("Wallet total does not match seed")
    for row in prepared["tokens"]:
        if row["user_id"] not in users or not re.fullmatch(r"[A-Za-z0-9_-]+", row["token"]):
            validation("Invalid session")
    if any(row["user_id"] not in users for row in prepared["operators"]):
        validation("Invalid operator")
    payments = {row["id"]: row for row in prepared["payments"]}
    requests = {row["id"]: row for row in prepared["requests"]}
    authorizations = {row["id"]: row for row in prepared["authorizations"]}
    if len(authorizations) != len(prepared["authorizations"]):
        validation("Duplicate authorization")
    for row in prepared["payments"]:
        if row["from_user_id"] not in users or row["to_user_id"] not in users or row["from_user_id"] == row["to_user_id"]:
            validation("Invalid payment parties")
        if not 0 <= row["amount"] <= 1000000000 or len(row["note"]) > 200 or row["visibility"] not in ("public", "private"):
            validation("Invalid payment")
        if row["request_id"] is not None and row["request_id"] not in requests:
            validation("Invalid payment request")
        if row["settlement_id"] is not None and not identifier(row["settlement_id"]):
            validation("Invalid settlement identity")
        if row["authorization_id"] is not None and (row["authorization_id"] not in authorizations or row["request_id"] is not None or row["settlement_id"] is not None):
            validation("Invalid payment authorization")
    held = {}
    capture_owners = {}
    for row in authorizations.values():
        if row["from_user_id"] not in users or row["to_user_id"] not in users or row["from_user_id"] == row["to_user_id"]:
            validation("Invalid authorization parties")
        if not 1 <= row["amount"] <= 1000000000 or not 0 <= row["captured_amount"] <= row["amount"] or len(row["note"]) > 200 or row["visibility"] not in ("public", "private") or row["status"] not in STATUSES:
            validation("Invalid authorization")
        expiry(row["expires_at"])
        if row["status"] == "open" and row["captured_amount"] == row["amount"]:
            validation("An open authorization must have a remainder")
        payment_ids = stored_json(row["payment_ids_json"], list)
        if any(not identifier(pid) or pid not in payments for pid in payment_ids) or len(set(payment_ids)) != len(payment_ids):
            validation("Invalid capture records")
        if row["payment_id"] != (payment_ids[len(payment_ids) - 1] if payment_ids else None):
            validation("Invalid latest capture")
        captured = 0
        for pid in payment_ids:
            payment = payments[pid]
            if pid in capture_owners or payment["authorization_id"] != row["id"] or payment["from_user_id"] != row["from_user_id"] or payment["to_user_id"] != row["to_user_id"]:
                validation("Invalid capture ownership")
            capture_owners[pid] = row["id"]
            captured += payment["amount"]
        if captured > row["captured_amount"]:
            validation("Invalid captured amount")
        held[row["from_user_id"]] = held.get(row["from_user_id"], 0) + remaining(row, now)
    if any(total > users[user_id]["balance"] for user_id, total in held.items()):
        validation("Holds exceed wallet total")
    if any(row["authorization_id"] is not None and row["id"] not in capture_owners for row in payments.values()):
        validation("Unlisted authorization capture")
    seen_capture_events = set()
    seen_closures = set()
    previous_times = {}
    for event in sorted(prepared["authorization_events"], key=lambda item: item["seq"]):
        hold = authorizations.get(event["authorization_id"])
        if hold is None or event["kind"] not in ("capture", "void", "expiry") or not 0 <= event["remaining_amount"] <= hold["amount"]:
            validation("Invalid authorization event")
        event_time = expiry(event["event_at"])
        if (event["kind"] != "expiry" and event_time < expiry(hold["created_at"])) or event_time > instant(now) or event["authorization_id"] in seen_closures:
            validation("Invalid authorization event time")
        if event_time < previous_times.get(hold["id"], event_time):
            validation("Unordered authorization events")
        previous_times[hold["id"]] = event_time
        if event["kind"] == "capture":
            payment = payments.get(event["payment_id"])
            if payment is None or capture_owners.get(payment["id"]) != hold["id"] or payment["id"] in seen_capture_events or expiry(payment["created_at"]) != event_time or event_time >= expiry(hold["expires_at"]):
                validation("Invalid capture event")
            seen_capture_events.add(payment["id"])
            payment_ids = stored_json(hold["payment_ids_json"], list)
            later = payment_ids[payment_ids.index(payment["id"]) + 1:]
            expected_remaining = hold["amount"] - hold["captured_amount"] + sum(payments[pid]["amount"] for pid in later)
            if event["remaining_amount"] != expected_remaining and event["remaining_amount"] != 0:
                validation("Invalid capture remainder")
            if event["remaining_amount"] == 0 and (hold["status"] != "captured" or hold["payment_id"] != payment["id"]):
                validation("Invalid final capture event")
        else:
            if event["payment_id"] is not None or event["remaining_amount"] != 0:
                validation("Invalid release event")
            if event["kind"] == "void" and (hold["status"] != "voided" or event_time >= expiry(hold["expires_at"])):
                validation("Invalid void event")
            if event["kind"] == "expiry" and (hold["status"] not in ("open", "expired") or event_time != expiry(hold["expires_at"])):
                validation("Invalid expiry event")
        if event["remaining_amount"] == 0:
            seen_closures.add(hold["id"])
    for row in prepared["requests"]:
        if row["requester_id"] not in users or row["payer_id"] not in users or row["requester_id"] == row["payer_id"]:
            validation("Invalid request parties")
        if not 0 <= row["amount"] <= 1000000000 or len(row["note"]) > 200 or row["status"] not in ("pending", "paid", "declined", "cancelled"):
            validation("Invalid request")
        if row["payment_id"] is not None and row["payment_id"] not in payments:
            validation("Invalid request payment")
    for row in prepared["settlements"]:
        if row["operator_id"] not in users:
            validation("Invalid settlement operator")
    for row in prepared["splits"]:
        if row["creator_id"] not in users or not 1 <= row["amount"] <= 1000000000 or len(row["note"]) > 200:
            validation("Invalid split")
        shares = stored_json(row["shares_json"], list)
        request_ids = stored_json(row["request_ids_json"], list)
        if not shares or any(not isinstance(share, dict) or set(share) != {"handle", "amount"} or not isinstance(share["handle"], str) or share["handle"] not in handles or isinstance(share["amount"], bool) or not isinstance(share["amount"], int) or share["amount"] < 0 for share in shares):
            validation("Invalid shares")
        share_handles = [share["handle"] for share in shares]
        if len(set(share_handles)) != len(shares):
            validation("Duplicate share")
        quotient, remainder = divmod(row["amount"], len(shares))
        if any(share["amount"] != quotient + (index < remainder) for index, share in enumerate(shares)):
            validation("Invalid share rounding")
        if any(not isinstance(request_id, str) or request_id not in requests for request_id in request_ids) or len(set(request_ids)) != len(request_ids):
            validation("Invalid split requests")
    for row in prepared["idempotency"]:
        if row["user_id"] not in users or not 1 <= len(row["key"]) <= 255 or row["method"] != "POST":
            validation("Invalid idempotency record")
        if row["path"] not in ("/payments", "/requests", "/splits", "/settlements", "/authorizations") and not re.fullmatch(r"/(?:requests/[^/]+/pay|authorizations/[^/]+/capture|payments/[^/]+/corrections)", row["path"]):
            validation("Invalid idempotency path")
        stored_json(row["body_json"], list)
        stored_json(row["response_json"], dict)
    return upgrade_tables(prepared,now,force=missing_history)


def import_state(db, envelope):
    now = clock()
    prepared = validate_state(db, envelope,now)
    with write_transaction(db):
        try:
            generation = get_meta(db)["reset_generation"]
            for row in prepared["meta"]:
                if row["key"] == "reset_generation":
                    row["value"] = generation
            for table in TABLES:
                db.execute(f"DELETE FROM {table}")
            db.execute("DELETE FROM sqlite_sequence")
            for table in TABLES:
                for row in prepared[table]:
                    columns = ",".join(row)
                    placeholders = ",".join("?" for _ in row)
                    db.execute(f"INSERT INTO {table}({columns}) VALUES({placeholders})", tuple(row.values()))
            validate_history(db,now)
            water = db.execute("SELECT value FROM meta WHERE key='clock_high_water'").fetchone()
            if water is None:
                validation("Missing clock high-water mark")
            try:
                retained = datetime.fromisoformat(water["value"])
            except (ValueError,OverflowError):
                validation("Invalid server clock high-water mark")
            retain_clock(retained)
        except sqlite3.IntegrityError:
            validation("Duplicate or invalid state record")
