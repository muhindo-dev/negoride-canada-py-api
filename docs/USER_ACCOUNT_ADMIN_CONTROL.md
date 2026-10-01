# User account administration plan

## Goal

Give authorized operations admins a complete, understandable control surface for customer and driver accounts,
with each change validated server-side and recorded in the audit history.

## Existing gaps

- The Users profile is primarily read-only; common contact and profile fields have no editor.
- Legacy account update and password-reset endpoints use broad admin access and do not consistently audit changes.
- Manual verification, session revocation, and a safe force-offline action are not available from the V4 profile.
- Driver onboarding decisions, account status, admin roles, wallet controls, and legal acceptance history already
  have separate workflows and must continue to use their own guarded APIs.

## Tasks

- [x] Add a strict role-gated, allowlisted profile update API with validation, verification invalidation when
      contact details change, and before/after audit metadata.
- [x] Add audited actions to revoke sessions, force a driver offline, send a password reset link, and correct
      email/phone verification only with a reason and explicit confirmation.
- [x] Tighten legacy update/reset endpoints so they cannot bypass the V4 permission, reason, and audit rules.
- [x] Add an account editor and action panel to the V4 user profile, gated by matching role permissions.
- [x] Show edit/action outcomes and refresh all affected profile/list/history queries.
- [ ] Backend regression tests were added. Python syntax checks and the frontend production build pass; executing
      backend tests is pending a Python environment with Flask-CORS and pytest plus an isolated test database.

## Safety boundaries

- Admin roles remain super-admin-only and use the existing role editor.
- Driver approval and identity document review continue through onboarding decisions.
- Wallet changes remain finance actions with their own ledger, reason, and permission rules.
- Admins cannot view or set passwords. “Reset password” sends the account holder a one-hour reset link and
  revokes existing sessions.
- No action silently verifies a newly changed email address or phone number.
