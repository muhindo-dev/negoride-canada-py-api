"""Notification engine (spec §5) + Socket.IO /rt authentication (spec §5.2)."""
from datetime import datetime, timedelta

from backend import jobs
from backend.app import socketio
from backend.models import db
from backend.models.notification import Notification, NotificationDelivery, NotificationPreference
from backend.services.notify import dispatcher, channels
from backend.utils.auth import issue_token
from tests.conftest import body


def _send(event, uid, ctx=None):
    ids = dispatcher.notify_now(event, [uid], ctx or {})
    db.session.rollback()
    return db.session.get(Notification, ids[0]) if ids else None


def test_every_notification_lands_in_inbox_with_deliveries(app, make_user):
    u = make_user('customer')
    n = _send('ride.driver_en_route', u.id, {'driver_first': 'Amara', 'eta_min': 7, 'vehicle': 'Grey Toyota Corolla ABC 123',
                                             'ride_type': 'carhire', 'ride_id': 5})
    assert n.title == 'Amara is on the way'
    assert '7 min' in n.body and 'ABC 123' in n.body
    assert n.deep_link == 'negoride://ride/carhire/5'
    chans = {d.channel: d.status for d in NotificationDelivery.query.filter_by(notification_id=n.id)}
    assert chans['inbox'] == 'delivered' and chans['socket'] == 'delivered'
    # push dry-run: OneSignal payload targets the external id with the right channel
    p = channels.PUSH_LOG[-1]
    assert p['include_aliases'] == {'external_id': [str(u.id)]} and p['target_channel'] == 'push'
    assert p['data']['notification_id'] == n.id and p['data']['route'] == 'ride'


def test_french_copy(app, make_user):
    u = make_user('customer', preferred_language='fr')
    n = _send('ride.driver_arrived', u.id, {'pin': '4821'})
    assert n.title == 'Votre chauffeur est arrivé' and 'NIP : 4821' in n.body


def test_mutable_group_can_be_muted_but_safety_cannot(app, make_user, client, auth):
    u = make_user('customer')
    r = client.put('/api/notification-preferences', headers=auth(u),
                   json={'groups': {'ratings': {'push': False, 'sms': False, 'email': False}}})
    assert body(r)['code'] == 1
    n = _send('rating.reminder', u.id, {'other_first': 'Sam'})
    assert {d.channel for d in NotificationDelivery.query.filter_by(notification_id=n.id)} == {'inbox'}
    # mandatory groups ignore preferences (and are shown locked)
    groups = {g['group']: g for g in body(client.get('/api/notification-preferences', headers=auth(u)))['data']['groups']}
    assert groups['safety']['mandatory'] and groups['ratings']['push'] is False
    n2 = _send('ride.cancelled', u.id, {'cancelled_by': 'driver'})
    assert 'push' in {d.channel for d in NotificationDelivery.query.filter_by(notification_id=n2.id)}


def test_quiet_hours_skip_push_for_non_critical(app, make_user):
    u = make_user('customer')
    now = datetime.utcnow()
    db.session.add(NotificationPreference(user_id=u.id, event_group='ratings',
                                          quiet_start=(now - timedelta(hours=1)).strftime('%H:%M'),
                                          quiet_end=(now + timedelta(hours=1)).strftime('%H:%M')))
    db.session.commit()
    n = _send('rating.reminder', u.id, {'other_first': 'Sam'})
    assert 'push' not in {d.channel for d in NotificationDelivery.query.filter_by(notification_id=n.id)}


def test_critical_push_escalates_to_sms_if_unopened(app, make_user):
    u = make_user('customer')
    jobs.DEFERRED.clear()
    n = _send('ride.driver_arrived', u.id, {'pin': '1111'})
    assert any(p.endswith('escalate_if_unopened') for _, p, _, _ in jobs.DEFERRED)
    jobs.run_deferred(max_delay=60)
    db.session.rollback()
    sms = NotificationDelivery.query.filter_by(notification_id=n.id, channel='sms').first()
    assert sms is not None   # Twilio not configured in tests → recorded as failed(not configured), but attempted
    assert sms.status == 'failed' and 'not configured' in (sms.error or '')


def test_opened_notification_is_not_escalated(app, make_user, client, auth):
    u = make_user('customer')
    jobs.DEFERRED.clear()
    n = _send('ride.driver_arrived', u.id, {'pin': '2222'})
    r = client.post(f'/api/notifications/{n.id}/opened', headers=auth(u))
    assert body(r)['code'] == 1
    jobs.run_deferred(max_delay=60)
    db.session.rollback()
    assert NotificationDelivery.query.filter_by(notification_id=n.id, channel='sms').count() == 0
    assert NotificationDelivery.query.filter_by(notification_id=n.id, channel='push').first().status == 'opened'


def test_retry_with_backoff(app, make_user, monkeypatch):
    u = make_user('customer')
    calls = {'n': 0}

    def flaky(n, user, spec):
        calls['n'] += 1
        raise RuntimeError('provider timeout')
    monkeypatch.setattr(channels, 'push_onesignal', flaky)
    n = _send('ride.driver_en_route', u.id, {})
    d = NotificationDelivery.query.filter_by(notification_id=n.id, channel='push').first()
    assert d.status == 'retrying' and d.attempts == 1 and d.next_attempt_at
    for _ in range(2):
        d.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        dispatcher.retry_due()
        db.session.rollback()
        d = db.session.get(NotificationDelivery, d.id)
    assert d.status == 'failed' and d.attempts == 3 and calls['n'] == 3


def test_inbox_endpoints(app, make_user, client, auth):
    u = make_user('customer')
    for _ in range(3):
        _send('rating.reminder', u.id, {'other_first': 'Sam'})
    h = auth(u)
    assert body(client.get('/api/notifications/unread-count', headers=h))['data']['unread'] == 3
    page = body(client.get('/api/notifications?per_page=2', headers=h))['data']
    assert page['total'] == 3 and len(page['data']) == 2 and page['last_page'] == 2
    client.post(f"/api/notifications/{page['data'][0]['id']}/read", headers=h)
    assert body(client.get('/api/notifications/unread-count', headers=h))['data']['unread'] == 2
    client.post('/api/notifications/read-all', headers=h)
    assert body(client.get('/api/notifications/unread-count', headers=h))['data']['unread'] == 0
    other = make_user('customer')
    assert client.post(f"/api/notifications/{page['data'][0]['id']}/read", headers=auth(other)).status_code == 404


def test_app_config_is_public(client):
    d = body(client.get('/api/app/config'))['data']
    assert d['flags']['pay_before_trip'] is True and 'ride.wait_window_s' in d['settings']
    assert 'company.gst_number' not in d['settings']      # private settings never leak


# ── Socket.IO /rt ────────────────────────────────────────────────────────────

def test_socket_rejects_unauthenticated(app):
    c = socketio.test_client(app, namespace='/rt', auth={'token': 'garbage'})
    assert not c.is_connected(namespace='/rt')


def test_socket_rejects_revoked_token(app, make_user):
    u = make_user('customer')
    token = issue_token(u)
    u.token_version = (u.token_version or 0) + 1
    db.session.commit()
    c = socketio.test_client(app, namespace='/rt', auth={'token': token})
    assert not c.is_connected(namespace='/rt')


def test_socket_connects_joins_user_room_and_receives_notifications(app, make_user):
    u = make_user('customer')
    c = socketio.test_client(app, namespace='/rt', auth={'token': issue_token(u)})
    assert c.is_connected(namespace='/rt')
    got = c.get_received('/rt')
    assert any(m['name'] == 'connected' and f'user:{u.id}' in m['args'][0]['rooms'] for m in got)
    _send('ride.driver_en_route', u.id, {'driver_first': 'Amara'})
    got = c.get_received('/rt')
    notes = [m for m in got if m['name'] == 'notification']
    assert notes and notes[0]['args'][0]['title'] == 'Amara is on the way'
    # ack marks it opened
    c.emit('notification:ack', {'id': notes[0]['args'][0]['id']}, namespace='/rt')
    db.session.rollback()
    assert db.session.get(Notification, notes[0]['args'][0]['id']).opened_at is not None
    c.disconnect(namespace='/rt')


def test_admin_socket_joins_ops_and_sos(app, make_user):
    a = make_user('admin')
    c = socketio.test_client(app, namespace='/rt', auth={'token': issue_token(a)})
    rooms = [m for m in c.get_received('/rt') if m['name'] == 'connected'][0]['args'][0]['rooms']
    assert 'admin:ops' in rooms and 'admin:sos' in rooms
    c.disconnect(namespace='/rt')


def test_ride_subscribe_is_party_only(app, make_user, client, auth):
    from tests.test_carhire_flow import create_negotiation
    customer, driver, stranger = make_user('customer'), make_user('driver'), make_user('customer')
    neg_id = create_negotiation(client, auth, customer, driver)
    ok = socketio.test_client(app, namespace='/rt', auth={'token': issue_token(customer)})
    ok.emit('ride:subscribe', {'ride_type': 'carhire', 'ride_id': neg_id}, namespace='/rt')
    assert any(m['name'] == 'ride:subscribed' for m in ok.get_received('/rt'))
    bad = socketio.test_client(app, namespace='/rt', auth={'token': issue_token(stranger)})
    bad.emit('ride:subscribe', {'ride_type': 'carhire', 'ride_id': neg_id}, namespace='/rt')
    assert not any(m['name'] == 'ride:subscribed' for m in bad.get_received('/rt'))
    ok.disconnect(namespace='/rt')
    bad.disconnect(namespace='/rt')


def test_suspended_token_is_revoked_for_http(app, make_user, client, auth):
    u = make_user('customer')
    h = auth(u)
    assert client.get('/api/users/me', headers=h).status_code == 200
    u.token_version += 1
    db.session.commit()
    assert client.get('/api/users/me', headers=h).status_code == 401


def test_postmark_webhook_tracks_opens_and_bounces(app, make_user, client, monkeypatch):
    import base64
    monkeypatch.setenv('POSTMARK_WEBHOOK_USER', 'pm')
    monkeypatch.setenv('POSTMARK_WEBHOOK_PASSWORD', 'secret')
    u = make_user('customer')
    n = _send('refund.issued', u.id, {'amount': '$5.00'})
    d = NotificationDelivery.query.filter_by(notification_id=n.id, channel='email').first()
    assert d and d.provider_message_id
    h = {'Authorization': 'Basic ' + base64.b64encode(b'pm:secret').decode()}
    assert client.post('/api/webhooks/postmark', json={'RecordType': 'Open', 'MessageID': d.provider_message_id},
                       headers={'Authorization': 'Basic ' + base64.b64encode(b'pm:bad').decode()}).status_code == 401
    assert client.post('/api/webhooks/postmark', json={'RecordType': 'Open', 'MessageID': d.provider_message_id,
                                                       'ReceivedAt': '2026-09-27T10:00:00Z'}, headers=h).status_code == 204
    db.session.rollback()
    assert db.session.get(NotificationDelivery, d.id).status == 'opened'
    client.post('/api/webhooks/postmark', json={'RecordType': 'Bounce', 'MessageID': d.provider_message_id,
                                                'ID': 1, 'Type': 'HardBounce'}, headers=h)
    db.session.rollback()
    assert db.session.get(NotificationDelivery, d.id).status == 'failed'
