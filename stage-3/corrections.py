"""Payment revision writes; caller supplies the idempotent writer transaction."""
from datetime import datetime, timedelta
from decimal import Decimal
from core import APIError, MAX_BALANCE, amount, retain_clock, validation
from history import has_overdraft, instant, parse_instant
from holds import wallet_funds


def correct(handler, conn, user, body, payment_id):
    expected = body.get("expected_revision")
    if isinstance(expected, bool) or not isinstance(expected, (int,Decimal)) or expected < 1 or (isinstance(expected,Decimal) and (not expected.is_finite() or expected != expected.to_integral_value())):
        validation("Invalid expected revision")
    value = amount(body,minimum=0)
    reason = body.get("reason")
    if not isinstance(reason,str) or not 1 <= len(reason) <= 200:
        validation("Invalid correction reason")
    effective = body.get("effective_at")
    if parse_instant(effective) > instant(handler.now):
        validation("Correction cannot take effect in the future")
    payment = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    if payment is None:
        raise APIError(404,"not_found")
    if payment["from_user_id"] != user["id"]:
        raise APIError(403,"forbidden")
    if payment["settlement_id"] is not None or payment["authorization_id"] is not None:
        raise APIError(422,"linked_payment_immutable")
    latest = conn.execute("SELECT * FROM payment_revisions WHERE payment_id=? ORDER BY revision DESC LIMIT 1", (payment_id,)).fetchone()
    if expected != latest["revision"]:
        raise APIError(409,"stale_revision")
    difference = value-latest["amount"]
    debtor = payment["from_user_id"] if difference >= 0 else payment["to_user_id"]
    creditor = payment["to_user_id"] if difference >= 0 else payment["from_user_id"]
    debit = abs(difference)
    debtor_balance = conn.execute("SELECT balance FROM users WHERE id=?", (debtor,)).fetchone()["balance"]
    creditor_balance = conn.execute("SELECT balance FROM users WHERE id=?", (creditor,)).fetchone()["balance"]
    if wallet_funds(conn,debtor,debtor_balance,handler.now)["available"] < debit:
        raise APIError(409,"insufficient_funds")
    if creditor_balance+debit > MAX_BALANCE:
        validation("Balance limit exceeded")
    recorded = handler.now
    if instant(recorded) <= parse_instant(latest["recorded_at"]):
        previous = datetime.fromisoformat(latest["recorded_at"].replace("Z","+00:00").replace("z","+00:00"))
        recorded = previous + timedelta(microseconds=1)
    handler.now = recorded
    retain_clock(recorded)
    result = {"payment_id":payment_id,"revision":latest["revision"]+1,"amount":value,
              "effective_at":effective,"recorded_at":recorded.isoformat(timespec="microseconds"),"reason":reason}
    conn.execute("INSERT INTO payment_revisions VALUES(?,?,?,?,?,?)", tuple(result.values()))
    if has_overdraft(conn,(payment["from_user_id"],payment["to_user_id"]),recorded):
        raise APIError(409,"historical_overdraft")
    conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (debit,debtor))
    conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (debit,creditor))
    return result


def revisions(conn,user,payment_id):
    payment = conn.execute("SELECT from_user_id,to_user_id FROM payments WHERE id=?", (payment_id,)).fetchone()
    if payment is None or user["id"] not in (payment["from_user_id"],payment["to_user_id"]):
        raise APIError(404,"not_found")
    return {"revisions":[dict(row) for row in conn.execute("SELECT * FROM payment_revisions WHERE payment_id=? ORDER BY revision", (payment_id,))]}
