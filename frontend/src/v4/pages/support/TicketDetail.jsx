import React, { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Anchor, Button, Card, Checkbox, Grid, Group, Select, Stack, Text, Textarea } from '@mantine/core';
import { http } from '../../lib/api';
import { fmt, humanize } from '../../lib/format';
import { useAuth } from '../../../contexts/AuthContext';
import { ErrorBox, KV, Loading, notifyErr, notifyOk, PageHeader, RideLink, StatusBadge, UserLink } from '../../components/ui';
import { SlaTimer } from './SupportQueue';

export default function TicketDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { user: me } = useAuth();
  const q = useQuery({ queryKey: ['support', 'ticket', id], queryFn: () => http.get(`/admin/support/tickets/${id}`) });
  const [body, setBody] = useState('');
  const [internal, setInternal] = useState(false);
  const [resolution, setResolution] = useState('');
  const [busy, setBusy] = useState(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ['support'] });
  const run = async (key, fn, msg) => {
    setBusy(key);
    try { await fn(); notifyOk(msg); refresh(); } catch (e) { notifyErr(e); } finally { setBusy(null); }
  };
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const t = q.data;
  return (
    <>
      <PageHeader title={<Group gap="xs">#{t.id} {t.subject} <StatusBadge value={t.status} size="lg" /></Group>}
        subtitle={`${humanize(t.type)} · ${t.priority} priority · opened ${fmt.dateTime(t.created_at)}`}
        actions={<SlaTimer sla={t.sla} status={t.status} />} />
      {t.type === 'appeal' && t.user && (
        <Alert color="grape" mb="sm">
          Account appeal — user is currently <b>{humanize(t.user.account_status)}</b>. To grant it, reactivate from the <Anchor component={Link} to={`/users/${t.user.id}`}>user profile</Anchor> (reason “Appeal granted”).
        </Alert>
      )}
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Card withBorder radius="md" padding="sm" mb="sm">
            <Text size="xs" c="dimmed">Original message</Text>
            <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{t.body}</Text>
          </Card>
          <Stack gap="xs">
            {(t.messages || []).map((m) => (
              <Card key={m.id} withBorder radius="md" padding="sm"
                bg={m.author_type === 'internal' ? 'var(--mantine-color-yellow-light)' : m.author_type === 'admin' ? 'var(--mantine-color-blue-light)' : undefined}>
                <Text size="xs" c="dimmed">{humanize(m.author_type)} #{m.author_id} · {fmt.dateTime(m.created_at)}</Text>
                <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{m.body}</Text>
              </Card>
            ))}
          </Stack>
          <Card withBorder radius="md" padding="sm" mt="sm">
            <Textarea placeholder={internal ? 'Internal note (not visible to the user)' : 'Reply to the user'} value={body} onChange={(e) => setBody(e.currentTarget.value)} autosize minRows={3} />
            <Group justify="space-between" mt="xs">
              <Checkbox label="Internal note" checked={internal} onChange={(e) => setInternal(e.currentTarget.checked)} />
              <Button disabled={!body.trim()} loading={busy === 'reply'} onClick={() => run('reply', async () => { await http.post(`/admin/support/tickets/${id}/reply`, { body, internal }); setBody(''); }, internal ? 'Note added' : 'Reply sent')}>
                {internal ? 'Add note' : 'Send reply'}
              </Button>
            </Group>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Stack gap="sm">
            <Card withBorder radius="md" padding="sm">
              <KV items={[
                ['User', <UserLink id={t.user_id} name={t.user?.name} />], ['User type', t.user?.user_type],
                ['Account', <StatusBadge value={t.user?.account_status} />],
                ['Ride', t.ride_type ? <RideLink type={t.ride_type} id={t.ride_id} /> : '—'],
                ['Assignee', t.assigned_to ? <UserLink id={t.assigned_to} /> : 'Unassigned'],
                ['SLA due', fmt.dateTime(t.sla?.due_at)], ['First response', fmt.dateTime(t.sla?.first_response_at)],
                ['Resolved', fmt.dateTime(t.resolved_at)], ['Resolution', t.resolution],
              ]} />
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Assign</Text>
              <Group gap="xs">
                <Button size="xs" variant="light" loading={busy === 'assign'} onClick={() => run('assign', () => http.post(`/admin/support/tickets/${id}/assign`, { admin_id: 'me' }), 'Assigned to you')} disabled={t.assigned_to === me?.id}>Assign to me</Button>
                <Select size="xs" placeholder="Priority" data={['urgent', 'high', 'normal', 'low']} value={t.priority} w={120}
                  onChange={(v) => v && run('prio', () => http.post(`/admin/support/tickets/${id}/assign`, { admin_id: t.assigned_to || 'me', priority: v }), 'Priority updated')} />
              </Group>
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Status</Text>
              <Textarea placeholder="Resolution (sent to the user when resolving)" value={resolution} onChange={(e) => setResolution(e.currentTarget.value)} autosize minRows={2} mb="xs" />
              <Group gap="xs">
                {['open', 'pending', 'resolved', 'closed'].filter((s) => s !== t.status).map((s) => (
                  <Button key={s} size="xs" variant={s === 'resolved' ? 'filled' : 'light'} color={s === 'resolved' ? 'green' : s === 'closed' ? 'gray' : 'blue'} loading={busy === s}
                    onClick={() => run(s, () => http.post(`/admin/support/tickets/${id}/status`, { status: s, resolution: resolution || undefined }), `Ticket ${s}`)}>
                    {humanize(s)}
                  </Button>
                ))}
              </Group>
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>
    </>
  );
}
