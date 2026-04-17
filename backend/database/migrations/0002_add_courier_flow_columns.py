"""
Migration: Add courier flow and compliance columns to scheduled_bookings
"""


def up(conn):
    with conn.cursor() as cur:
        for col_sql in [
            "ALTER TABLE scheduled_bookings ADD COLUMN community_guidelines_accepted TINYINT(1) NOT NULL DEFAULT 0",
            "ALTER TABLE scheduled_bookings ADD COLUMN community_guidelines_accepted_at DATETIME NULL DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN courier_batch_id VARCHAR(64) NULL DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN courier_sequence INT NOT NULL DEFAULT 1",
            "ALTER TABLE scheduled_bookings ADD COLUMN courier_total INT NOT NULL DEFAULT 1",
            "ALTER TABLE scheduled_bookings ADD COLUMN courier_next_booking_id BIGINT NULL DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN pickup_proof_image TEXT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN pickup_proof_uploaded_at DATETIME NULL DEFAULT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN dropoff_proof_image TEXT NULL",
            "ALTER TABLE scheduled_bookings ADD COLUMN dropoff_proof_uploaded_at DATETIME NULL DEFAULT NULL",
        ]:
            try:
                cur.execute(col_sql)
            except Exception as e:
                if 'Duplicate column name' in str(e) or '1060' in str(e):
                    pass
                else:
                    raise

        try:
            cur.execute("CREATE INDEX idx_scheduled_bookings_courier_batch ON scheduled_bookings(courier_batch_id)")
        except Exception:
            pass
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("DROP INDEX idx_scheduled_bookings_courier_batch ON scheduled_bookings")
        except Exception:
            pass

        for col in [
            'community_guidelines_accepted',
            'community_guidelines_accepted_at',
            'courier_batch_id',
            'courier_sequence',
            'courier_total',
            'courier_next_booking_id',
            'pickup_proof_image',
            'pickup_proof_uploaded_at',
            'dropoff_proof_image',
            'dropoff_proof_uploaded_at',
        ]:
            try:
                cur.execute(f"ALTER TABLE scheduled_bookings DROP COLUMN {col}")
            except Exception:
                pass
    conn.commit()
