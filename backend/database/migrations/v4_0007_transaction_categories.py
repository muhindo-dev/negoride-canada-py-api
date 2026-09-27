"""
v4 · Extend transactions.category (additive: the new ENUM is the union of the
existing values and the v4 ones, so values another app added are preserved).
"""
import re

NEW = ['tip', 'cancellation_fee', 'ride_credit', 'clawback', 'referral_bonus', 'background_check_fee']


def _current(cur):
    cur.execute("SHOW COLUMNS FROM transactions LIKE 'category'")
    row = cur.fetchone()
    return re.findall(r"'((?:[^']|'')*)'", row[1])


def up(conn):
    with conn.cursor() as cur:
        values = _current(cur)
        merged = values + [v for v in NEW if v not in values]
        if merged != values:
            enum = ','.join("'" + v + "'" for v in merged)
            cur.execute(f"ALTER TABLE transactions MODIFY category ENUM({enum}) NOT NULL")
    conn.commit()


def down(conn):
    pass  # never shrink an ENUM that live rows may use
