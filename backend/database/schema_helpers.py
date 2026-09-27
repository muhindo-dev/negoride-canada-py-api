"""Idempotent DDL helpers shared by the v4 migrations.

MySQL 5.7 (MAMP) has no `ADD COLUMN IF NOT EXISTS`, so every helper swallows the
"already exists" error codes and re-raises anything else. That makes each
migration safe to re-run and safe against the Truckeroo backend, which shares
the local `negoride` database.
"""

_ALREADY = ('1060', '1061', '1050', 'Duplicate column name', 'Duplicate key name',
            'already exists')
_MISSING = ('1091', "check that column/key exists", "Unknown table", '1051')


def _run(cur, sql, ignore):
    try:
        cur.execute(sql)
    except Exception as e:  # pymysql errors carry the code in str(e)
        if any(tok in str(e) for tok in ignore):
            return
        raise


def add_columns(conn, table, columns):
    """columns: list of 'name TYPE ...' fragments."""
    with conn.cursor() as cur:
        for col in columns:
            _run(cur, f"ALTER TABLE {table} ADD COLUMN {col}", _ALREADY)
    conn.commit()


def drop_columns(conn, table, names):
    with conn.cursor() as cur:
        for name in names:
            _run(cur, f"ALTER TABLE {table} DROP COLUMN {name}", _MISSING)
    conn.commit()


def add_index(conn, table, name, cols, unique=False):
    kind = 'UNIQUE INDEX' if unique else 'INDEX'
    with conn.cursor() as cur:
        _run(cur, f"CREATE {kind} {name} ON {table} ({cols})", _ALREADY)
    conn.commit()


def create_tables(conn, ddl_list):
    with conn.cursor() as cur:
        for ddl in ddl_list:
            _run(cur, ddl, _ALREADY)
    conn.commit()


def drop_tables(conn, names):
    with conn.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        for name in names:
            _run(cur, f"DROP TABLE IF EXISTS {name}", _MISSING)
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()


TABLE_OPTS = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
