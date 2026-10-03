"""Portable snapshots of application rows; callers never supply SQL or a database file."""
import json
import re
import sqlite3
from datetime import datetime

from core import HANDLE_PATTERN, MAX_BALANCE, PASSWORD_ITERATIONS, TABLES, email_key, identifier, number_as_integer, valid_email, validation, write_transaction


NULLABLE = {("payments", "request_id"), ("payments", "settlement_id"), ("requests", "payment_id")}


def export_state(db):
    db.execute("BEGIN")
    try:
        tables = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in TABLES}
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    return {"track": "pocketful", "format_version": 1, "state": {"schema_version": 1, "tables": tables}}


def valid_time(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except (ValueError, TypeError):
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


def validate_state(db, envelope):
    if envelope.get("track") != "pocketful" or number_as_integer(envelope.get("format_version"), 1, 1) != 1:
        validation("Unsupported export format")
    state = envelope.get("state")
    if not isinstance(state, dict) or number_as_integer(state.get("schema_version"), 1, 1) != 1:
        validation("Invalid state")
    tables = state.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        validation("Invalid state tables")
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
            for field in ("created_at", "committed_at"):
                if field in normalized and not valid_time(normalized[field]):
                    validation("Invalid timestamp")
            prepared[table].append(normalized)

    meta = {row["key"]: row["value"] for row in prepared["meta"]}
    if len(meta) != len(prepared["meta"]) or not {"currency", "minor_units", "seed_total"} <= set(meta):
        validation("Invalid metadata")
    if not meta["currency"] or meta["minor_units"] not in ("0", "2", "3") or not re.fullmatch(r"[0-9]+", meta["seed_total"]):
        validation("Invalid currency or total")
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
        if not re.fullmatch(r"[0-9a-f]{32}", user["password_salt"]) or not re.fullmatch(rf"(?:pbkdf2_sha256\${PASSWORD_ITERATIONS}\$)?[0-9a-f]{{64}}", user["password_hash"]):
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
    for row in prepared["payments"]:
        if row["from_user_id"] not in users or row["to_user_id"] not in users or row["from_user_id"] == row["to_user_id"]:
            validation("Invalid payment parties")
        if not 0 <= row["amount"] <= 1000000000 or len(row["note"]) > 200 or row["visibility"] not in ("public", "private"):
            validation("Invalid payment")
        if row["request_id"] is not None and row["request_id"] not in requests:
            validation("Invalid payment request")
        if row["settlement_id"] is not None and not identifier(row["settlement_id"]):
            validation("Invalid settlement identity")
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
        if row["path"] not in ("/payments", "/requests", "/splits", "/settlements") and not re.fullmatch(r"/requests/[^/]+/pay", row["path"]):
            validation("Invalid idempotency path")
        stored_json(row["body_json"], list)
        stored_json(row["response_json"], dict)
    return prepared


def import_state(db, envelope):
    prepared = validate_state(db, envelope)
    with write_transaction(db):
        try:
            for table in TABLES:
                db.execute(f"DELETE FROM {table}")
            db.execute("DELETE FROM sqlite_sequence")
            for table in TABLES:
                for row in prepared[table]:
                    columns = ",".join(row)
                    placeholders = ",".join("?" for _ in row)
                    db.execute(f"INSERT INTO {table}({columns}) VALUES({placeholders})", tuple(row.values()))
        except sqlite3.IntegrityError:
            validation("Duplicate or invalid state record")
