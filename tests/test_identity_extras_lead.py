"""Profile update conflicts + verification reset (lead)."""
from backend.models import db
from backend.models.user import AdminUser
from tests.conftest import body


def test_profile_update_conflicts_and_unverifies(client, auth, make_user):
    from datetime import datetime
    from tests.identity_utils import rand_phone
    a, b = make_user('customer'), make_user('customer')
    mine = rand_phone()     # verified phones are DB-unique — never a fixed number (parallel test runs)
    a.phone_e164, a.phone_verified_at, a.email_verified_at = mine, datetime.utcnow(), datetime.utcnow()
    db.session.commit()
    r = client.post('/api/profile/update', headers=auth(a), json={'email': b.email})
    assert r.status_code == 409 and body(r)['data']['error_code'] == 'email_in_use'
    # phone changes never go through /api/profile/update (they must be verified) → 400 use_update_phone
    r = client.post('/api/profile/update', headers=auth(a), json={'phone_number': b.phone_number})
    assert r.status_code == 400 and body(r)['data']['error_code'] == 'use_update_phone'
    r = client.post('/api/profile/update', headers=auth(a), json={'phone_number': '+16475550199', 'first_name': 'Zed'})
    assert r.status_code == 400 and body(r)['data']['error_code'] == 'use_update_phone'
    # sending the unchanged number (any formatting) with other fields is fine
    r = client.post('/api/profile/update', headers=auth(a), json={'phone_number': f'({mine[2:5]}) {mine[5:8]}-{mine[8:]}', 'first_name': 'Zed'})
    assert body(r)['code'] == 1, body(r)
    db.session.rollback()
    u = db.session.get(AdminUser, a.id)
    assert u.first_name == 'Zed' and u.phone_verified_at is not None and u.phone_e164 == mine
    assert u.email_verified_at is not None   # email untouched stays verified


def test_carhire_request_requires_verified_phone_when_flag_on(client, auth, make_user):
    from backend.services import settings_service as S
    before = S.get('ff.phone_required_signup')
    try:
        S.set_value('ff.phone_required_signup', True); db.session.commit()
        c = make_user('customer')
        r = client.post('/api/carhire/requests', headers=auth(c, **{'X-App-Version': '4.0.0'}),
                        json={'mode': 'broadcast', 'pickup': {'lat': 43.65, 'lng': -79.38, 'address': 'A'},
                              'dropoff': {'lat': 43.64, 'lng': -79.39, 'address': 'B'}, 'offer_cents': 2000})
        assert r.status_code == 403 and body(r)['data']['error_code'] == 'phone_verification_required'
    finally:
        S.set_value('ff.phone_required_signup', before); db.session.commit()


def test_token_rejection_code_distinguishes_blocked_from_revoked(app, make_user):
    from backend.services import account_service
    from backend.utils.auth import issue_token, token_rejection_code
    u = make_user('customer')
    tok = issue_token(u)
    assert token_rejection_code(tok) is None
    account_service.set_status(u, 'suspended', actor=None, reason_code='other', reason_text='Test suspension',
                               until=__import__('datetime').datetime.utcnow() + __import__('datetime').timedelta(days=1),
                               notify_user=False)
    db.session.rollback()
    assert token_rejection_code(tok) == 'account_blocked'
    assert token_rejection_code('garbage') == 'session_revoked'


def test_admin_legacy_started_moves_arrived_ride_forward(client, auth, make_user):
    from tests.test_carhire_flow import _confirmed_ride, PICKUP
    from backend.models.negotiation import Negotiation
    customer, driver, neg_id, rp = _confirmed_ride(client, auth, make_user)
    client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    client.post(f'/api/rides/carhire/{neg_id}/arrived', headers=auth(driver), json={'lat': PICKUP[0], 'lng': PICKUP[1]})
    a = make_user('admin')
    r = client.post(f'/api/admin/negotiations/{neg_id}/update-status', headers=auth(a),
                    json={'status': 'Started', 'reason': 'Rider confirmed by phone call'})
    assert body(r)['code'] == 1, r.get_json()
    db.session.rollback()
    assert db.session.get(Negotiation, neg_id).trip_stage == 'IN_PROGRESS'
