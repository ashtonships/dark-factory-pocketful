"""Dev-only stand-in for stage-3/history.py (Builder's W-9a), implementing the
interface W-10 asked for, over the stage-2 tables plus test-injected revisions.
Not part of any stage; replaced by the real module as soon as W-9a lands."""
import re
from datetime import datetime, timezone

RFC3339 = re.compile(r"(\d{4})-(\d\d)-(\d\d)[Tt](\d\d):(\d\d):(\d\d)(\.\d+)?([Zz]|[+-]\d\d:\d\d)")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
REVISIONS = {}      # payment_id -> [(revision, amount, effective_us, recorded_us)] added by tests
GENERATION = ["g0"]


def instant_us(text):
    if not isinstance(text, str) or not RFC3339.fullmatch(text):
        raise ValueError("not an RFC 3339 instant with an offset")
    return now_us(datetime.fromisoformat(text.replace("z", "Z").replace("t", "T").replace("Z", "+00:00")))


def now_us(moment):
    delta = moment.astimezone(timezone.utc) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def _text(us):
    return datetime.fromtimestamp(us / 1000000, timezone.utc).isoformat()


def _revisions(row):
    created = instant_us(row["created_at"])
    return [(1, row["amount"], created, created)] + REVISIONS.get(row["id"], [])


def selected_movements(db, user_id, known_us):
    out = []
    for row in db.execute("SELECT * FROM payments WHERE from_user_id = ? OR to_user_id = ?", (user_id, user_id)):
        known = [r for r in _revisions(row) if r[3] <= known_us]
        if not known:
            continue
        revision, amount, effective, recorded = max(known)
        sign = -1 if row["from_user_id"] == user_id else 1
        out.append({"payment_id": row["id"], "revision": revision, "amount": amount, "effective_us": effective,
                    "effective_at": _text(effective), "recorded_at": _text(recorded), "delta": sign * amount, "row": row})
    out.sort(key=lambda m: (m["effective_us"], m["payment_id"]))
    return out


def opening(db, user_id):
    balance = db.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()["balance"]
    for row in db.execute("SELECT * FROM payments WHERE from_user_id = ? OR to_user_id = ?", (user_id, user_id)):
        balance -= (-1 if row["from_user_id"] == user_id else 1) * row["amount"]
    return balance


def total_at(db, user_id, t_us, known_us, inclusive):
    moves = selected_movements(db, user_id, known_us)
    return opening(db, user_id) + sum(m["delta"] for m in moves if (m["effective_us"] <= t_us if inclusive else m["effective_us"] < t_us))


def held_at(db, user_id, t_us, known_us):
    held = 0
    for row in db.execute("SELECT * FROM authorizations WHERE from_user_id = ? AND status = 'open'", (user_id,)):
        if instant_us(row["created_at"]) <= min(t_us, known_us) < instant_us(row["expires_at"]) or (
                instant_us(row["created_at"]) <= known_us and instant_us(row["created_at"]) <= t_us < instant_us(row["expires_at"])):
            held += row["amount"] - row["captured_amount"]
    return held


def reset_generation(db):
    return GENERATION[0]
