"""Stage-4 correction batches (W-12): an operator corrects several payments atomically.

The caller supplies the idempotent BEGIN IMMEDIATE transaction (server.idempotent), so
every check reads the state the inserts write to, and any raised error rolls back
revisions, balances and the idempotency record together (3034). Checks follow D-23:
item errors in input order, settlement completeness, settlement instants, combined
current affordability, then historical boundaries under all proposed revisions at once.
The per-item steps are the shared helpers in corrections.py, so single corrections and
batches cannot drift apart.
"""
from core import APIError, new_id, validation
from corrections import apply_balances, check_current, check_history, combined_effects, insert_revision, prepare_item, recorded_time
from history import parse_instant

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


def _prepare(conn, item, now):
    payment_id = item.get("payment_id")
    if not isinstance(payment_id, str) or not payment_id:
        validation("Invalid payment_id")
    return prepare_item(conn, item, payment_id, now, allow_settlement=True)


def _settlements(conn, plan):
    """Every member of a touched settlement, all at one instant (3027, 3028)."""
    included = {entry["payment"]["id"] for entry in plan}
    groups = {}
    for entry in plan:
        if entry["payment"]["settlement_id"] is not None:
            groups.setdefault(entry["payment"]["settlement_id"], []).append(entry)
    for settlement_id in groups:
        members = {row["id"] for row in conn.execute("SELECT id FROM payments WHERE settlement_id = ?", (settlement_id,))}
        if not members <= included:
            raise APIError(422, "incomplete_settlement")
    for entries in groups.values():
        if len({parse_instant(entry["effective_at"]) for entry in entries}) != 1:
            validation("Settlement members must share one effective instant")


def create(handler, conn, user, body):
    plan = [_prepare(conn, item, handler.now) for item in _items(body)]
    _settlements(conn, plan)
    changes = combined_effects(plan)
    check_current(conn, changes, handler.now)
    recorded = recorded_time(handler, plan)
    batch_id = new_id("cb_")
    revisions = [insert_revision(conn, entry, recorded, batch_id) for entry in plan]
    check_history(conn, changes, recorded)
    apply_balances(conn, changes)
    return {"correction_batch_id": batch_id, "recorded_at": revisions[0]["recorded_at"], "revisions": revisions}
