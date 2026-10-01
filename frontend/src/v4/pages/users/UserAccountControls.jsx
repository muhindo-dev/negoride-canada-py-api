import React, { useEffect, useState } from 'react';
import {
  Alert, Badge, Button, Card, Divider, Group, Modal, SimpleGrid, Stack, Switch, Tabs, Text, TextInput, Textarea,
} from '@mantine/core';
import { FiCheckCircle, FiMail, FiPhone, FiShield } from 'react-icons/fi';
import { http } from '../../lib/api';

const EDITABLE = ['name', 'first_name', 'last_name', 'email', 'phone_number', 'date_of_birth', 'sex', 'legal_name', 'country_name', 'country_code', 'country_short_name', 'province', 'current_address', 'preferred_language', 'timezone', 'automobile', 'driving_license_number', 'nin', 'driving_license_issue_date', 'driving_license_validity', 'driving_license_issue_authority', 'max_passengers'];
const PROFILE_GROUPS = [
  { title: 'Personal details', fields: ['name', 'first_name', 'last_name', 'legal_name', 'date_of_birth', 'sex'] },
  { title: 'Contact details', fields: ['email', 'phone_number'] },
  { title: 'Location and preferences', fields: ['country_name', 'country_code', 'country_short_name', 'province', 'current_address', 'preferred_language', 'timezone'] },
  { title: 'Driver details', fields: ['automobile', 'driving_license_number', 'nin', 'driving_license_issue_date', 'driving_license_validity', 'driving_license_issue_authority', 'max_passengers'] },
];

const labelFor = (key) => key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

function ContactVerificationCard({ kind, value, verified, busy, disabled, onChange }) {
  const isEmail = kind === 'email';
  const Icon = isEmail ? FiMail : FiPhone;
  return (
    <Card withBorder radius="md" padding="lg" h="100%">
      <Stack gap="sm" h="100%">
        <Group justify="space-between" align="flex-start">
          <Group gap="sm">
            <Icon size={20} aria-hidden="true" />
            <Text fw={600}>{isEmail ? 'Email address' : 'Phone number'}</Text>
          </Group>
          <Badge color={verified ? 'green' : 'orange'} variant="light" leftSection={verified ? <FiCheckCircle size={11} /> : undefined}>
            {verified ? 'Verified' : 'Unverified'}
          </Badge>
        </Group>
        <Text size="sm" c={value ? undefined : 'dimmed'} mih={22} style={{ overflowWrap: 'anywhere' }}>
          {value || `No ${isEmail ? 'email address' : 'phone number'} on this account`}
        </Text>
        <Text size="xs" c="dimmed" mt="auto">
          {verified ? 'Remove the verified status if the contact can no longer be trusted.' : 'Use only after confirming this contact through an approved support process.'}
        </Text>
        <Button
          fullWidth
          variant={verified ? 'light' : 'filled'}
          color={verified ? 'gray' : 'orange'}
          loading={busy}
          disabled={disabled || !value}
          onClick={() => onChange(kind, verified ? 'unverify' : 'verify')}
        >
          {verified ? 'Remove verified status' : `Mark ${isEmail ? 'email' : 'phone'} as verified`}
        </Button>
      </Stack>
    </Card>
  );
}

export default function UserAccountControls({ user, verification, opened, onClose, onDone, canEdit, canVerify }) {
  const [form, setForm] = useState({});
  const [profileReason, setProfileReason] = useState('');
  const [actionReason, setActionReason] = useState('');
  const [verificationReason, setVerificationReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (opened && user) {
      const values = {};
      EDITABLE.forEach((key) => { values[key] = user[key] || ''; });
      values.marketing_opt_in = !!user.marketing_opt_in;
      setForm(values);
      setProfileReason('');
      setActionReason('');
      setVerificationReason('');
      setError('');
    }
  }, [opened, user]);

  const update = (key, value) => setForm((old) => ({ ...old, [key]: value }));

  async function run(path, body, message) {
    setBusy(true);
    setError('');
    try {
      const result = await http.postFull(`/admin/users/${user.id}/${path}`, body);
      onDone(result.message || message);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile() {
    setBusy(true);
    setError('');
    try {
      const changes = {};
      EDITABLE.forEach((key) => { if ((form[key] || '') !== (user[key] || '')) changes[key] = form[key]; });
      if (!!form.marketing_opt_in !== !!user.marketing_opt_in) changes.marketing_opt_in = !!form.marketing_opt_in;
      const result = await http.put(`/admin/users/${user.id}/profile`, { changes, reason_text: profileReason });
      onDone(result.message || 'Profile saved.');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function changeVerification(field, action) {
    const label = field === 'email' ? 'email address' : 'phone number';
    const change = action === 'verify' ? 'Mark this contact as verified' : 'Remove this contact’s verified status';
    if (window.confirm(`${change}? This is an administrator attestation and does not send or validate a verification code.`)) {
      run('verification', { field, action, reason_text: verificationReason }, `${label} verification updated.`);
    }
  }

  const profileDisabled = busy || profileReason.trim().length < 5;
  const actionDisabled = busy || actionReason.trim().length < 5;
  const verificationDisabled = busy || verificationReason.trim().length < 5;
  const emailVerified = !!verification?.email_verified_at;
  const phoneVerified = !!verification?.phone_verified_at;

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={`Manage account · ${user?.name || `#${user?.id}`}`}
      size="1100px"
      centered
      lockScroll
      closeOnClickOutside={!busy}
      closeOnEscape={!busy}
      styles={{
        content: { maxHeight: 'min(90vh, 980px)', display: 'flex', flexDirection: 'column' },
        body: { overflowY: 'auto' },
      }}
    >
      <Stack gap="md">
        <Text size="sm" c="dimmed">Changes are recorded in this account’s audit history. Driver approvals, financial records, roles and legal acceptances use their dedicated workflows.</Text>
        {error && <Alert color="red" title="Could not save this change">{error}</Alert>}
        <Tabs defaultValue={canVerify ? 'verification' : canEdit ? 'profile' : 'actions'} keepMounted={false}>
          <Tabs.List grow>
            {canVerify && <Tabs.Tab value="verification" leftSection={<FiShield size={15} />}>Contact verification</Tabs.Tab>}
            {canEdit && <Tabs.Tab value="profile">Profile details</Tabs.Tab>}
            {canEdit && <Tabs.Tab value="actions">Account access</Tabs.Tab>}
          </Tabs.List>

          {canVerify && (
            <Tabs.Panel value="verification" pt="md">
              <Stack gap="md">
                <Alert color="blue" variant="light" title="Administrator verification">
                  This records that an administrator has checked the contact. It does not send an email, SMS, or verification code. Confirm the person’s identity and contact ownership before continuing.
                </Alert>
                <Textarea
                  label="Reason for this verification change"
                  description="Enter this first. A reason is required for the audit history (at least 5 characters)."
                  placeholder="For example: ownership confirmed during support call"
                  value={verificationReason}
                  onChange={(e) => setVerificationReason(e.currentTarget.value)}
                  minRows={2}
                  maxLength={500}
                  required
                />
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                  <ContactVerificationCard
                    kind="email" value={user?.email} verified={emailVerified} busy={busy}
                    disabled={verificationDisabled} onChange={changeVerification}
                  />
                  <ContactVerificationCard
                    kind="phone" value={verification?.phone_e164 || user?.phone_number} verified={phoneVerified} busy={busy}
                    disabled={verificationDisabled} onChange={changeVerification}
                  />
                </SimpleGrid>
              </Stack>
            </Tabs.Panel>
          )}

          {canEdit && (
            <Tabs.Panel value="profile" pt="md">
              <Stack gap="md">
                {PROFILE_GROUPS.map((group) => {
                  const fields = group.fields.filter((key) => EDITABLE.includes(key));
                  return (
                    <Card key={group.title} withBorder radius="md" padding="md">
                      <Text fw={600} mb="sm">{group.title}</Text>
                      <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                        {fields.map((key) => (
                          <TextInput
                            key={key}
                            label={labelFor(key)}
                            type={key === 'email' ? 'email' : ['date_of_birth', 'driving_license_issue_date', 'driving_license_validity'].includes(key) ? 'date' : key === 'max_passengers' ? 'number' : 'text'}
                            value={form[key] || ''}
                            onChange={(e) => update(key, e.currentTarget.value)}
                          />
                        ))}
                      </SimpleGrid>
                    </Card>
                  );
                })}
                <Card withBorder radius="md" padding="md">
                  <Switch label="Marketing messages allowed" description="This preference does not override SMS opt-out or legal communication requirements." checked={!!form.marketing_opt_in} onChange={(e) => update('marketing_opt_in', e.currentTarget.checked)} />
                </Card>
                <Textarea
                  label="Reason for profile change"
                  description="Required for the audit history (at least 5 characters)."
                  placeholder="Briefly explain why these profile details are being corrected"
                  value={profileReason}
                  onChange={(e) => setProfileReason(e.currentTarget.value)}
                  minRows={2}
                  maxLength={500}
                  required
                />
                <Group justify="flex-end"><Button variant="default" onClick={onClose}>Close</Button><Button loading={busy} disabled={profileDisabled} onClick={saveProfile}>Save profile changes</Button></Group>
              </Stack>
            </Tabs.Panel>
          )}

          {canEdit && (
            <Tabs.Panel value="actions" pt="md">
              <Stack gap="md">
                <Alert color="yellow" variant="light" title="Password reset">
                  Sends a one-hour reset link to the user’s email and invalidates current sessions. Administrators cannot view or set the password.
                </Alert>
                <Textarea
                  label="Reason for account action"
                  description="Required for the audit history (at least 5 characters)."
                  placeholder="Briefly explain why this account action is needed"
                  value={actionReason}
                  onChange={(e) => setActionReason(e.currentTarget.value)}
                  minRows={2}
                  maxLength={500}
                  required
                />
                <Group>
                  {canEdit && <>
                    <Button variant="light" loading={busy} disabled={actionDisabled} onClick={() => run('sessions/revoke', { reason_text: actionReason }, 'Sessions revoked.')}>Revoke all sessions</Button>
                    {!!user?.email && <Button variant="light" loading={busy} disabled={actionDisabled} onClick={() => run('password-reset-link', { reason_text: actionReason }, 'Reset link sent.')}>Send password reset link</Button>}
                    {['Driver', 'Pending Driver'].includes(user?.user_type) && user?.ready_for_trip === 'Yes' && <Button color="orange" variant="light" loading={busy} disabled={actionDisabled} onClick={() => { if (window.confirm('Force this driver offline? Current rides are not cancelled.')) run('force-offline', { reason_text: actionReason }, 'Driver forced offline.'); }}>Force driver offline</Button>}
                  </>}
                </Group>
              </Stack>
            </Tabs.Panel>
          )}
        </Tabs>
        <Divider />
        <Group justify="space-between">
          <Text size="xs" c="dimmed">User #{user?.id} · {user?.user_type || 'Account'}</Text>
          <Button variant="default" onClick={onClose} disabled={busy}>Close</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
