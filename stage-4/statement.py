"""Pocketful stage-3 read side (W-10): historical GET /me and GET /statement.

Every money figure comes from the shared history evaluator (history.py, owned by
the W-9 writes) so reads and historical-overdraft checks cannot diverge. Both
functions run inside the server's read transaction, under the write lock, with
the handler's single clock reading as "now" (D-16, 9015).

Snapshots live in the statement_snapshots table until reset (ledger 2084-2094,
D-27): each row is bound to its owner and to the reset generation it was taken in,
and holds the complete, already computed window as JSON, so paging never
recomputes anything. The rows are written in the caller's transaction.
export_snapshots/import_snapshots carry them through /_test/export and import
(3046); imported tokens bind to the importing service's generation.
"""
import json
import secrets
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import history
from core import APIError, get_meta, validation

TEMPORAL = ("as_of", "known_at")
WINDOW = ("from", "to", "known_at")



def _query(path):
    return parse_qs(urlsplit(path).query, keep_blank_values=True)


def _last(values):
    """A repeated parameter takes its last value, as the stage-1 pagination does."""
    *_, last = values
    return last


def _instant(query, name):
    """(original text, exact UTC key) for a supplied instant, (None, None) if absent.
    A supplied value that is not an RFC 3339 instant with an offset, including an
    empty one, is 422 (ledger 2014, 2076); history.parse_instant raises it."""
    if name not in query:
        return None, None
    text = _last(query[name])
    return text, history.parse_instant(text)


def _generation(db):
    """Changes only at reset; import keeps the local value (ledger 2094)."""
    return get_meta(db)["reset_generation"]


def temporal(path):
    """True when GET /me carries as_of or known_at; otherwise /me is unchanged (2015)."""
    query = _query(path)
    return any(name in query for name in TEMPORAL)


def me(handler, db, user):
    """GET /me?as_of=T&known_at=K: all four money fields from the same T and K (2102)."""
    query = _query(handler.path)
    as_of_text, as_of = _instant(query, "as_of")
    known_text, known = _instant(query, "known_at")
    now = history.instant(handler.now)
    at = now if as_of is None else as_of
    known = now if known is None else known
    total = history.total(db, user["id"], at, known)
    held = history.held(db, user["id"], at, known)
    meta = get_meta(db)
    result = {
        "user_id": user["id"], "display_name": user["display_name"], "handle": user["handle"],
        "balance": total, "total": total, "available": total - held, "held": held,
        "currency": meta["currency"], "minor_units": int(meta["minor_units"]),
    }
    if as_of_text is not None:
        result["as_of"] = as_of_text
    if known_text is not None:
        result["known_at"] = known_text
    return result


def statement(handler, db, user):
    query, limit, offset = handler.pagination()
    if "snapshot" in query:
        if any(name in query for name in WINDOW):
            validation("A snapshot takes only limit and offset")
        return _page(_lookup(db, user, _last(query["snapshot"])), limit, offset)
    return _page(_take(handler, db, user, query), limit, offset)


def _lookup(db, user, token):
    row = db.execute("SELECT * FROM statement_snapshots WHERE token = ?", (token,)).fetchone()
    if row is None or row["user_id"] != user["id"] or row["generation"] != _generation(db):
        raise APIError(404, "not_found")
    head = json.loads(row["snapshot_json"])
    entries = head.pop("entries")
    return {"owner": row["user_id"], "generation": row["generation"], "head": head, "entries": entries, "token": token}


def _store(db, snapshot):
    db.execute("INSERT INTO statement_snapshots(token, user_id, generation, snapshot_json) VALUES(?, ?, ?, ?)",
               (snapshot["token"], snapshot["owner"], snapshot["generation"],
                json.dumps(dict(snapshot["head"], entries=snapshot["entries"]), ensure_ascii=False, separators=(",", ":"))))


def _take(handler, db, user, query):
    """Compute the full window once and freeze it (2085)."""
    from_text, start = _instant(query, "from")
    to_text, end = _instant(query, "to")
    known_text, known = _instant(query, "known_at")
    now = history.instant(handler.now)
    known = now if known is None else known
    if end is None:
        # The default `to` is now, frozen with the snapshot. A future `from` with no
        # `to` is not an inverted range: the window is empty at `from` (D-20 amended).
        end = now if start is None or start <= now else start
    elif start is not None and start > end:
        validation("from must not be later than to")
    user_id = user["id"]
    opening = history.opening(db, user_id) if start is None else history.total(db, user_id, start, known, inclusive=False)
    entries = history.statement_rows(db, user_id, start, end, known)
    closing = opening + sum(entry["delta"] for entry in entries)
    head = {"opening_balance": opening, "closing_balance": closing}
    for name, text in (("from", from_text), ("to", to_text), ("known_at", known_text)):
        if text is not None:
            head[name] = text
    generation = _generation(db)
    token = secrets.token_urlsafe()
    snapshot = {"owner": user_id, "generation": generation, "head": head, "entries": entries, "token": token}
    db.execute("DELETE FROM statement_snapshots WHERE generation != ?", (generation,))
    _store(db, snapshot)
    return snapshot


def _page(snapshot, limit, offset):
    entries = snapshot["entries"]
    result = dict(snapshot["head"])
    result["entries"] = entries[offset:offset + limit]
    result["has_more"] = offset + limit < len(entries)
    result["snapshot"] = snapshot["token"]
    return result


HEAD_NUMBERS = ("opening_balance", "closing_balance")
HEAD_TEXTS = ("from", "to", "known_at")


def _plain(value):
    """Imported JSON numbers arrive as Decimal; frozen results hold only integers."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            validation("Invalid snapshot number")
        return int(value)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _plain(item) for key, item in value.items()}
    validation("Invalid snapshot value")


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _imported(item):
    """One exported snapshot, checked and normalized; the result is fully self-consistent."""
    if not isinstance(item, dict):
        validation("Invalid snapshot")
    token, user_id, result = item.get("token"), item.get("user_id"), _plain(item.get("result"))
    if not isinstance(token, str) or not token or not isinstance(user_id, str) or not user_id or not isinstance(result, dict):
        validation("Invalid snapshot")
    head = {}
    for name in HEAD_NUMBERS:
        if not _integer(result.get(name)):
            validation("Invalid snapshot balance")
        head[name] = result[name]
    for name in HEAD_TEXTS:
        if name in result:
            if not isinstance(result[name], str):
                validation("Invalid snapshot window")
            head[name] = result[name]
    entries = result.get("entries")
    if not isinstance(entries, list) or not all(
            isinstance(entry, dict) and isinstance(entry.get("payment"), dict) and _integer(entry.get("delta")) and _integer(entry.get("balance_after"))
            for entry in entries):
        validation("Invalid snapshot entries")
    if head["opening_balance"] + sum(entry["delta"] for entry in entries) != head["closing_balance"]:
        validation("Snapshot balances do not add up")
    return token, user_id, head, entries


def export_snapshots(db):
    """Every live snapshot (current generation) as JSON-safe dicts, sorted by token."""
    rows = db.execute("SELECT * FROM statement_snapshots WHERE generation = ? ORDER BY token", (_generation(db),)).fetchall()
    exported = []
    for row in rows:
        exported.append({"token": row["token"], "user_id": row["user_id"], "result": json.loads(row["snapshot_json"])})
    return exported


def _record(snapshot, generation):
    result = dict(snapshot["result"])
    entries = result.pop("entries")
    return {"owner": snapshot["user_id"], "generation": generation, "head": result, "entries": entries, "token": snapshot["token"]}


def validate_snapshots(items):
    """The export's `snapshots` value (None: no snapshots) checked and normalized into
    export-shaped dicts. Raises 422 validation_failed on any bad shape; it never
    changes the store."""
    if items is None:
        return []
    if not isinstance(items, list):
        validation("Invalid snapshots")
    valid = {}
    for item in items:
        token, user_id, head, entries = _imported(item)
        snapshot = {"token": token, "user_id": user_id, "result": dict(head, entries=entries)}
        if valid.get(token, snapshot) != snapshot:
            validation("Conflicting snapshot token")
        valid[token] = snapshot
    return list(valid.values())


def import_snapshots(db, items):
    """Merge exported snapshots into statement_snapshots, bound to this service's
    current generation, inside the caller's import transaction. Local tokens stay
    until reset, an identical token replays, and a token that would change a live
    frozen result is 422."""
    generation = _generation(db)
    for snapshot in validate_snapshots(items):
        row = db.execute("SELECT * FROM statement_snapshots WHERE token = ?", (snapshot["token"],)).fetchone()
        if row is not None and row["generation"] == generation and (
                row["user_id"] != snapshot["user_id"] or json.loads(row["snapshot_json"]) != snapshot["result"]):
            validation("Conflicting snapshot token")
        db.execute("DELETE FROM statement_snapshots WHERE token = ?", (snapshot["token"],))
        _store(db, _record(snapshot, generation))
