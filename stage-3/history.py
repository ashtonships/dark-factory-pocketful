"""Pure stage-3 history queries; caller owns authentication, snapshot and clock.

parse_instant(text) returns an exact, comparable Decimal UTC second key. T and K
in every function accept that key or an aware datetime (never naive datetimes).
selected_revisions returns entry dictionaries: payment (selected amount), revision,
effective_at, recorded_at, delta. statement_rows adds balance_after and returns
the full ordered window, before any pagination. Functions never write or read a
clock. One caller-captured T/K must be reused for every query in a response.
"""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

SECONDS_PER_DAY = 24 * 60 * 60
RFC3339 = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]+))?([Zz]|[+-][0-9]{2}:[0-9]{2})")


def parse_instant(text):
    from core import validation
    match = RFC3339.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        validation("Expected an RFC3339 instant with offset")
    year, month, day, hour, minute, second = map(int, match.groups()[:6])
    fraction = match.group(7) or ""
    offset = match.group(8)
    try:
        date = datetime(year, month, day, hour, minute, second)
        offset_seconds = 0
        if offset.lower() != "z":
            offset_hour, offset_minute = map(int, offset[1:].split(":"))
            if offset_hour >= 24 or offset_minute >= 60:
                raise ValueError("Offset outside range")
            offset_seconds = (offset_hour * 60 + offset_minute) * 60
            if offset.startswith("-"):
                offset_seconds = -offset_seconds
        whole = date.toordinal() * SECONDS_PER_DAY + hour * 3600 + minute * 60 + second - offset_seconds
        # Construct rather than add Decimals, preserving arbitrarily fine fractions.
        return Decimal(str(whole) + ("." + fraction if fraction else ""))
    except (ValueError, OverflowError):
        validation("Invalid RFC3339 instant")


def instant(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, datetime) and value.tzinfo is not None:
        return parse_instant(value.isoformat())
    return parse_instant(value)


def selected_revisions(conn, user_id, K):
    from core import payment_body
    cutoff = instant(K)
    payments = conn.execute("SELECT * FROM payments WHERE from_user_id = ? OR to_user_id = ?", (user_id, user_id)).fetchall()
    selected = []
    for payment in payments:
        revisions = conn.execute("SELECT * FROM payment_revisions WHERE payment_id = ? ORDER BY revision DESC", (payment["id"],)).fetchall()
        revision = next((row for row in revisions if parse_instant(row["recorded_at"]) <= cutoff), None)
        if revision is None:
            continue
        body = payment_body(conn, payment)
        body["amount"] = revision["amount"]
        selected.append({"payment": body, "revision": revision["revision"], "effective_at": revision["effective_at"],
                         "recorded_at": revision["recorded_at"], "delta": -revision["amount"] if payment["from_user_id"] == user_id else revision["amount"]})
    return selected


def opening(conn, user_id):
    row = conn.execute("SELECT opening_amount FROM wallet_openings WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise ValueError("Missing wallet opening")
    return row["opening_amount"]


def total(conn, user_id, T, K, *, inclusive=True):
    boundary = instant(T)
    balance = opening(conn, user_id)
    for row in selected_revisions(conn, user_id, K):
        at = parse_instant(row["effective_at"])
        if at < boundary or (inclusive and at == boundary):
            balance += row["delta"]
    return balance


def held(conn, user_id, T, K):
    boundary, known = instant(T), instant(K)
    value = 0
    holds = conn.execute("SELECT a.*, b.baseline_at, b.held_amount, b.provenance FROM authorizations a JOIN authorization_history_baselines b ON b.authorization_id = a.id WHERE a.from_user_id = ?", (user_id,)).fetchall()
    for hold in holds:
        creation = parse_instant(hold["baseline_at"])
        if creation > boundary or creation > known or hold["provenance"] == "closed_legacy":
            continue
        if parse_instant(hold["expires_at"]) <= boundary:
            continue
        remainder = hold["held_amount"]
        events = conn.execute("SELECT * FROM authorization_events WHERE authorization_id = ? ORDER BY seq", (hold["id"],)).fetchall()
        for event in events:
            at = parse_instant(event["event_at"])
            if event["kind"] != "expiry" and at <= boundary and at <= known:
                remainder = event["remaining_amount"]
        value += remainder
    return value


def statement_rows(conn, user_id, start, end, K):
    left = instant(start) if start is not None else Decimal("-Infinity")
    right = instant(end)
    rows = sorted(selected_revisions(conn, user_id, K), key=lambda row: (parse_instant(row["effective_at"]), row["payment"]["payment_id"]))
    balance = opening(conn, user_id)
    entries = []
    for row in rows:
        at = parse_instant(row["effective_at"])
        balance += row["delta"]
        if left <= at < right:
            entries.append(dict(row, balance_after=balance))
    return entries


def boundaries(conn, user_id, K):
    result = {parse_instant(row["effective_at"]) for row in selected_revisions(conn, user_id, K)}
    for hold in conn.execute("SELECT a.*, b.baseline_at FROM authorizations a JOIN authorization_history_baselines b ON b.authorization_id=a.id WHERE a.from_user_id=?", (user_id,)):
        result.add(parse_instant(hold["baseline_at"]))
        result.add(parse_instant(hold["expires_at"]))
        result.update(parse_instant(row["event_at"]) for row in conn.execute("SELECT event_at FROM authorization_events WHERE authorization_id=?", (hold["id"],)))
    return sorted(result)


def has_overdraft(conn, user_ids, now):
    cutoff = instant(now)
    for user_id in user_ids:
        if opening(conn, user_id) < 0:
            return True
        for boundary in boundaries(conn, user_id, cutoff):
            if boundary > cutoff:
                continue
            balance = total(conn, user_id, boundary, cutoff)
            if balance < 0 or balance - held(conn, user_id, boundary, cutoff) < 0:
                return True
    return False
