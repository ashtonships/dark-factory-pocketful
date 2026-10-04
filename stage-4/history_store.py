"""Stage-3 storage helpers. All write calls run in the caller's writer transaction."""
import json
from datetime import datetime, timezone
from core import identifier, new_id, validation
from history import has_overdraft, instant, parse_instant, total

HISTORY_TABLES = {"wallet_openings", "payment_revisions", "authorization_history_baselines"}


def original(conn, payment_id):
    row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
    at = row["created_at"]
    if row["settlement_id"]:
        settlement = conn.execute("SELECT committed_at FROM settlements WHERE id=?", (row["settlement_id"],)).fetchone()
        if settlement:
            at = settlement["committed_at"]
    conn.execute("INSERT INTO payment_revisions(payment_id,revision,amount,effective_at,recorded_at,reason) VALUES(?, 1, ?, ?, ?, '')", (payment_id, row["amount"], at, at))


def baseline(conn, authorization_id, provenance="created", held_amount=None):
    hold = conn.execute("SELECT * FROM authorizations WHERE id=?", (authorization_id,)).fetchone()
    amount = hold["amount"] if held_amount is None else held_amount
    conn.execute("INSERT INTO authorization_history_baselines VALUES(?, ?, ?, ?)", (authorization_id, hold["created_at"], amount, provenance))


def upgrade_tables(source, now, force=False):
    tables = dict(source)
    if HISTORY_TABLES <= set(tables) and not force:
        return tables
    tables["payment_revisions"] = []
    net = {user["id"]: 0 for user in tables["users"]}
    settlements = {row["id"]: row for row in tables["settlements"]}
    for payment in tables["payments"]:
        at = settlements.get(payment["settlement_id"], {}).get("committed_at", payment["created_at"])
        tables["payment_revisions"].append({"payment_id":payment["id"], "revision":1, "amount":payment["amount"], "effective_at":at, "recorded_at":at, "reason":"", "correction_batch_id":None})
        if payment["from_user_id"] not in net or payment["to_user_id"] not in net:
            validation("Invalid payment parties")
        net[payment["from_user_id"]] -= payment["amount"]
        net[payment["to_user_id"]] += payment["amount"]
    tables["wallet_openings"] = [{"user_id":user["id"], "opening_amount":user["balance"]-net[user["id"]]} for user in tables["users"]]
    events = tables["authorization_events"]
    tables["authorization_history_baselines"] = []
    for hold in tables["authorizations"]:
        own = [event for event in events if event["authorization_id"]==hold["id"]]
        captured = sum(payment["amount"] for event in own if event["kind"]=="capture" for payment in tables["payments"] if payment["id"]==event["payment_id"])
        closed = hold["status"] in ("captured", "voided", "expired")
        provenance = "closed_legacy" if closed and not own else "legacy"
        amount = 0 if provenance == "closed_legacy" else hold["amount"]-hold["captured_amount"]+captured
        tables["authorization_history_baselines"].append({"authorization_id":hold["id"], "baseline_at":hold["created_at"], "held_amount":amount, "provenance":provenance})
    tables["meta"] = list(tables["meta"])
    keys = {row["key"] for row in tables["meta"]}
    for key, value in (("reset_generation",new_id("generation_")),("clock_high_water",now.isoformat())):
        if key not in keys:
            tables["meta"].append({"key":key,"value":value})
    return tables


def seed(conn, now):
    for payment in conn.execute("SELECT id FROM payments").fetchall():
        original(conn, payment["id"])
    for user in conn.execute("SELECT id,balance FROM users").fetchall():
        net = sum((-row["amount"] if row["from_user_id"] == user["id"] else row["amount"]) for row in conn.execute("SELECT * FROM payments WHERE from_user_id=? OR to_user_id=?", (user["id"],user["id"])))
        conn.execute("INSERT INTO wallet_openings VALUES(?, ?)", (user["id"],user["balance"]-net))
    for hold in conn.execute("SELECT * FROM authorizations").fetchall():
        baseline(conn,hold["id"],"closed_legacy" if hold["status"] != "open" else "seed",0 if hold["status"] != "open" else hold["amount"]-hold["captured_amount"])
    validate(conn,now)


def validate(conn, now):
    meta = {row["key"]:row["value"] for row in conn.execute("SELECT * FROM meta")}
    if not meta.get("reset_generation") or "clock_high_water" not in meta or parse_instant(meta["clock_high_water"]) > instant(now):
        validation("Invalid history metadata")
    users = {row["id"]:row for row in conn.execute("SELECT * FROM users")}
    openings = {row["user_id"]:row for row in conn.execute("SELECT * FROM wallet_openings")}
    if set(users) != set(openings):
        validation("Invalid wallet openings")
    payments = {row["id"]:row for row in conn.execute("SELECT * FROM payments")}
    grouped = {}
    for revision in conn.execute("SELECT * FROM payment_revisions ORDER BY revision"):
        if revision["payment_id"] not in payments or not 0 <= revision["amount"] <= 1000000000:
            validation("Invalid payment revision")
        if parse_instant(revision["effective_at"]) > instant(now) or parse_instant(revision["recorded_at"]) > instant(now):
            validation("Future payment revision")
        if parse_instant(revision["recorded_at"]) > parse_instant(meta["clock_high_water"]):
            validation("Recorded revision exceeds clock high-water mark")
        grouped.setdefault(revision["payment_id"],[]).append(revision)
    if set(grouped) != set(payments):
        validation("Missing payment revision")
    for payment_id,revisions in grouped.items():
        payment = payments[payment_id]
        original_at = payment["created_at"]
        if payment["settlement_id"]:
            settlement = conn.execute("SELECT committed_at FROM settlements WHERE id=?", (payment["settlement_id"],)).fetchone()
            if settlement:
                original_at = settlement["committed_at"]
        previous = None
        for index,revision in enumerate(revisions,1):
            if revision["revision"] != index or (index==1 and (revision["amount"] != payment["amount"] or revision["reason"] != "" or revision["correction_batch_id"] is not None or parse_instant(revision["effective_at"]) != parse_instant(original_at) or parse_instant(revision["recorded_at"]) != parse_instant(original_at))):
                validation("Invalid original revision")
            if index > 1 and (not 1 <= len(revision["reason"]) <= 200 or payment["authorization_id"] or payment["refund_of"] or (payment["settlement_id"] and revision["correction_batch_id"] is None) or parse_instant(revision["recorded_at"]) <= previous):
                validation("Invalid correction history")
            previous = parse_instant(revision["recorded_at"])
    refunded={}
    for payment in payments.values():
        target_id=payment["refund_of"]
        if target_id is None:
            continue
        target=payments.get(target_id)
        if target is None or target["refund_of"] is not None or payment["from_user_id"]!=target["to_user_id"] or payment["to_user_id"]!=target["from_user_id"] or payment["request_id"] is not None or payment["authorization_id"] is not None or payment["settlement_id"] is not None or payment["note"]!=target["note"] or payment["visibility"]!=target["visibility"] or parse_instant(payment["created_at"])<parse_instant(target["created_at"]):
            validation("Invalid refund linkage")
        refunded[target_id]=refunded.get(target_id,0)+payment["amount"]
    if any(value>max(grouped[payment_id],key=lambda revision:revision["revision"])["amount"] for payment_id,value in refunded.items()):
        validation("Refunds exceed corrected payment")
    batches={}
    for revisions in grouped.values():
        for revision in revisions:
            identity=revision["correction_batch_id"]
            if identity is not None:
                if not identifier(identity):
                    validation("Invalid correction batch identity")
                batches.setdefault(identity,[]).append(revision)
    for revisions in batches.values():
        if not 1<=len(revisions)<=32 or len({r["payment_id"] for r in revisions})!=len(revisions) or len({parse_instant(r["recorded_at"]) for r in revisions})!=1:
            validation("Invalid correction batch history")
        by_id={r["payment_id"]:r for r in revisions}
        settlement_ids={payments[r["payment_id"]]["settlement_id"] for r in revisions}-{None}
        for identity in settlement_ids:
            members={p["id"] for p in payments.values() if p["settlement_id"]==identity}
            if not members<=set(by_id) or len({parse_instant(by_id[pid]["effective_at"]) for pid in members})!=1:
                validation("Invalid settlement correction batch")
    holds = {row["id"]:row for row in conn.execute("SELECT * FROM authorizations")}
    baselines = {row["authorization_id"]:row for row in conn.execute("SELECT * FROM authorization_history_baselines")}
    if set(holds) != set(baselines):
        validation("Missing hold baseline")
    for identity,row in baselines.items():
        if row["provenance"] not in ("created","seed","legacy","closed_legacy") or not 0 <= row["held_amount"] <= holds[identity]["amount"] or parse_instant(row["baseline_at"]) > instant(now):
            validation("Invalid hold baseline")
    if any(total(conn,user_id,now,now) != row["balance"] for user_id,row in users.items()) or has_overdraft(conn,users,now):
        validation("Inconsistent historical balances")
