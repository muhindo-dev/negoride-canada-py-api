"""Account activation / deactivation, automatic rules, appeals, admin roles (spec §15, §7.3, §19)."""
from datetime import datetime, timedelta

from backend.models import db
from backend.models.identity import SupportTicket
from backend.models.money import DriverStrike
from backend.models.notification import Notification
from backend.models.platform import AuditLog
from backend.models.user import AdminUser
from backend.services import account_jobs
from backend.services import account_service as A
from backend.services import realtime
from tests.conftest import body
from tests.identity_utils import setting, v4


def _suspend(client, auth, admin, user, **extra):
    payload = {'action': 'suspend', 'reason_code': 'harassment', 'reason_text': 'Reported by two riders',
               'duration_days': 3}
    payload.update(extra)
    return client.post(f'/api/admin/users/{user.id}/account-status', json=payload, headers=auth(admin))


def test_suspension_revokes_existing_jwt_immediately(client, auth, make_user):
    admin = make_user('admin')
    u = make_user('customer', email_verified_at=datetime.utcnow())
    old = auth(u)
    assert client.get('/api/wallet', headers=old).status_code != 401
    realtime.SENT.clear()
    r = _suspend(client, auth, admin, u)
    assert body(r)['code'] == 1 and body(r)['data']['applied'] is True, body(r)
    # the old token is dead everywhere, even on endpoints suspended users may call
    assert client.get('/api/users/me', headers=old).status_code == 401
    assert client.get('/api/account/status', headers=old).status_code == 401
    assert any(ev == 'account.status_changed' and room == f'user:{u.id}' for ev, _d, room in realtime.SENT)

    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.account_status == 'suspended' and u.status == 0 and u.token_version == 1
    assert u.suspended_until > datetime.utcnow() + timedelta(days=2)
    assert Notification.query.filter_by(user_id=u.id, event_key='account.deactivated').count() == 1
    log = AuditLog.query.filter_by(action='account.status_changed', entity_id=str(u.id)).one()
    assert log.actor_id == admin.id and log.after_json['account_status'] == 'suspended'

    # v3 login keeps the old error; v4 login gets a restricted token
    r = client.post('/api/users/login', json={'email': u.email, 'password': 'Test1234!'})
    assert body(r)['code'] == 0 and body(r)['data']['account_status'] == 'suspended'
    r = client.post('/api/users/login', json={'email': u.email, 'password': 'Test1234!'}, headers=v4())
    tok = {'Authorization': f"Bearer {body(r)['data']['token']}"}
    st = body(client.get('/api/account/status', headers=tok))['data']
    assert st['account_status'] == 'suspended' and st['can_appeal'] is True and st['reason_category'] == 'conduct'
    assert st['suspended_until']
    r = client.get('/api/wallet', headers=tok)
    assert r.status_code == 403 and body(r)['data']['account_status'] == 'suspended'

    # appeal → support ticket
    r = client.post('/api/account/appeal', json={'message': 'This was a misunderstanding.'}, headers=tok)
    assert r.status_code == 201 and body(r)['data']['ticket']['type'] == 'appeal'
    r = client.post('/api/account/appeal', json={'message': 'More details.'}, headers=tok)
    assert r.status_code == 200 and body(r)['data']['created'] is False
    assert SupportTicket.query.filter_by(user_id=u.id, type='appeal').count() == 1

    # reactivate
    r = client.post(f'/api/admin/users/{u.id}/account-status',
                    json={'action': 'reactivate', 'reason_code': 'appeal_granted', 'reason_text': 'Appeal upheld'},
                    headers=auth(admin))
    assert body(r)['data']['account_status'] == 'active'
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.status == 1 and u.suspended_until is None
    assert Notification.query.filter_by(user_id=u.id, event_key='account.reactivated').count() == 1


def test_status_action_validation_and_preview(client, auth, make_user):
    admin = make_user('admin')
    u = make_user('customer')
    r = client.post(f'/api/admin/users/{u.id}/account-status', json={'action': 'ban'}, headers=auth(admin))
    assert body(r)['data']['error_code'] == 'reason_required'
    r = client.post(f'/api/admin/users/{u.id}/account-status', json={'action': 'ban', 'reason_code': 'fraud'},
                    headers=auth(admin))
    assert body(r)['data']['error_code'] == 'reason_text_required'
    r = client.post(f'/api/admin/users/{u.id}/account-status',
                    json={'action': 'suspend', 'reason_code': 'fraud', 'reason_text': 'x'}, headers=auth(admin))
    assert body(r)['data']['error_code'] == 'duration_required'
    r = client.post(f'/api/admin/users/{u.id}/account-status/preview',
                    json={'action': 'suspend', 'reason_code': 'fraud', 'duration_days': 7}, headers=auth(admin))
    p = body(r)['data']
    assert 'suspended' in p['message']['en']['body'] and 'Suspected fraud' in p['message']['en']['body']
    assert 'suspendu' in p['message']['fr']['body'] and p['will_defer'] is False
    reasons = body(client.get('/api/admin/account-status/reasons', headers=auth(admin)))['data']
    assert any(x['code'] == 'low_rating' for x in reasons['reasons'])
    # role enforcement: finance may not change account status
    fin = make_user('customer', admin_roles='finance')
    assert _suspend(client, auth, fin, u).status_code == 403
    assert _suspend(client, auth, make_user('customer'), u).status_code == 403
    sup = make_user('customer', admin_roles='support')
    r = client.post(f'/api/admin/users/{u.id}/account-status',
                    json={'action': 'deactivate', 'reason_code': 'user_request', 'reason_text': 'Asked by phone',
                          'notify_user': False}, headers=auth(sup))
    assert body(r)['code'] == 1
    db.session.rollback()
    assert Notification.query.filter_by(user_id=u.id, event_key='account.deactivated').count() == 0
    prof = body(client.get(f'/api/admin/users/{u.id}/profile', headers=auth(sup)))['data']
    assert prof['account']['account_status'] == 'deactivated'
    assert AuditLog.query.filter_by(action='admin.view_user', actor_id=sup.id, entity_id=str(u.id)).count() == 1
    hist = body(client.get(f'/api/admin/users/{u.id}/history', headers=auth(sup)))['data']['data']
    assert any(h['action'] == 'account.status_changed' for h in hist)


def test_suspension_deferred_during_active_ride(client, auth, make_user):
    from tests.test_carhire_flow import _confirmed_ride
    admin = make_user('admin')
    customer, driver, neg_id, _rp = _confirmed_ride(client, auth, make_user)
    r = client.post(f'/api/rides/carhire/{neg_id}/en-route', headers=auth(driver))
    assert body(r)['code'] == 1
    r = _suspend(client, auth, admin, driver, reason_code='safety_concern')
    d = body(r)['data']
    assert d['deferred'] is True and d['active_ride'] == {'ride_type': 'carhire', 'ride_id': neg_id}
    db.session.rollback()
    drv = db.session.get(AdminUser, driver.id)
    assert drv.account_status in (None, 'active') and drv.pending_account_status == 'suspended'
    # the ride is not cut: the driver can still act on it
    assert client.get(f'/api/rides/carhire/{neg_id}', headers=auth(driver)).status_code == 200
    ok, why = A.can_go_online(drv)
    assert ok is False and 'review' in why

    r = client.post(f'/api/rides/carhire/{neg_id}/cancel', headers=auth(customer), json={'reason_code': 'changed_mind'})
    assert body(r)['code'] == 1, body(r)
    db.session.rollback()
    drv = db.session.get(AdminUser, driver.id)
    assert drv.account_status == 'suspended' and drv.pending_account_status is None and drv.token_version == 1
    assert drv.ready_for_trip == 'No'
    assert client.get('/api/wallet', headers=auth(drv)).status_code == 403


def test_temporary_suspension_auto_ends(client, auth, make_user):
    admin = make_user('admin')
    u = make_user('customer')
    _suspend(client, auth, admin, u)
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    u.suspended_until = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    res = account_jobs.tick()
    assert res['suspensions_ended'] >= 1
    db.session.rollback()
    u = db.session.get(AdminUser, u.id)
    assert u.account_status == 'active' and u.status == 1 and u.status_reason_code == 'suspension_ended'
    assert Notification.query.filter_by(user_id=u.id, event_key='account.reactivated').count() == 1


def test_strikes_warning_then_suspension(make_user):
    d = make_user('driver')
    for i in range(4):
        db.session.add(DriverStrike(driver_id=d.id, reason='driver_cancel', ride_type='carhire', ride_id=900000 + i))
    db.session.commit()
    assert A.evaluate_strikes(d.id) == 'warned'
    assert A.evaluate_strikes(d.id) == 'already_warned'
    assert Notification.query.filter_by(user_id=d.id, event_key='account.warning').count() == 1
    for i in range(2):
        db.session.add(DriverStrike(driver_id=d.id, reason='driver_no_show', ride_type='carhire', ride_id=900010 + i))
    db.session.commit()
    assert A.evaluate_strikes(d.id) == 'suspended'
    db.session.rollback()
    d = db.session.get(AdminUser, d.id)
    assert d.account_status == 'suspended' and d.status_reason_code == 'reliability_strikes'
    assert timedelta(days=2, hours=23) < d.suspended_until - datetime.utcnow() <= timedelta(days=3, seconds=2)
    assert d.ready_for_trip == 'No'


def test_rating_rules(make_user, monkeypatch):
    from backend.models.experience import RideRating
    setting(monkeypatch, 'rating.min_rides_for_rules', 3)
    d = make_user('driver')
    raters = [make_user('customer') for _ in range(3)]

    def rate(stars):
        RideRating.query.filter_by(ratee_id=d.id).delete()
        for i, r in enumerate(raters):
            db.session.add(RideRating(ride_type='carhire', ride_id=990000 + d.id * 10 + i, rater_id=r.id, ratee_id=d.id,
                                      role='customer', stars=stars[i]))
        db.session.commit()

    rate([5, 5, 5])
    assert A.evaluate_rating_rules(d.id) is None
    rate([5, 4, 4])            # 4.33 → fine
    assert A.evaluate_rating_rules(d.id) is None
    rate([4, 4, 4])            # 4.0 < 4.3 → warning
    assert A.evaluate_rating_rules(d.id) == 'warned'
    rate([4, 4, 3])            # 3.67 < 4.0 → pending review
    assert A.evaluate_rating_rules(d.id) == 'pending_review'
    db.session.rollback()
    assert db.session.get(AdminUser, d.id).effective_account_status() == 'pending_review'


def test_support_tickets_sla_and_admin_reply(client, auth, make_user):
    u = make_user('customer')
    sup = make_user('customer', admin_roles='support')
    r = client.post('/api/support/tickets', json={'type': 'safety', 'body': 'Driver was speeding.'}, headers=auth(u))
    t = body(r)['data']
    assert r.status_code == 201 and t['priority'] == 'high' and t['sla']['remaining_s'] > 3 * 3600
    assert client.post('/api/support/tickets', json={'type': 'nope', 'body': 'x'}, headers=auth(u)).status_code == 400
    q = body(client.get('/api/admin/support/tickets?type=safety', headers=auth(sup)))['data']
    assert any(i['id'] == t['id'] for i in q['data']) and 'counts' in q
    r = client.post(f"/api/admin/support/tickets/{t['id']}/reply", json={'body': 'We are looking into it.'}, headers=auth(sup))
    d = body(r)['data']
    assert d['status'] == 'pending' and d['sla']['first_response_at'] and d['assigned_to'] == sup.id
    client.post(f"/api/admin/support/tickets/{t['id']}/reply", json={'body': 'internal note', 'internal': True},
                headers=auth(sup))
    mine = body(client.get(f"/api/support/tickets/{t['id']}", headers=auth(u)))['data']
    assert [m['author_type'] for m in mine['messages']] == ['user', 'admin']
    assert Notification.query.filter_by(user_id=u.id, event_key='support.reply').count() == 1
    r = client.post(f"/api/admin/support/tickets/{t['id']}/status", json={'status': 'resolved', 'resolution': 'Driver coached.'},
                    headers=auth(sup))
    assert body(r)['data']['status'] == 'resolved'
    assert AuditLog.query.filter_by(action='support.status', entity_id=str(t['id'])).count() == 1
    other = make_user('customer')
    assert client.get(f"/api/support/tickets/{t['id']}", headers=auth(other)).status_code == 404


def test_admin_roles_management_super_admin_only(client, auth, make_user):
    sup = make_user('customer', admin_roles='support')
    target = make_user('customer')
    r = client.put(f'/api/admin/admin-users/{target.id}/roles', json={'roles': ['ops']}, headers=auth(sup))
    assert r.status_code == 403
    root = make_user('admin')
    r = client.put(f'/api/admin/admin-users/{target.id}/roles', json={'roles': ['ops', 'bogus']}, headers=auth(root))
    assert body(r)['data']['error_code'] == 'invalid_role'
    r = client.put(f'/api/admin/admin-users/{target.id}/roles', json={'roles': ['ops', 'finance']}, headers=auth(root))
    assert body(r)['data']['roles'] == ['ops', 'finance']
    assert AuditLog.query.filter_by(action='admin.roles_changed', entity_id=str(target.id)).count() == 1
    db.session.rollback()
    target = db.session.get(AdminUser, target.id)
    assert client.get('/api/admin/onboarding/funnel', headers=auth(target)).status_code == 200
    lst = body(client.get('/api/admin/admin-users', headers=auth(root)))['data']['items']
    assert any(i['id'] == target.id for i in lst)
