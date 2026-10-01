"""Ghost-trip prevention: /api/negotiations-verify tells the app which cached
negotiations really exist, and every "not found" carries a machine-readable
error_code so the app can purge the ghost immediately."""
from tests.conftest import body
from tests.test_carhire_flow import create_negotiation


def test_verify_classifies_active_ended_and_gone(client, auth, make_user, app):
    from backend.models import db
    from backend.models.negotiation import Negotiation
    customer, driver, stranger = make_user('customer'), make_user('driver'), make_user('customer')
    open_id = create_negotiation(client, auth, customer, driver)
    ended_id = create_negotiation(client, auth, customer, driver)
    neg = db.session.get(Negotiation, ended_id)
    neg.status, neg.is_active = 'Completed', 'No'
    db.session.commit()

    r = client.post('/api/negotiations-verify', headers=auth(customer),
                    json={'ids': [open_id, ended_id, 999999999]})
    d = body(r)['data']
    assert r.status_code == 200
    assert d['results'][str(open_id)]['state'] == 'active'
    assert d['results'][str(ended_id)] == {'state': 'ended', 'status': 'Completed'}
    assert d['results']['999999999'] == {'state': 'gone'}
    assert open_id in d['active_ids'] and ended_id not in d['active_ids']
    assert d['gone_ids'] == [999999999]

    # Someone else's ride is "gone" for this caller — never leak its existence.
    r = client.post('/api/negotiations-verify', headers=auth(stranger), json={'ids': f'{open_id}'})
    assert body(r)['data']['results'][str(open_id)] == {'state': 'gone'}


def test_not_found_carries_error_code(client, auth, make_user):
    customer = make_user('customer')
    for path in ('/api/negotiations-complete', '/api/negotiation-updates', '/api/negotiations-cancel'):
        r = client.post(path, headers=auth(customer), json={'negotiation_id': 999999999})
        assert r.status_code == 404, path
        assert body(r)['data']['error_code'] == 'negotiation_not_found', path


def test_verify_requires_auth(client):
    assert client.post('/api/negotiations-verify', json={'ids': [1]}).status_code == 401


def test_new_ride_never_inherits_history_of_a_reused_id(client, auth, make_user):
    """MySQL 5.7 can re-issue a deleted ride's id: the new ride must start clean."""
    from sqlalchemy import text
    from backend.models import db
    from backend.models.platform import TripEvent
    customer, driver = make_user('customer'), make_user('driver')
    next_id = db.session.execute(text(
        "SELECT AUTO_INCREMENT FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = 'negotiations'")).scalar()
    db.session.add(TripEvent(ride_type='carhire', ride_id=next_id, from_stage='IN_PROGRESS',
                             to_stage='COMPLETED', actor_type='system'))
    db.session.commit()
    neg_id = create_negotiation(client, auth, customer, driver)
    db.session.rollback()
    assert neg_id == next_id          # the id really was the one with stale history
    stages = [e.to_stage for e in TripEvent.query.filter_by(ride_type='carhire', ride_id=neg_id)]
    assert stages == ['REQUESTED']
    TripEvent.query.filter_by(ride_type='carhire', ride_id=next_id).filter(
        TripEvent.to_stage == 'COMPLETED').delete()
    db.session.commit()
