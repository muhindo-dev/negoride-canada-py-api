"""
v4 · §13.3 weekly driver earnings statements.

One row per (driver, ISO week). Amounts are INTEGER CENTS, CAD. The unique key
makes `receipt_jobs.weekly_driver_statements()` idempotent per driver-week.
"""
from backend.database.schema_helpers import create_tables, drop_tables, TABLE_OPTS

TABLES = [
    f"""CREATE TABLE driver_statements (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        number VARCHAR(40) NOT NULL,
        driver_id INT NOT NULL,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        currency CHAR(3) NOT NULL DEFAULT 'cad',
        gross_cents BIGINT NOT NULL DEFAULT 0,
        commission_cents BIGINT NOT NULL DEFAULT 0,
        fees_cents BIGINT NOT NULL DEFAULT 0,
        net_cents BIGINT NOT NULL DEFAULT 0,
        payouts_cents BIGINT NOT NULL DEFAULT 0,
        totals JSON NOT NULL,
        pdf_path VARCHAR(500) NULL,
        emailed_at DATETIME NULL,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_driver_statements_week (driver_id, period_start),
        UNIQUE KEY uq_driver_statements_number (number),
        KEY ix_driver_statements_period (period_start)
    ) {TABLE_OPTS}""",
]


def up(conn):
    create_tables(conn, TABLES)


def down(conn):
    drop_tables(conn, ['driver_statements'])
