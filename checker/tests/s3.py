"""Stage-3 helpers: a deterministic seeded history with known balances at every instant.

    users (ending balances): ada 10000, bob 2500, cy 500, dee 700   (total 13700)
    p_a  ada -> bob 1000  at T1
    p_b  bob -> cy   300  at T2   (tie with p_c; "p_b" < "p_c" bytewise)
    p_c  ada -> cy   200  at T2
    p_d  cy  -> ada  100  at T3

    opening: ada 11100, bob 1800, cy 100, dee 700
    ada: T1 10100, T2 9900, T3 10000      bob: T1 2800, T2 2500      cy: T2 600, T3 500
"""

from __future__ import annotations

import datetime as dt

from pf import PASSWORD

T1 = "2026-01-01T10:00:00+00:00"
T2 = "2026-01-02T10:00:00+00:00"
T3 = "2026-01-03T10:00:00+00:00"
TOTAL = 10000 + 2500 + 500 + 700
OPENING = {"ada": 11100, "bob": 1800, "cy": 100, "dee": 700}


def user(uid, handle, balance):
    return {"id": uid, "email": f"{handle}@example.com", "password": PASSWORD,
            "display_name": handle.title(), "handle": handle, "balance": balance}


def history_fixture(**over):
    fx = {
        "currency": "EUR", "minor_units": 2, "settlement_operator_ids": ["u_dee"],
        "users": [user("u_ada", "ada", 10000), user("u_bob", "bob", 2500),
                  user("u_cy", "cy", 500), user("u_dee", "dee", 700)],
        "payments": [
            {"id": "p_a", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1000, "note": "rent",
             "visibility": "public", "created_at": T1},
            {"id": "p_b", "from_user_id": "u_bob", "to_user_id": "u_cy", "amount": 300, "note": "",
             "visibility": "private", "created_at": T2},
            {"id": "p_c", "from_user_id": "u_ada", "to_user_id": "u_cy", "amount": 200, "note": "gift",
             "visibility": "public", "created_at": T2},
            {"id": "p_d", "from_user_id": "u_cy", "to_user_id": "u_ada", "amount": 100, "note": "back",
             "visibility": "public", "created_at": T3},
        ],
        "requests": [], "authorizations": [],
    }
    fx.update(over)
    return fx


def at(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso(d: dt.datetime) -> str:
    return d.isoformat()


def shift(ts: str, seconds: float) -> str:
    return iso(at(ts) + dt.timedelta(seconds=seconds))


def now_iso(delta=0.0) -> str:
    return iso(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=delta))
