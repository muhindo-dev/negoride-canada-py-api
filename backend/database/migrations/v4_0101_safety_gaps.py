"""
v4 · Safety audit gaps (spec §8.4, §9.1, §10.1)

  • ride_routes          planned route polyline per ride (route-deviation checks)
  • ride_pin_failures    wrong ride-PIN attempts (brute-force lock, sliding window)
  • dispute_resolved_at  on negotiations / scheduled_bookings / trip_bookings
                         (recordings + breadcrumbs of a disputed ride are kept
                         until the dispute is resolved + recording.hold_after_case_days)
  • help_contacts        non-emergency police lines for SK, NB, PE, NL, YT, NT, NU
"""
from backend.database.schema_helpers import add_columns, create_tables, drop_columns, drop_tables, TABLE_OPTS

TABLES = [
    f"""CREATE TABLE ride_routes (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        target VARCHAR(10) NOT NULL,
        polyline MEDIUMTEXT NOT NULL,
        distance_m INT NULL,
        duration_s INT NULL,
        source VARCHAR(20) NOT NULL DEFAULT 'straight_line',
        created_at DATETIME NOT NULL,
        KEY ix_ride_routes_ride (ride_type, ride_id, target, id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE ride_pin_failures (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        actor_id INT NULL,
        created_at DATETIME NOT NULL,
        KEY ix_pin_fail_ride (ride_type, ride_id, created_at)
    ) {TABLE_OPTS}""",
]

DISPUTE_TABLES = ('negotiations', 'scheduled_bookings', 'trip_bookings')

# name, phone, province, description, is_emergency, sort
HELP_SEED = [
    ('Regina Police Service non-emergency', '306-777-6500', 'SK', None, 0, 20),
    ('Saskatoon Police Service non-emergency', '306-975-8300', 'SK', None, 0, 21),
    ('Saint John Police Force non-emergency', '506-648-3333', 'NB', None, 0, 20),
    ('Fredericton Police Force non-emergency', '506-460-2300', 'NB', None, 0, 21),
    ('Charlottetown Police Services non-emergency', '902-629-4172', 'PE', None, 0, 20),
    ('Royal Newfoundland Constabulary non-emergency', '709-729-8000', 'NL', None, 0, 20),
    ('Whitehorse RCMP non-emergency', '867-667-5555', 'YT', None, 0, 20),
    ('Yellowknife RCMP (24/7 line)', '867-669-1111', 'NT', None, 0, 20),
    ('Iqaluit RCMP non-emergency', '867-979-0123', 'NU', None, 0, 20),
    ('Nunavut RCMP emergency (Iqaluit)', '867-979-1111', 'NU',
     'Nunavut has no 911 service: call your community RCMP detachment at 867-<local prefix>-1111. '
     'Iqaluit: 867-979-1111.', 1, 5),
]


def up(conn):
    create_tables(conn, TABLES)
    for t in DISPUTE_TABLES:
        add_columns(conn, t, ['dispute_resolved_at DATETIME NULL DEFAULT NULL'])
    with conn.cursor() as cur:
        for name, phone, prov, desc, emerg, sort in HELP_SEED:
            cur.execute("SELECT COUNT(*) FROM help_contacts WHERE name=%s AND province=%s", (name, prov))
            if cur.fetchone()[0]:
                continue
            cur.execute(
                "INSERT INTO help_contacts (name, phone, category, province, description,"
                " is_emergency, sort_order, is_active, created_at, updated_at)"
                " VALUES (%s,%s,'police_non_emergency',%s,%s,%s,%s,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                (name, phone, prov, desc, emerg, sort))
    conn.commit()


def down(conn):
    with conn.cursor() as cur:
        for name, _p, prov, *_ in HELP_SEED:
            cur.execute("DELETE FROM help_contacts WHERE name=%s AND province=%s", (name, prov))
    conn.commit()
    for t in DISPUTE_TABLES:
        drop_columns(conn, t, ['dispute_resolved_at'])
    drop_tables(conn, ['ride_pin_failures', 'ride_routes'])
