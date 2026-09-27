import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Badge, Button, Checkbox, Group, Modal, NumberInput, Stack, Text } from '@mantine/core';
import { FiPlus } from 'react-icons/fi';
import { http } from '../lib/api';
import { ROLE_LABELS } from '../lib/roles';
import { useAuth } from '../../contexts/AuthContext';
import { DataTable, notifyErr, notifyOk, PageHeader, StatusBadge, UserLink } from '../components/ui';

const ROLE_HELP = {
  super_admin: 'Everything, including admin roles',
  ops: 'Live ops, rides, users, onboarding, settings, broadcasts',
  safety_reviewer: 'Safety Center, recordings, onboarding review',
  finance: 'Payments, refunds, payouts, reconciliation, settings',
  support: 'Tickets, users, ratings, receipts',
};

export default function AdminUsers() {
  const qc = useQueryClient();
  const { user: me } = useAuth();
  const q = useQuery({ queryKey: ['admin-users'], queryFn: () => http.get('/admin/admin-users') });
  const [edit, setEdit] = useState(null);
  const [busy, setBusy] = useState(false);
  const roles = q.data?.roles || Object.keys(ROLE_LABELS);
  const save = async () => {
    setBusy(true);
    try {
      await http.put(`/admin/admin-users/${edit.id}/roles`, { roles: edit.roles });
      notifyOk('Roles updated — they apply on the user’s next sign-in');
      setEdit(null);
      qc.invalidateQueries({ queryKey: ['admin-users'] });
    } catch (e) { notifyErr(e); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHeader title="Admin users & roles" subtitle="Super admin only · every change is audited and revokes the user’s sessions"
        actions={<Button leftSection={<FiPlus />} onClick={() => setEdit({ id: '', roles: [], isNew: true })}>Grant admin role</Button>} />
      <DataTable loading={q.isLoading} error={q.error} rows={q.data?.items || []} onRowClick={(u) => setEdit({ ...u, roles: [...u.roles] })} empty="No admin users."
        columns={[
          { key: 'name', label: 'Admin', render: (u) => <UserLink id={u.id} name={`${u.name} (#${u.id})`} /> },
          { key: 'email', label: 'Email' },
          { key: 'roles', label: 'Roles', render: (u) => <Group gap={4}>{u.roles.map((r) => <Badge key={r} variant="light" color={r === 'super_admin' ? 'red' : 'blue'}>{ROLE_LABELS[r] || r}</Badge>)}</Group> },
          { key: 'user_type', label: 'Legacy type' },
          { key: 'account_status', label: 'Account', render: (u) => <StatusBadge value={u.account_status} /> },
        ]} />
      <Modal opened={!!edit} onClose={() => setEdit(null)} title={edit?.isNew ? 'Grant admin roles' : `Roles — ${edit?.name}`} centered>
        {edit && (
          <Stack>
            {edit.isNew && <NumberInput label="User ID" value={edit.id} onChange={(v) => setEdit({ ...edit, id: v })} hideControls description="Find the ID in Users." />}
            {roles.map((r) => (
              <Checkbox key={r} label={<><b>{ROLE_LABELS[r] || r}</b> <Text span size="xs" c="dimmed">— {ROLE_HELP[r]}</Text></>}
                checked={edit.roles.includes(r)}
                disabled={r === 'super_admin' && edit.id === me?.id}
                onChange={(e) => setEdit({ ...edit, roles: e.currentTarget.checked ? [...edit.roles, r] : edit.roles.filter((x) => x !== r) })} />
            ))}
            {!edit.roles.length && !edit.isNew && <Alert color="orange">Removing every role revokes admin access.</Alert>}
            <Group justify="flex-end"><Button onClick={save} loading={busy} disabled={!edit.id}>Save roles</Button></Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}
