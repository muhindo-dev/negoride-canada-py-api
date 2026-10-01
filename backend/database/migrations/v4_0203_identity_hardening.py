"""
v4 · identity / onboarding hardening (audit follow-up, spec §11.2 #12, §12, §14).

* admin_users.verified_phone — STORED generated column = phone_e164 while the
  phone is verified and the account not deleted, with a UNIQUE index, so the
  database itself guarantees one verified phone per account (MySQL 5.7 OK).
* marketing_consents — CASL proof: every grant / withdrawal of marketing
  consent with ip, user agent, wording version + text, source, timestamp.
* driver_documents — meta JSON (e.g. insurance rideshare-endorsement
  attestation) and face-match result on the selfie.
* background_checks — per-check consent evidence, delayed Certn start
  (cancel/refund window), refund bookkeeping, partial pay-later recovery,
  fee receipt email.
"""
from backend.database.schema_helpers import (
    add_columns, add_index, create_tables, drop_columns, drop_tables, TABLE_OPTS)

USER_COLUMNS = [
    "verified_phone VARCHAR(20) GENERATED ALWAYS AS "
    "(IF(phone_verified_at IS NOT NULL AND deleted_at IS NULL, phone_e164, NULL)) STORED",
]

COLUMNS = {
    'driver_documents': [
        "meta JSON NULL",
        "face_match_status VARCHAR(20) NULL DEFAULT NULL",
        "face_match_score DECIMAL(5,2) NULL DEFAULT NULL",
        "face_match_provider VARCHAR(30) NULL DEFAULT NULL",
        "face_match_checked_at DATETIME NULL DEFAULT NULL",
        "face_match_detail VARCHAR(500) NULL DEFAULT NULL",
    ],
    'background_checks': [
        "consent_evidence JSON NULL",
        "start_after DATETIME NULL DEFAULT NULL",
        "refunded_cents BIGINT NOT NULL DEFAULT 0",
        "refunded_at DATETIME NULL DEFAULT NULL",
        "cancelled_at DATETIME NULL DEFAULT NULL",
        "deducted_cents BIGINT NOT NULL DEFAULT 0",
        "receipt_emailed_at DATETIME NULL DEFAULT NULL",
    ],
}

TABLES = [
    f"""CREATE TABLE marketing_consents (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        action VARCHAR(10) NOT NULL,
        channels VARCHAR(40) NOT NULL DEFAULT 'email,sms',
        source VARCHAR(40) NOT NULL,
        wording_version VARCHAR(40) NULL,
        wording_text TEXT NULL,
        language VARCHAR(5) NULL,
        ip VARCHAR(64) NULL,
        user_agent VARCHAR(500) NULL,
        app_version VARCHAR(30) NULL,
        created_at DATETIME NOT NULL,
        KEY ix_mc_user (user_id, created_at)
    ) {TABLE_OPTS}""",
]


def up(conn):
    add_columns(conn, 'admin_users', USER_COLUMNS)
    add_index(conn, 'admin_users', 'uq_admin_users_verified_phone', 'verified_phone', unique=True)
    for table, cols in COLUMNS.items():
        add_columns(conn, table, cols)
    add_index(conn, 'background_checks', 'ix_bgc_start_after', 'status, start_after')
    create_tables(conn, TABLES)


def down(conn):
    drop_tables(conn, ['marketing_consents'])
    for table, cols in COLUMNS.items():
        drop_columns(conn, table, [c.split()[0] for c in cols])
    with conn.cursor() as cur:
        try:
            cur.execute("DROP INDEX uq_admin_users_verified_phone ON admin_users")
        except Exception:
            pass
    conn.commit()
    drop_columns(conn, 'admin_users', ['verified_phone'])
