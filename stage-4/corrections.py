"""Shared correction helpers. Caller owns one idempotent writer transaction.

Prepare items in input order, check_current with their combined_effects, choose a
shared recorded_time, insert every revision, check_history, then apply_balances.
An exception rolls all provisional revisions back with the caller's transaction.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from core import APIError, MAX_BALANCE, amount, new_id, payment_body, retain_clock, validation
from history import has_overdraft, instant, parse_instant
from holds import wallet_funds


def refunded_total(conn,payment_id):
    return conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE refund_of=?",(payment_id,)).fetchone()[0]


def immutable(payment):
    return payment["authorization_id"] is not None or payment["refund_of"] is not None


def validate_fields(body,now):
    expected=body.get("expected_revision")
    if isinstance(expected,bool) or not isinstance(expected,(int,Decimal)) or expected<1 or (isinstance(expected,Decimal) and (not expected.is_finite() or expected!=expected.to_integral_value())):
        validation("Invalid expected revision")
    value=amount(body,minimum=0)
    reason=body.get("reason")
    if not isinstance(reason,str) or not 1<=len(reason)<=200:
        validation("Invalid correction reason")
    effective=body.get("effective_at")
    if parse_instant(effective)>instant(now):
        validation("Correction cannot take effect in the future")
    return {"expected_revision":expected,"amount":value,"effective_at":effective,"reason":reason}


def prepare_item(conn,body,payment_id,now,*,sender_id=None,allow_settlement=False):
    item=validate_fields(body,now)
    payment=conn.execute("SELECT * FROM payments WHERE id=?",(payment_id,)).fetchone()
    if payment is None:
        raise APIError(404,"not_found")
    if sender_id is not None and payment["from_user_id"]!=sender_id:
        raise APIError(403,"forbidden")
    # Preserve single-correction linked-payment precedence from the prior stage.
    if not allow_settlement and (payment["settlement_id"] is not None or immutable(payment)):
        raise APIError(422,"linked_payment_immutable")
    latest=conn.execute("SELECT * FROM payment_revisions WHERE payment_id=? ORDER BY revision DESC LIMIT 1",(payment_id,)).fetchone()
    if item["expected_revision"]!=latest["revision"]:
        raise APIError(409,"stale_revision")
    if immutable(payment):
        raise APIError(422,"linked_payment_immutable")
    if item["amount"]<refunded_total(conn,payment_id):
        raise APIError(422,"refund_exceeds_payment")
    return dict(item,payment=payment,latest=latest)


def combined_effects(items):
    changes={}
    for item in items:
        difference=item["amount"]-item["latest"]["amount"]
        source,target=item["payment"]["from_user_id"],item["payment"]["to_user_id"]
        changes[source]=changes.get(source,0)-difference
        changes[target]=changes.get(target,0)+difference
    return changes


def check_current(conn,changes,now):
    balances={user_id:conn.execute("SELECT balance FROM users WHERE id=?",(user_id,)).fetchone()[0] for user_id in changes}
    if any(wallet_funds(conn,user_id,balance,now)["available"]+changes[user_id]<0 for user_id,balance in balances.items()):
        raise APIError(409,"insufficient_funds")
    if any(balance+changes[user_id]>MAX_BALANCE for user_id,balance in balances.items()):
        validation("Balance limit exceeded")


def recorded_time(handler,items):
    recorded=handler.now
    for item in items:
        if instant(recorded)<=parse_instant(item["latest"]["recorded_at"]):
            previous=datetime.fromisoformat(item["latest"]["recorded_at"].replace("Z","+00:00").replace("z","+00:00"))
            recorded=previous+timedelta(microseconds=1)
    handler.now=recorded
    retain_clock(recorded)
    return recorded


def insert_revision(conn,item,recorded_at,correction_batch_id=None):
    at=recorded_at.isoformat(timespec="microseconds") if isinstance(recorded_at,datetime) else recorded_at
    result={"payment_id":item["payment"]["id"],"revision":item["latest"]["revision"]+1,"amount":item["amount"],
            "effective_at":item["effective_at"],"recorded_at":at,"reason":item["reason"],"correction_batch_id":correction_batch_id}
    conn.execute("INSERT INTO payment_revisions(payment_id,revision,amount,effective_at,recorded_at,reason,correction_batch_id) VALUES(?,?,?,?,?,?,?)",tuple(result.values()))
    return result


def check_history(conn,changes,now,*,status=409):
    if has_overdraft(conn,changes,now):
        raise APIError(status,"historical_overdraft")


def apply_balances(conn,changes):
    conn.executemany("UPDATE users SET balance=balance+? WHERE id=?",((change,user_id) for user_id,change in changes.items()))


def correct(handler,conn,user,body,payment_id):
    item=prepare_item(conn,body,payment_id,handler.now,sender_id=user["id"])
    changes=combined_effects([item])
    check_current(conn,changes,handler.now)
    recorded=recorded_time(handler,[item])
    result=insert_revision(conn,item,recorded)
    check_history(conn,changes,recorded)
    apply_balances(conn,changes)
    return result


def refund(handler,conn,user,body,payment_id):
    value=amount(body)
    payment=conn.execute("SELECT * FROM payments WHERE id=?",(payment_id,)).fetchone()
    if payment is None:
        raise APIError(404,"not_found")
    if user["id"]!=payment["to_user_id"]:
        raise APIError(403,"forbidden")
    if payment["refund_of"] is not None:
        raise APIError(422,"invalid_refund_target")
    latest=conn.execute("SELECT amount FROM payment_revisions WHERE payment_id=? ORDER BY revision DESC LIMIT 1",(payment_id,)).fetchone()
    if refunded_total(conn,payment_id)+value>latest["amount"]:
        raise APIError(422,"refund_exceeds_payment")
    changes={payment["to_user_id"]:-value,payment["from_user_id"]:value}
    check_current(conn,changes,handler.now)
    identity=new_id("p_")
    conn.execute("INSERT INTO payments(id,from_user_id,to_user_id,amount,note,visibility,created_at,refund_of) VALUES(?,?,?,?,?,?,?,?)",
                 (identity,payment["to_user_id"],payment["from_user_id"],value,payment["note"],payment["visibility"],handler.now.isoformat(),payment_id))
    from history_store import original
    original(conn,identity)
    apply_balances(conn,changes)
    return payment_body(conn,conn.execute("SELECT * FROM payments WHERE id=?",(identity,)).fetchone())


def revisions(conn,user,payment_id):
    payment=conn.execute("SELECT from_user_id,to_user_id FROM payments WHERE id=?",(payment_id,)).fetchone()
    if payment is None or user["id"] not in (payment["from_user_id"],payment["to_user_id"]):
        raise APIError(404,"not_found")
    return {"revisions":[dict(row) for row in conn.execute("SELECT * FROM payment_revisions WHERE payment_id=? ORDER BY revision",(payment_id,))]}
