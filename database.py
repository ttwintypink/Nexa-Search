import sqlite3
import time
from pathlib import Path
from typing import Optional, Any

DB_PATH = Path(__file__).with_name("nexa_search.db")


def now() -> int:
    return int(time.time())


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                ref_by INTEGER,
                attempts INTEGER DEFAULT 3,
                total_referrals INTEGER DEFAULT 0,
                premium_until INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                last_msg_id INTEGER DEFAULT NULL,
                last_search_at INTEGER DEFAULT 0,
                registered_at INTEGER DEFAULT 0,
                last_restore_at INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS found_usernames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                length INTEGER NOT NULL,
                with_digits INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                stars INTEGER NOT NULL,
                days INTEGER NOT NULL,
                charge_id TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                value INTEGER NOT NULL,
                max_uses INTEGER DEFAULT 0,
                used_count INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS promo_uses (
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                used_at INTEGER NOT NULL,
                PRIMARY KEY (code, user_id)
            );
            """
        )


def ensure_user(user_id: int, first_name: str = "", username: str = "", ref_by: Optional[int] = None, free_attempts: int = 3) -> tuple[sqlite3.Row, bool]:
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            db.execute("UPDATE users SET first_name=?, username=? WHERE user_id=?", (first_name, username, user_id))
            return db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone(), False
        ts = now()
        db.execute(
            "INSERT INTO users(user_id, first_name, username, ref_by, attempts, registered_at, last_restore_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, first_name, username, ref_by, free_attempts, ts, ts),
        )
        return db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone(), True


def get_user(user_id: int) -> Optional[sqlite3.Row]:
    with connect() as db:
        return db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def update_user(user_id: int, **kwargs: Any) -> None:
    if not kwargs:
        return
    cols = ", ".join([f"{k}=?" for k in kwargs])
    vals = list(kwargs.values()) + [user_id]
    with connect() as db:
        db.execute(f"UPDATE users SET {cols} WHERE user_id=?", vals)


def add_attempts(user_id: int, amount: int) -> None:
    with connect() as db:
        db.execute("UPDATE users SET attempts=attempts+? WHERE user_id=?", (amount, user_id))


def use_attempt(user_id: int) -> bool:
    with connect() as db:
        row = db.execute("SELECT attempts FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or row["attempts"] <= 0:
            return False
        db.execute("UPDATE users SET attempts=attempts-1, last_search_at=? WHERE user_id=?", (now(), user_id))
        return True


def set_premium(user_id: int, days: Optional[int] = None) -> int:
    ts = now()
    if days is None or days <= 0:
        premium_until = 4102444800  # 2100-01-01
    else:
        cur = get_user(user_id)
        base = max(ts, int(cur["premium_until"]) if cur else 0)
        premium_until = base + days * 86400
    with connect() as db:
        db.execute("UPDATE users SET premium_until=? WHERE user_id=?", (premium_until, user_id))
    return premium_until




def set_premium_seconds(user_id: int, seconds: Optional[int] = None, replace: bool = False) -> int:
    """Set or extend Premium.

    seconds=None means permanent.
    replace=True is for admin grants: the new term is counted from now and can downgrade
    an old permanent/long Premium to a shorter testing term.
    replace=False is for purchases: the new term is added to an active term.
    """
    ts = now()
    if seconds is None or seconds <= 0:
        premium_until = 4102444800  # 2100-01-01
    else:
        cur = get_user(user_id)
        current_until = int(cur["premium_until"]) if cur else 0
        base = ts if replace else max(ts, current_until)
        premium_until = base + int(seconds)
    with connect() as db:
        db.execute("UPDATE users SET premium_until=? WHERE user_id=?", (premium_until, user_id))
    return premium_until


def remove_premium(user_id: int) -> None:
    with connect() as db:
        db.execute("UPDATE users SET premium_until=0 WHERE user_id=?", (user_id,))

def restore_attempts_if_needed(user_id: int, daily_restore: int) -> int:
    user = get_user(user_id)
    if not user:
        return 0
    ts = now()
    last = int(user["last_restore_at"] or 0)
    if ts - last < 86400:
        return 0
    days = max(1, (ts - last) // 86400)
    add = int(days) * daily_restore
    with connect() as db:
        db.execute("UPDATE users SET attempts=attempts+?, last_restore_at=? WHERE user_id=?", (add, ts, user_id))
    return add


def record_referral(referrer_id: int, bonus: int) -> None:
    with connect() as db:
        db.execute("UPDATE users SET total_referrals=total_referrals+1, attempts=attempts+? WHERE user_id=?", (bonus, referrer_id))


def save_last_msg(user_id: int, message_id: Optional[int]) -> None:
    with connect() as db:
        db.execute("UPDATE users SET last_msg_id=? WHERE user_id=?", (message_id, user_id))


def add_found(user_id: int, username: str, length: int, with_digits: bool) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO found_usernames(user_id, username, length, with_digits, created_at) VALUES(?,?,?,?,?)",
            (user_id, username, length, int(with_digits), now()),
        )


def add_payment(user_id: int, stars: int, days: int, charge_id: str = "") -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO payments(user_id, stars, days, charge_id, created_at) VALUES(?,?,?,?,?)",
            (user_id, stars, days, charge_id, now()),
        )


def stats() -> dict[str, int]:
    with connect() as db:
        total = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        prem = db.execute("SELECT COUNT(*) c FROM users WHERE premium_until>?", (now(),)).fetchone()["c"]
        found = db.execute("SELECT COUNT(*) c FROM found_usernames").fetchone()["c"]
        pays = db.execute("SELECT COUNT(*) c, COALESCE(SUM(stars),0) s FROM payments").fetchone()
        banned = db.execute("SELECT COUNT(*) c FROM users WHERE is_banned=1").fetchone()["c"]
        return {"users": total, "premium": prem, "found": found, "payments": pays["c"], "stars": pays["s"], "banned": banned}


def recent_users(limit: int = 10) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("SELECT * FROM users ORDER BY registered_at DESC LIMIT ?", (limit,)).fetchall()


def recent_found(limit: int = 10) -> list[sqlite3.Row]:
    with connect() as db:
        return db.execute("SELECT * FROM found_usernames ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()


def all_user_ids() -> list[int]:
    with connect() as db:
        return [r["user_id"] for r in db.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()]
