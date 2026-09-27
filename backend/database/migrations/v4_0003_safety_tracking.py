"""
v4 · P3 Safety (spec §8, §9, §10)

Tables: safety_incidents, safety_incident_locations, trusted_contacts,
safety_reports, safety_settings, safety_checks, help_contacts, ride_locations,
ride_share_links, recordings, recording_chunks.
"""
from backend.database.schema_helpers import create_tables, drop_tables, TABLE_OPTS

TABLES = [
    f"""CREATE TABLE safety_incidents (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'customer',
        ride_type VARCHAR(30) NULL,
        ride_id BIGINT NULL,
        kind VARCHAR(30) NOT NULL DEFAULT 'sos',
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        severity VARCHAR(20) NOT NULL DEFAULT 'critical',
        silent TINYINT(1) NOT NULL DEFAULT 0,
        lat DECIMAL(10,7) NULL,
        lng DECIMAL(10,7) NULL,
        accuracy_m INT NULL,
        battery_pct INT NULL,
        last_lat DECIMAL(10,7) NULL,
        last_lng DECIMAL(10,7) NULL,
        last_location_at DATETIME NULL,
        idempotency_key VARCHAR(120) NULL,
        acknowledged_by INT NULL,
        acknowledged_at DATETIME NULL,
        escalated_at DATETIME NULL,
        resolved_by INT NULL,
        resolved_at DATETIME NULL,
        notes TEXT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NULL,
        UNIQUE KEY uq_incident_idem (user_id, idempotency_key),
        KEY ix_incident_status (status, created_at),
        KEY ix_incident_ride (ride_type, ride_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE safety_incident_locations (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        incident_id BIGINT NOT NULL,
        lat DECIMAL(10,7) NOT NULL,
        lng DECIMAL(10,7) NOT NULL,
        accuracy_m INT NULL,
        speed_mps DECIMAL(6,2) NULL,
        heading SMALLINT NULL,
        battery_pct INT NULL,
        recorded_at DATETIME NOT NULL,
        KEY ix_sil_incident (incident_id, recorded_at)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE trusted_contacts (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        name VARCHAR(120) NOT NULL,
        phone_e164 VARCHAR(20) NOT NULL,
        relationship VARCHAR(40) NULL,
        auto_share TINYINT(1) NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL,
        UNIQUE KEY uq_trusted (user_id, phone_e164)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE safety_reports (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        reporter_id INT NOT NULL,
        reported_user_id INT NULL,
        ride_type VARCHAR(30) NULL,
        ride_id BIGINT NULL,
        category VARCHAR(40) NOT NULL,
        description TEXT NULL,
        attachments JSON NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        reviewed_by INT NULL,
        reviewed_at DATETIME NULL,
        resolution TEXT NULL,
        created_at DATETIME NOT NULL,
        KEY ix_reports_status (status, created_at)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE safety_settings (
        user_id INT PRIMARY KEY,
        record_audio VARCHAR(10) NOT NULL DEFAULT 'off',
        auto_record_on_sos TINYINT(1) NOT NULL DEFAULT 0,
        auto_share_night TINYINT(1) NOT NULL DEFAULT 0,
        auto_share_all TINYINT(1) NOT NULL DEFAULT 0,
        night_start CHAR(5) NOT NULL DEFAULT '21:00',
        night_end CHAR(5) NOT NULL DEFAULT '05:00',
        updated_at DATETIME NULL
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE safety_checks (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        user_id INT NOT NULL,
        kind VARCHAR(30) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        lat DECIMAL(10,7) NULL,
        lng DECIMAL(10,7) NULL,
        meta JSON NULL,
        incident_id BIGINT NULL,
        created_at DATETIME NOT NULL,
        responded_at DATETIME NULL,
        KEY ix_checks_ride (ride_type, ride_id),
        KEY ix_checks_status (status, created_at)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE help_contacts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(160) NOT NULL,
        phone VARCHAR(40) NULL,
        email VARCHAR(160) NULL,
        url VARCHAR(255) NULL,
        category VARCHAR(40) NOT NULL,
        province CHAR(2) NULL,
        description VARCHAR(500) NULL,
        is_emergency TINYINT(1) NOT NULL DEFAULT 0,
        sort_order INT NOT NULL DEFAULT 100,
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        created_at DATETIME NULL,
        updated_at DATETIME NULL,
        KEY ix_help_cat (category, province)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE ride_locations (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ride_type VARCHAR(30) NULL,
        ride_id BIGINT NULL,
        user_id INT NOT NULL,
        lat DECIMAL(10,7) NOT NULL,
        lng DECIMAL(10,7) NOT NULL,
        speed_mps DECIMAL(6,2) NULL,
        heading SMALLINT NULL,
        accuracy_m INT NULL,
        recorded_at DATETIME NOT NULL,
        KEY ix_rl_ride (ride_type, ride_id, recorded_at),
        KEY ix_rl_user (user_id, recorded_at)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE ride_share_links (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        token VARCHAR(64) NOT NULL,
        ride_type VARCHAR(30) NOT NULL,
        ride_id BIGINT NOT NULL,
        user_id INT NOT NULL,
        shared_with JSON NULL,
        created_at DATETIME NOT NULL,
        expires_at DATETIME NULL,
        revoked_at DATETIME NULL,
        view_count INT NOT NULL DEFAULT 0,
        last_viewed_at DATETIME NULL,
        UNIQUE KEY uq_share_token (token),
        KEY ix_share_ride (ride_type, ride_id)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE recordings (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        role VARCHAR(20) NOT NULL,
        ride_type VARCHAR(30) NULL,
        ride_id BIGINT NULL,
        incident_id BIGINT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'recording',
        trigger_source VARCHAR(20) NOT NULL DEFAULT 'manual',
        started_at DATETIME NOT NULL,
        stopped_at DATETIME NULL,
        chunk_count INT NOT NULL DEFAULT 0,
        total_bytes BIGINT NOT NULL DEFAULT 0,
        retain_until DATETIME NULL,
        legal_hold TINYINT(1) NOT NULL DEFAULT 0,
        deleted_at DATETIME NULL,
        created_at DATETIME NOT NULL,
        KEY ix_rec_ride (ride_type, ride_id),
        KEY ix_rec_retention (retain_until, legal_hold)
    ) {TABLE_OPTS}""",
    f"""CREATE TABLE recording_chunks (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        recording_id BIGINT NOT NULL,
        seq INT NOT NULL,
        storage_key VARCHAR(500) NOT NULL,
        bytes BIGINT NOT NULL DEFAULT 0,
        sha256 CHAR(64) NULL,
        duration_ms INT NULL,
        started_at DATETIME NULL,
        uploaded_at DATETIME NOT NULL,
        UNIQUE KEY uq_chunk (recording_id, seq)
    ) {TABLE_OPTS}""",
]

HELP_SEED = [
    # name, phone, category, province, description, is_emergency, sort
    ('Emergency services (Police · Fire · Ambulance)', '911', 'emergency', None,
     'Life-threatening emergencies anywhere in Canada.', 1, 1),
    ('Talk Suicide Canada / 9-8-8', '988', 'crisis', None,
     'Suicide crisis helpline — call or text 988, 24/7.', 1, 2),
    ('Kids Help Phone', '1-800-668-6868', 'crisis', None,
     'Support for young people, 24/7. Text CONNECT to 686868.', 0, 3),
    ('NegoRide Safety & Support', '', 'support', None,
     'In-app chat and support line — set phone/email in admin settings.', 0, 4),
    ('Toronto Police non-emergency', '416-808-2222', 'police_non_emergency', 'ON', None, 0, 20),
    ('Ontario Provincial Police non-emergency', '1-888-310-1122', 'police_non_emergency', 'ON', None, 0, 21),
    ('Vancouver Police non-emergency', '604-717-3321', 'police_non_emergency', 'BC', None, 0, 20),
    ('Calgary Police non-emergency', '403-266-1234', 'police_non_emergency', 'AB', None, 0, 20),
    ('Edmonton Police non-emergency', '780-423-4567', 'police_non_emergency', 'AB', None, 0, 21),
    ('Montréal SPVM (info)', '514-280-2222', 'police_non_emergency', 'QC', None, 0, 20),
    ('Ottawa Police non-emergency', '613-236-1222', 'police_non_emergency', 'ON', None, 0, 22),
    ('Winnipeg Police non-emergency', '204-986-6222', 'police_non_emergency', 'MB', None, 0, 20),
    ('Halifax Regional Police non-emergency', '902-490-5020', 'police_non_emergency', 'NS', None, 0, 20),
    ('CAA Roadside Assistance', '1-800-222-4357', 'roadside', None,
     'Roadside assistance (members).', 0, 40),
]


def up(conn):
    create_tables(conn, TABLES)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM help_contacts")
        if cur.fetchone()[0] == 0:
            for name, phone, cat, prov, desc, emerg, sort in HELP_SEED:
                cur.execute(
                    "INSERT INTO help_contacts (name, phone, category, province, description,"
                    " is_emergency, sort_order, is_active, created_at, updated_at)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                    (name, phone, cat, prov, desc, emerg, sort))
    conn.commit()


def down(conn):
    drop_tables(conn, ['recording_chunks', 'recordings', 'ride_share_links', 'ride_locations',
                       'help_contacts', 'safety_checks', 'safety_settings', 'safety_reports',
                       'trusted_contacts', 'safety_incident_locations', 'safety_incidents'])
