"""Stage-4 correction batches (W-12): an operator corrects several payments atomically.

The caller supplies the idempotent BEGIN IMMEDIATE transaction (server.idempotent), so
every check below reads the same state the inserts write to, and any raised error rolls
back revisions, balances and the idempotency record together (3034). Checks follow D-23:
item errors in input order, settlement completeness, settlement instants, combined current
affordability, then historical boundaries under all proposed revisions at once.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from core import APIError, MAX_BALANCE, amount, new_id, retain_clock, validation
from history import has_overdraft, instant, parse_instant
from holds import wallet_funds

MAX_ITEMS = 32


def _items(body):
    """1..32 objects with distinct payment_ids (3023)."""
    items = body.get("corrections")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS or not all(isinstance(item, dict) for item in items):
        validation("corrections must contain 1 to 32 objects")
    seen = set()
    for item in items:
        payment_id = item.get("payment_id")
        if isinstance(payment_id, str):
            if payment_id in seen:
                validation("Duplicate payment_id")
            seen.add(payment_id)
    return items


def _fields(item, now):
    """The ordinary correction fields and validation (3024, 3037)."""
    payment_id = item.get("payment_id")
    if not isinstance(payment_id, str) or not payment_id:
        validation("Invalid payment_id")
    expected = item.get("expected_revision")
    if isinstance(expected, bool) or not isinstance(expected, (int, Decimal)) or expected < 1 or (
            isinstance(expected, Decimal) and (not expected.is_finite() or expected != expected.to_integral_value())):
        validation("Invalid expected revision")
    value = amount(item, minimum=0)
    reason = item.get("reason")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 200:
        validation("Invalid correction reason")
    effective = item.get("effective_at")
    if parse_instant(effective) > now:
        validation("Correction cannot take effect in the future")
    return payment_id, int(expected), value, reason, effective


def _immutable(payment):
    """Captures and refunds are linked payments that no correction may change (3026)."""
    keys = payment.keys()
    return payment["authorization_id"] is not None or ("refund_of" in keys and payment["refund_of"] is not None)


def _refunded(conn, payment_id):
    if "refund_of" not in [row["name"] for row in conn.execute("PRAGMA table_info(payments)")]:
        return 0
    return conn.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE refund_of = ?", (payment_id,)).fetchone()[0]


def create(handler, conn, user, body):
    items = _items(body)
    now = instant(handler.now)
    plan = []
    for item in items:
        payment_id, expected, value, reason, effective = _fields(item, now)
        payment = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        if payment is None:
            raise APIError(404, "not_found")
        latest = conn.execute("SELECT * FROM payment_revisions WHERE payment_id = ? ORDER BY revision DESC LIMIT 1", (payment_id,)).fetchone()
        if expected != latest["revision"]:
            raise APIError(409, "stale_revision")
        if _immutable(payment):
            raise APIError(422, "linked_payment_immutable")
        if value < _refunded(conn, payment_id):
            raise APIError(422, "refund_exceeds_payment")
        plan.append({"payment": payment, "latest": latest, "amount": value, "reason": reason, "effective": effective})

    # Correcting any settlement member requires every member, at one instant (3027, 3028).
    included = {entry["payment"]["id"] for entry in plan}
    settlements = {}
    for entry in plan:
        settlement_id = entry["payment"]["settlement_id"]
        if settlement_id is not None:
            settlements.setdefault(settlement_id, []).append(entry)
    for settlement_id in settlements:
        members = {row["id"] for row in conn.execute("SELECT id FROM payments WHERE settlement_id = ?", (settlement_id,))}
        if not members <= included:
            raise APIError(422, "incomplete_settlement")
    for entries in settlements.values():
        if len({parse_instant(entry["effective"]) for entry in entries}) != 1:
            validation("Settlement members must share one effective instant")

    # Combined effect of every proposed revision on current available funds (3033).
    net = {}
    for entry in plan:
        payment, difference = entry["payment"], entry["amount"] - entry["latest"]["amount"]
        net[payment["from_user_id"]] = net.get(payment["from_user_id"], 0) - difference
        net[payment["to_user_id"]] = net.get(payment["to_user_id"], 0) + difference
    for user_id in sorted(net):
        balance = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()["balance"]
        if net[user_id] < 0 and wallet_funds(conn, user_id, balance, handler.now)["available"] + net[user_id] < 0:
            raise APIError(409, "insufficient_funds")
    for user_id in sorted(net):
        balance = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()["balance"]
        if balance + net[user_id] > MAX_BALANCE:
            validation("Balance limit exceeded")

    # One shared recorded_at, strictly later than every member's previous one (3036).
    recorded = handler.now
    for entry in plan:
        previous_text = entry["latest"]["recorded_at"]
        if instant(recorded) <= parse_instant(previous_text):
            previous = datetime.fromisoformat(previous_text.replace("Z", "+00:00").replace("z", "+00:00"))
            recorded = previous + timedelta(microseconds=1)
    handler.now = recorded
    retain_clock(recorded)
    recorded_text = recorded.isoformat(timespec="microseconds")

    batch_id = new_id("cb_")
    revisions = []
    for entry in plan:
        revision = {"payment_id": entry["payment"]["id"], "revision": entry["latest"]["revision"] + 1,
                    "amount": entry["amount"], "effective_at": entry["effective"], "recorded_at": recorded_text,
                    "reason": entry["reason"], "correction_batch_id": batch_id}
        conn.execute(
            "INSERT INTO payment_revisions(payment_id, revision, amount, effective_at, recorded_at, reason, correction_batch_id) VALUES(?, ?, ?, ?, ?, ?, ?)",
            tuple(revision.values()))
        revisions.append(revision)
    if has_overdraft(conn, sorted(net), recorded):
        raise APIError(409, "historical_overdraft")
    for user_id, change in net.items():
        conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (change, user_id))
    return {"correction_batch_id": batch_id, "recorded_at": recorded_text, "revisions": revisions}
