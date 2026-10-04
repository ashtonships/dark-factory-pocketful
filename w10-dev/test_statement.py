"""Dev-only logic tests for stage-3/statement.py against fake_history.py.
    python3 w10-dev/test_statement.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, "..", "stage-3")
os.environ["POCKETFUL_DB"] = os.path.join(tempfile.mkdtemp(), "w10.sqlite3")
sys.path.insert(0, STAGE)
sys.path.insert(0, HERE)
import fake_history  # noqa: E402
sys.modules["history"] = fake_history
import core  # noqa: E402
import statement  # noqa: E402
from core import APIError  # noqa: E402
from server import PocketfulHandler  # noqa: E402

passed = failed = 0


def check(name, cond, detail=None):
    global passed, failed
    if cond:
        passed += 1
        print("PASS " + name)
    else:
        failed += 1
        print("FAIL " + name + ("" if detail is None else " -- " + repr(detail)))


class Handler:
    pagination = PocketfulHandler.pagination

    def __init__(self, path, now):
        self.path, self.now = path, now


def status_of(fn):
    try:
        fn()
        return 200
    except APIError as e:
        return (e.status, e.code)


core.initialize()
db = core.connection()
core.reset(db, {
    "currency": "EUR", "minor_units": 2,
    "users": [
        {"id": "u_a", "email": "a@x.io", "password": "correct horse", "display_name": "A", "handle": "a", "balance": 10000},
        {"id": "u_b", "email": "b@x.io", "password": "correct horse", "display_name": "B", "handle": "b", "balance": 5000},
        {"id": "u_c", "email": "c@x.io", "password": "correct horse", "display_name": "C", "handle": "c", "balance": 1000},
    ],
})
U = lambda uid: db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def pay(pid, frm, to, amount, when):
    db.execute("INSERT INTO payments(id, from_user_id, to_user_id, amount, note, visibility, request_id, settlement_id, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (pid, frm, to, amount, "n " + pid, "public", None, None, when))
    db.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, frm))
    db.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, to))


T0 = "2026-09-20T10:00:00+00:00"
pay("p_2", "u_a", "u_b", 500, T0)            # tie at T0: ordered by id, p_1 then p_2
pay("p_1", "u_b", "u_a", 1200, T0)
pay("p_3", "u_a", "u_b", 300, "2026-09-21T10:00:00+00:00")
pay("p_x", "u_b", "u_c", 999, "2026-09-21T11:00:00+00:00")   # not a's
NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)

# ---------------- GET /me
check("/me without as_of/known_at keeps the old path", not statement.temporal("/me") and not statement.temporal("/me?foo=1"))
m = statement.me(Handler("/me?as_of=2026-09-20T12:00:00%2B02:00", NOW), db, U("u_a"))
check("as_of echoed exactly", m["as_of"] == "2026-09-20T12:00:00+02:00", m)
cur_a = U("u_a")["balance"]
open_a = fake_history.opening(db, "u_a")
check("opening balance = current minus net", open_a == cur_a - (1200 - 500 - 300), (open_a, cur_a))
m = statement.me(Handler("/me?as_of=2026-09-20T10:00:00Z", NOW), db, U("u_a"))
check("as_of == T0 includes both T0 payments", m["balance"] == open_a + 1200 - 500, m["balance"])
m = statement.me(Handler("/me?as_of=2026-09-20T09:59:59.999999Z", NOW), db, U("u_a"))
check("as_of before earliest = opening", m["balance"] == open_a and m["total"] == open_a)
m = statement.me(Handler("/me?as_of=2030-01-01T00:00:00Z", NOW), db, U("u_a"))
check("as_of after latest = current", m["balance"] == cur_a)
check("four fields agree: balance = total, available = total - held", m["balance"] == m["total"] and m["available"] == m["total"] - m["held"])
for bad in ["", "2026-09-20", "2026-09-20T10:00:00", "2026-09-20 10:00:00+00:00", "2026-02-30T10:00:00Z", "yesterday"]:
    check("as_of %r is 422" % bad, status_of(lambda: statement.me(Handler("/me?as_of=" + bad.replace("+", "%2B"), NOW), db, U("u_a"))) == (422, "validation_failed"))
check("known_at empty is 422", status_of(lambda: statement.me(Handler("/me?known_at=", NOW), db, U("u_a"))) == (422, "validation_failed"))
m = statement.me(Handler("/me?known_at=2026-09-20T10:00:00%2B00:00", NOW), db, U("u_a"))
check("known_at echoed exactly", m["known_at"] == "2026-09-20T10:00:00+00:00")

# ---------------- GET /statement
s = statement.statement(Handler("/statement", NOW), db, U("u_a"))
ids = [e["payment"]["payment_id"] for e in s["entries"]]
check("own payments only, oldest first, ties by id", ids == ["p_1", "p_2", "p_3"], ids)
check("deltas signed", [e["delta"] for e in s["entries"]] == [1200, -500, -300])
check("opening + sum(delta) = closing", s["opening_balance"] + sum(e["delta"] for e in s["entries"]) == s["closing_balance"])
check("default window opening is the wallet opening", s["opening_balance"] == open_a)
check("closing equals current when to defaults to now", s["closing_balance"] == cur_a)
check("entries carry revision, effective_at, recorded_at", all(set(("revision", "effective_at", "recorded_at", "payment", "delta", "balance_after")) <= set(e) for e in s["entries"]))
check("snapshot token returned", isinstance(s.get("snapshot"), str) and len(s["snapshot"]) <= 64)
full = [(e["payment"]["payment_id"], e["balance_after"]) for e in s["entries"]]
pages = []
for off in range(0, 4):
    p = statement.statement(Handler("/statement?snapshot=%s&limit=1&offset=%d" % (s["snapshot"], off), NOW), db, U("u_a"))
    pages.append(p)
check("paging keeps balance_after", [(e["payment"]["payment_id"], e["balance_after"]) for p in pages[:3] for e in p["entries"]] == full)
check("has_more true until the last entry", [p["has_more"] for p in pages] == [True, True, False, False], [p["has_more"] for p in pages])
check("offset beyond the end: no entries, has_more false", pages[3]["entries"] == [] and not pages[3]["has_more"])
check("paging keeps opening/closing", all(p["opening_balance"] == s["opening_balance"] and p["closing_balance"] == s["closing_balance"] for p in pages))
p2 = statement.statement(Handler("/statement?limit=2&offset=1", NOW), db, U("u_a"))
check("fresh paged statement: balance_after independent of offset", [(e["payment"]["payment_id"], e["balance_after"]) for e in p2["entries"]] == full[1:3])

# half-open window
w = statement.statement(Handler("/statement?from=2026-09-20T10:00:00Z&to=2026-09-21T10:00:00Z", NOW), db, U("u_a"))
check("window [from, to): includes at from, excludes at to", [e["payment"]["payment_id"] for e in w["entries"]] == ["p_1", "p_2"], [e["payment"]["payment_id"] for e in w["entries"]])
check("window opening = balance before from", w["opening_balance"] == open_a)
check("window closing = balance before to", w["closing_balance"] == open_a + 700)
check("window echoes from and to exactly", w["from"] == "2026-09-20T10:00:00Z" and w["to"] == "2026-09-21T10:00:00Z")
e = statement.statement(Handler("/statement?from=2026-09-21T10:00:00Z&to=2026-09-21T10:00:00Z", NOW), db, U("u_a"))
check("from == to: empty window, opening == closing", e["entries"] == [] and e["opening_balance"] == e["closing_balance"])
check("from > to is 422", status_of(lambda: statement.statement(Handler("/statement?from=2026-09-22T00:00:00Z&to=2026-09-21T00:00:00Z", NOW), db, U("u_a"))) == (422, "validation_failed"))
for name in ("from", "to", "known_at"):
    check("snapshot with %s is 422" % name, status_of(lambda: statement.statement(Handler("/statement?snapshot=%s&%s=2026-09-21T00:00:00Z" % (s["snapshot"], name), NOW), db, U("u_a"))) == (422, "validation_failed"))
    check("snapshot with empty %s is 422" % name, status_of(lambda: statement.statement(Handler("/statement?snapshot=%s&%s=" % (s["snapshot"], name), NOW), db, U("u_a"))) == (422, "validation_failed"))
check("snapshot ignores unknown params", status_of(lambda: statement.statement(Handler("/statement?snapshot=%s&zzz=1" % s["snapshot"], NOW), db, U("u_a"))) == 200)
check("another user's snapshot is 404", status_of(lambda: statement.statement(Handler("/statement?snapshot=" + s["snapshot"], NOW), db, U("u_b"))) == (404, "not_found"))
check("unknown snapshot is 404", status_of(lambda: statement.statement(Handler("/statement?snapshot=nope", NOW), db, U("u_a"))) == (404, "not_found"))
check("bad limit still 422 with snapshot", status_of(lambda: statement.statement(Handler("/statement?snapshot=%s&limit=0" % s["snapshot"], NOW), db, U("u_a"))) == (422, "validation_failed"))

# frozen snapshot vs later payment and a correction
pay("p_4", "u_b", "u_a", 50, "2026-09-22T10:00:00+00:00")
fake_history.REVISIONS["p_3"] = [(2, 0, fake_history.instant_us("2026-09-21T10:00:00Z"), fake_history.instant_us("2026-09-24T00:00:00Z"))]
again = statement.statement(Handler("/statement?snapshot=" + s["snapshot"], NOW), db, U("u_a"))
check("snapshot unchanged after a payment and a correction", [(x["payment"]["payment_id"], x["balance_after"], x["payment"]["amount"]) for x in again["entries"]] ==
      [(x["payment"]["payment_id"], x["balance_after"], x["payment"]["amount"]) for x in s["entries"]])
new = statement.statement(Handler("/statement", NOW), db, U("u_a"))
p3 = [x for x in new["entries"] if x["payment"]["payment_id"] == "p_3"][0]
check("new statement selects the correction: zero amount shown with delta 0", p3["payment"]["amount"] == 0 and p3["delta"] == 0 and p3["revision"] == 2, p3)
check("correction is not counted alongside the revision it replaces", len([x for x in new["entries"] if x["payment"]["payment_id"] == "p_3"]) == 1)
old = statement.statement(Handler("/statement?known_at=2026-09-23T00:00:00Z", NOW), db, U("u_a"))
p3o = [x for x in old["entries"] if x["payment"]["payment_id"] == "p_3"][0]
check("known_at before the correction selects revision 1", p3o["revision"] == 1 and p3o["delta"] == -300 and old["known_at"] == "2026-09-23T00:00:00Z")
none = statement.statement(Handler("/statement?known_at=2026-09-01T00:00:00Z", NOW), db, U("u_a"))
check("known_at before any payment was recorded: nothing contributes", none["entries"] == [])
check("opening + sum = closing with corrections", new["opening_balance"] + sum(x["delta"] for x in new["entries"]) == new["closing_balance"])

# reset generation invalidates snapshots
fake_history.GENERATION[0] = "g1"
check("snapshot from before reset is 404", status_of(lambda: statement.statement(Handler("/statement?snapshot=" + s["snapshot"], NOW), db, U("u_a"))) == (404, "not_found"))

print("%d/%d passed" % (passed, passed + failed))
sys.exit(1 if failed else 0)
