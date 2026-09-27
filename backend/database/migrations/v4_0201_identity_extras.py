"""
v4 · P4 identity extras (spec §11, §14, §15, §19.8) — additive columns used by
phone verification (dev-fallback code hash, Lookup line type), deferred account
status changes, SMS opt-out (STOP), background-check deductions / re-check
reminders and support SLA tracking.
"""
from backend.database.schema_helpers import add_columns, add_index, drop_columns

COLUMNS = {
    'phone_verifications': [
        "code_hash CHAR(64) NULL DEFAULT NULL",
        "line_type VARCHAR(30) NULL DEFAULT NULL",
        "locale VARCHAR(5) NULL DEFAULT NULL",
    ],
    'admin_users': [
        "pending_status_meta JSON NULL",
        "sms_opt_out_at DATETIME NULL DEFAULT NULL",
    ],
    'background_checks': [
        "deduction_status VARCHAR(20) NULL DEFAULT NULL",
        "deduction_settled_at DATETIME NULL DEFAULT NULL",
        "recheck_reminded_at DATETIME NULL DEFAULT NULL",
        "provider_score VARCHAR(30) NULL DEFAULT NULL",
    ],
    'support_tickets': [
        "first_response_at DATETIME NULL DEFAULT NULL",
        "closed_by INT NULL DEFAULT NULL",
    ],
}


def up(conn):
    for table, cols in COLUMNS.items():
        add_columns(conn, table, cols)
    add_index(conn, 'admin_users', 'ix_admin_users_pending_status', 'pending_account_status')


def down(conn):
    for table, cols in COLUMNS.items():
        drop_columns(conn, table, [c.split()[0] for c in cols])
