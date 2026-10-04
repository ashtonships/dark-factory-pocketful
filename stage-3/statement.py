"""Pocketful stage-3 read side (W-10): historical GET /me and GET /statement.

Every money figure comes from the shared history evaluator (history.py, owned by
the W-9 writes) so reads and historical-overdraft checks cannot diverge. Both
functions run inside the server's read transaction, under the write lock, with
the handler's single clock reading as "now" (D-16, 9015).

Snapshots are kept in this process until reset (ledger 2084-2094): each one is
bound to its owner and to the reset generation it was taken in, and holds the
complete, already computed window, so paging never recomputes anything.
"""
import secrets
import threading
from urllib.parse import parse_qs, urlsplit

import history
from core import APIError, get_meta, payment_body, validation

TEMPORAL = ("as_of", "known_at")
WINDOW = ("from", "to", "known_at")

_snapshots = {}
_snapshots_lock = threading.Lock()


def _query(path):
    return parse_qs(urlsplit(path).query, keep_blank_values=True)


def _last(values):
    """A repeated parameter takes its last value, as the stage-1 pagination does."""
    *_, last = values
    return last


def _instant(query, name):
    """(original text, UTC microseconds) for a supplied instant, (None, None) if absent.
    A supplied value that is not an RFC 3339 instant with an offset, including an
    empty one, is 422 (ledger 2014, 2076)."""
    if name not in query:
        return None, None
    text = _last(query[name])
    try:
        return text, history.instant_us(text)
    except (ValueError, OverflowError, TypeError):
        validation("Invalid " + name)


def temporal(path):
    """True when GET /me carries as_of or known_at; otherwise /me is unchanged (2015)."""
    query = _query(path)
    return any(name in query for name in TEMPORAL)


def me(handler, db, user):
    """GET /me?as_of=T&known_at=K: all four money fields from the same T and K (2102)."""
    query = _query(handler.path)
    as_of_text, as_of = _instant(query, "as_of")
    known_text, known = _instant(query, "known_at")
    now = history.now_us(handler.now)
    at = now if as_of is None else as_of
    known = now if known is None else known
    total = history.total_at(db, user["id"], at, known, True)
    held = history.held_at(db, user["id"], at, known)
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
    with _snapshots_lock:
        snapshot = _snapshots.get(token)
    if snapshot is None or snapshot["owner"] != user["id"] or snapshot["generation"] != history.reset_generation(db):
        raise APIError(404, "not_found")
    return snapshot


def _take(handler, db, user, query):
    """Compute the full window once and freeze it (2085)."""
    from_text, start = _instant(query, "from")
    to_text, end = _instant(query, "to")
    known_text, known = _instant(query, "known_at")
    now = history.now_us(handler.now)
    end = now if end is None else end           # the default `to` is frozen with the snapshot
    known = now if known is None else known
    if start is not None and start > end:
        validation("from must not be later than to")
    user_id = user["id"]
    opening = history.opening(db, user_id) if start is None else history.total_at(db, user_id, start, known, False)
    running = opening
    entries = []
    for move in history.selected_movements(db, user_id, known):
        if move["effective_us"] >= end or (start is not None and move["effective_us"] < start):
            continue
        running += move["delta"]
        payment = payment_body(db, move["row"])
        payment["amount"] = move["amount"]
        entries.append({
            "payment": payment, "delta": move["delta"], "balance_after": running,
            "revision": move["revision"], "effective_at": move["effective_at"], "recorded_at": move["recorded_at"],
        })
    head = {"opening_balance": opening, "closing_balance": running}
    for name, text in (("from", from_text), ("to", to_text), ("known_at", known_text)):
        if text is not None:
            head[name] = text
    generation = history.reset_generation(db)
    token = secrets.token_urlsafe()
    snapshot = {"owner": user_id, "generation": generation, "head": head, "entries": entries, "token": token}
    with _snapshots_lock:
        for stale in [key for key, value in _snapshots.items() if value["generation"] != generation]:
            del _snapshots[stale]
        _snapshots[token] = snapshot
    return snapshot


def _page(snapshot, limit, offset):
    entries = snapshot["entries"]
    result = dict(snapshot["head"])
    result["entries"] = entries[offset:offset + limit]
    result["has_more"] = offset + limit < len(entries)
    result["snapshot"] = snapshot["token"]
    return result
