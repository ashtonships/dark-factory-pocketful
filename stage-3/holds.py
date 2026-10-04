"""Reserved funds are derived inside the same snapshot as wallet totals."""
import json
from datetime import datetime, timezone
from decimal import Decimal

from core import amount, fixture_record_id, get_meta, identifier, note, number_as_integer, required_string, server_clock, validation, visibility
from history import instant, parse_instant


STATUSES = ("open", "captured", "voided", "expired")


def record_event(db, authorization_id, kind, event_at, remaining_amount=0, payment_id=None):
    db.execute(
        "INSERT INTO authorization_events(authorization_id, kind, event_at, payment_id, remaining_amount) VALUES(?, ?, ?, ?, ?)",
        (authorization_id, kind, event_at, payment_id, remaining_amount),
    )


def record_expiries(db, now):
    # The clock event occurs at its known deadline, not at its later observation.
    rows = db.execute("SELECT * FROM authorizations WHERE status IN ('open', 'expired')").fetchall()
    for row in rows:
        if parse_instant(row["expires_at"]) <= instant(now) and db.execute(
            "SELECT 1 FROM authorization_events WHERE authorization_id = ? AND kind = 'expiry'",
            (row["id"],),
        ).fetchone() is None:
            record_event(db, row["id"], "expiry", row["expires_at"])


def clock():
    return server_clock()


def expiry(value):
    return parse_instant(value)


def lifetime(value, now=None):
    now = now or clock()
    # RFC3339 dates must remain representable when this lifetime is applied.
    distance = datetime.max.replace(tzinfo=timezone.utc) - now
    maximum = distance.days * 86400 + distance.seconds
    seconds = number_as_integer(value, 1, maximum)
    if seconds is None:
        validation("Invalid authorization lifetime")
    return seconds


def effective_status(row, now):
    return "expired" if row["status"] == "open" and parse_instant(row["expires_at"]) <= instant(now) else row["status"]


def remaining(row, now):
    return row["amount"] - row["captured_amount"] if effective_status(row, now) == "open" else 0


def wallet_funds(db, user_id, total, now):
    rows = db.execute("SELECT * FROM authorizations WHERE from_user_id = ? AND status = 'open'", (user_id,))
    held = sum(remaining(row, now) for row in rows)
    return {"total": total, "held": held, "available": total - held}


def authorization_body(db, row, now):
    source = db.execute("SELECT handle FROM users WHERE id = ?", (row["from_user_id"],)).fetchone()
    target = db.execute("SELECT handle FROM users WHERE id = ?", (row["to_user_id"],)).fetchone()
    status = effective_status(row,now)
    closed_at = None
    if status == "expired":
        closed_at = row["expires_at"]
    elif status != "open":
        closed = db.execute("SELECT event_at FROM authorization_events WHERE authorization_id=? AND remaining_amount=0 ORDER BY seq DESC LIMIT 1", (row["id"],)).fetchone()
        closed_at = closed["event_at"] if closed else row["created_at"]
    return {
        "authorization_id": row["id"], "from_user_id": row["from_user_id"], "from_handle": source["handle"],
        "to_user_id": row["to_user_id"], "to_handle": target["handle"], "amount": row["amount"],
        "captured_amount": row["captured_amount"], "remaining_amount": remaining(row, now),
        "currency": get_meta(db)["currency"], "note": row["note"], "visibility": row["visibility"],
        "status": status, "expires_at": row["expires_at"], "closed_at":closed_at,
        "payment_id": row["payment_id"], "payment_ids": json.loads(row["payment_ids_json"]),
        "created_at": row["created_at"],
    }


def capture_value(body):
    if "amount" not in body:
        return None
    value = body["amount"]
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)) or value < 1:
        validation("Invalid capture amount")
    if isinstance(value, Decimal) and (not value.is_finite() or value != value.to_integral_value()):
        validation("Invalid capture amount")
    return value


def prepare_fixture_authorizations(fixture, users, payments, now=None):
    now = now or clock()
    ttl = lifetime(fixture.get("authorization_ttl_seconds", 600), now)
    records = fixture.get("authorizations", [])
    if not isinstance(records, list):
        validation("Invalid authorizations")
    wallets = {row[0]: row[5] for row in users}
    payment_by_id = {row[0]: row for row in payments}
    prepared = []
    ids = set()
    held = {}
    for item in records:
        if not isinstance(item, dict):
            validation("Invalid authorization")
        auth_id = fixture_record_id(item)
        source = required_string(item, "from_user_id", fixture=True)
        target = required_string(item, "to_user_id", fixture=True)
        value = amount(item)
        status = required_string(item, "status", fixture=True)
        expires_at = required_string(item, "expires_at", fixture=True)
        expiration = expiry(expires_at)
        captured = number_as_integer(item.get("captured_amount", value if status == "captured" else 0), 0, value)
        if auth_id in ids or source not in wallets or target not in wallets or source == target or status not in STATUSES or captured is None:
            validation("Invalid authorization")
        if status == "open" and captured == value:
            validation("An open authorization must have a remainder")
        payment_id = item.get("payment_id")
        payment_ids = item.get("payment_ids", [] if payment_id is None else [payment_id])
        if not isinstance(payment_ids, list) or any(not identifier(pid) or pid not in payment_by_id for pid in payment_ids):
            validation("Invalid authorization payments")
        if len(set(payment_ids)) != len(payment_ids) or payment_id != (payment_ids[len(payment_ids) - 1] if payment_ids else None):
            validation("Invalid latest capture")
        if any(payment_by_id[pid][1:3] != (source, target) for pid in payment_ids):
            validation("Invalid capture parties")
        if sum(payment_by_id[pid][3] for pid in payment_ids) > captured:
            validation("Invalid captured amount")
        if status == "open" and expiration > instant(now):
            held[source] = held.get(source, 0) + value - captured
        ids.add(auth_id)
        prepared.append((auth_id, source, target, value, captured, note(item, fixture=True), visibility(item, fixture=True), status, expires_at, payment_id, json.dumps(payment_ids)))
    if any(value > wallets[user_id] for user_id, value in held.items()):
        validation("Seeded holds exceed wallet total")
    links = []
    owners = {pid: row[0] for row in prepared for pid in json.loads(row[10])}
    if len(owners) != sum(len(json.loads(row[10])) for row in prepared):
        validation("A capture belongs to only one authorization")
    for item in fixture.get("payments", []):
        auth_id = item.get("authorization_id", owners.get(item["id"]))
        if auth_id is not None:
            if auth_id not in ids or owners.get(item["id"]) != auth_id or item.get("request_id") is not None or item.get("settlement_id") is not None:
                validation("Invalid payment authorization")
            links.append((auth_id, item["id"]))
    return ttl, prepared, links
