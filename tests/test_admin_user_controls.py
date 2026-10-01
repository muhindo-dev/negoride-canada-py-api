from datetime import datetime

from backend.models import db
from backend.models.platform import AuditLog
from backend.models.user import AdminUser
from tests.conftest import body


def test_ops_can_edit_profile_and_contact_changes_revoke_and_unverify(client, auth, make_user):
    admin = make_user('admin', admin_roles='ops')
    target = make_user('customer', email_verified_at=datetime.utcnow(), phone_verified_at=datetime.utcnow())
    old_version = target.token_version
    r = client.put(f'/api/admin/users/{target.id}/profile', headers=auth(admin), json={
        'changes': {'name': 'Corrected Name', 'email': 'corrected@example.test'},
        'reason_text': 'Corrected at the user request',
    })
    assert body(r)['code'] == 1, r.get_json()
    db.session.refresh(target)
    assert target.name == 'Corrected Name'
    assert target.email == 'corrected@example.test'
    assert target.email_verified_at is None
    assert target.phone_verified_at is not None
    assert target.token_version == old_version + 1
    assert AuditLog.query.filter_by(action='admin.user_profile_update', entity_id=str(target.id)).count() == 1


def test_profile_editor_rejects_privilege_and_password_fields(client, auth, make_user):
    admin = make_user('admin', admin_roles='ops')
    target = make_user('customer')
    r = client.put(f'/api/admin/users/{target.id}/profile', headers=auth(admin), json={
        'changes': {'user_type': 'Admin'}, 'reason_text': 'Attempted escalation',
    })
    assert r.status_code == 400 and body(r)['data']['error_code'] == 'field_not_editable'
    r = client.put(f'/api/admin/users/{target.id}/profile', headers=auth(admin), json={
        'changes': {'password': 'NeverAcceptThis'}, 'reason_text': 'Attempted password change',
    })
    assert r.status_code == 400


def test_support_role_cannot_edit_profile_but_can_view_it(client, auth, make_user):
    admin = make_user('admin', admin_roles='support')
    target = make_user('customer')
    r = client.put(f'/api/admin/users/{target.id}/profile', headers=auth(admin), json={
        'changes': {'name': 'Not allowed'}, 'reason_text': 'Support should not edit',
    })
    assert r.status_code == 403
    assert body(client.get(f'/api/admin/users/{target.id}/profile', headers=auth(admin)))['code'] == 1


def test_session_revoke_and_force_offline_are_audited(client, auth, make_user):
    admin = make_user('admin', admin_roles='ops')
    driver = make_user('driver', ready_for_trip='Yes')
    version = driver.token_version
    r = client.post(f'/api/admin/users/{driver.id}/sessions/revoke', headers=auth(admin), json={'reason_text': 'Security response'})
    assert body(r)['code'] == 1
    db.session.refresh(driver)
    assert driver.token_version == version + 1
    r = client.post(f'/api/admin/users/{driver.id}/force-offline', headers=auth(admin), json={'reason_text': 'Safety concern'})
    assert body(r)['code'] == 1
    db.session.refresh(driver)
    assert driver.ready_for_trip == 'No'
    assert AuditLog.query.filter_by(action='admin.user_sessions_revoked', entity_id=str(driver.id)).count() == 1
    assert AuditLog.query.filter_by(action='admin.driver_forced_offline', entity_id=str(driver.id)).count() == 1
