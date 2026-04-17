"""
Migration: Add email verification and password reset columns to admin_users
"""


def up(conn):
    """Apply the migration."""
    with conn.cursor() as cur:
        # Add columns only if they don't already exist (MySQL 8+: IF NOT EXISTS)
        # MySQL 5.x doesn't support IF NOT EXISTS for ADD COLUMN, so we wrap each
        for col_sql in [
            "ALTER TABLE admin_users ADD COLUMN email_verified_at DATETIME NULL DEFAULT NULL",
            "ALTER TABLE admin_users ADD COLUMN email_verification_token VARCHAR(64) NULL DEFAULT NULL",
            "ALTER TABLE admin_users ADD COLUMN verification_token_expires DATETIME NULL DEFAULT NULL",
            "ALTER TABLE admin_users ADD COLUMN password_reset_token VARCHAR(64) NULL DEFAULT NULL",
            "ALTER TABLE admin_users ADD COLUMN password_reset_expires DATETIME NULL DEFAULT NULL",
        ]:
            try:
                cur.execute(col_sql)
            except Exception as e:
                if 'Duplicate column name' in str(e) or '1060' in str(e):
                    pass  # Column already exists — skip
                else:
                    raise
    conn.commit()


def down(conn):
    """Reverse the migration."""
    with conn.cursor() as cur:
        for col in [
            'email_verified_at',
            'email_verification_token',
            'verification_token_expires',
            'password_reset_token',
            'password_reset_expires',
        ]:
            try:
                cur.execute(f"ALTER TABLE admin_users DROP COLUMN {col}")
            except Exception:
                pass
    conn.commit()
