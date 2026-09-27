import React, { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Anchor, Avatar, Badge, Button, Card, Grid, Group, SimpleGrid, Stack, Tabs, Text,
} from '@mantine/core';
import { FiShield, FiUserCheck } from 'react-icons/fi';
import { http, page } from '../../lib/api';
import { fmt, humanize, initials, money } from '../../lib/format';
import { useRoles } from '../../lib/roles';
import { DocThumb, DocZoomModal } from '../../components/DocViewer';
import {
  DataTable, Empty, ErrorBox, Json, KV, Loading, notifyOk, PageHeader, RideLink, StageBadge, StatCard, StatusBadge, Time, UserLink,
} from '../../components/ui';
import AccountStatusModal from './AccountStatusModal';

function History({ id }) {
  const [p, setP] = useState(1);
  const q = useQuery({ queryKey: ['user-history', id, p], queryFn: () => http.get(`/admin/users/${id}/history`, { page: p }) });
  const pg = page(q.data);
  return (
    <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} empty="No audit history."
      columns={[
        { key: 'created_at', label: 'When', render: (r) => <Time value={r.created_at} seconds /> },
        { key: 'action', label: 'Action', render: (r) => <Text size="sm" ff="monospace">{r.action}</Text> },
        { key: 'actor', label: 'Actor', render: (r) => (r.actor_id ? `${r.actor_name || ''} #${r.actor_id} (${r.actor_type})` : r.actor_type) },
        { key: 'entity', label: 'Entity', render: (r) => `${r.entity_type || ''} ${r.entity_id || ''}` },
        { key: 'change', label: 'Change', render: (r) => <Json value={r.after_json || r.meta} maxH={90} /> },
      ]} />
  );
}

function UserRides({ id }) {
  const nav = useNavigate();
  const [p, setP] = useState(1);
  const q = useQuery({ queryKey: ['rides', { user_id: id, p }], queryFn: () => http.get('/admin/rides', { user_id: id, page: p }) });
  const pg = page(q.data);
  return (
    <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} onRowClick={(r) => nav(`/rides/${r.ride_type}/${r.id}`)} empty="No rides."
      columns={[
        { key: 'id', label: 'Ride', render: (r) => <RideLink type={r.ride_type} id={r.id} /> },
        { key: 'stage', label: 'Stage', render: (r) => <StageBadge stage={r.stage} /> },
        { key: 'role', label: 'Role', render: (r) => (String(r.driver_id) === String(id) ? 'Driver' : 'Customer') },
        { key: 'route', label: 'Route', render: (r) => <Text size="xs" lineClamp={1}>{r.pickup} → {r.dropoff}</Text> },
        { key: 'fare', label: 'Fare', render: (r) => money(r.fare_cents) },
        { key: 'created_at', label: 'Created', render: (r) => <Time value={r.created_at} /> },
      ]} />
  );
}

function UserRatings({ id }) {
  const q = useQuery({ queryKey: ['ratings', 'ratee', id], queryFn: () => http.get('/admin/ratings', { ratee_id: id, per_page: 50 }) });
  return (
    <DataTable loading={q.isLoading} error={q.error} rows={q.data?.items || []} empty="No ratings received."
      columns={[
        { key: 'stars', label: 'Stars', render: (x) => <Text c={x.stars <= 2 ? 'red' : undefined}>{'★'.repeat(x.stars)}</Text> },
        { key: 'rater', label: 'From', render: (x) => <UserLink id={x.rater_id} name={x.rater?.name} /> },
        { key: 'ride', label: 'Ride', render: (x) => <RideLink type={x.ride_type} id={x.ride_id} /> },
        { key: 'tags', label: 'Tags', render: (x) => (x.tags || []).join(', ') },
        { key: 'comment', label: 'Comment' },
        { key: 'hidden', label: 'Hidden', render: (x) => (x.hidden_by_admin ? <Badge size="xs" color="gray">hidden</Badge> : '') },
        { key: 'created_at', label: 'When', render: (x) => <Time value={x.created_at} /> },
      ]} />
  );
}

export default function UserDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { can } = useRoles();
  const q = useQuery({ queryKey: ['user-profile', id], queryFn: () => http.get(`/admin/users/${id}/profile`) });
  const [statusModal, setStatusModal] = useState(null);
  const [doc, setDoc] = useState(null);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { user: u, account, verification: v, strikes, driver_application: app, documents, background_checks: bgcs, legal_acceptances: acc, support_tickets: tickets } = q.data;
  const st = account.account_status;
  return (
    <>
      <PageHeader
        title={<Group gap="sm"><Avatar src={u.avatar || null} radius="xl">{initials(u.name)}</Avatar>{u.name || `User #${u.id}`}<StatusBadge value={st} size="lg" /></Group>}
        subtitle={`#${u.id} · ${u.user_type} · joined ${fmt.date(u.created_at)}${u.admin_roles?.length ? ` · admin: ${u.admin_roles.join(', ')}` : ''}`}
        actions={<>
          {st !== 'active' && <Button color="green" onClick={() => setStatusModal('reactivate')}>Reactivate</Button>}
          {st === 'active' && <Button color="orange" variant="light" onClick={() => setStatusModal('suspend')}>Suspend</Button>}
          {st === 'active' && <Button color="gray" variant="light" onClick={() => setStatusModal('deactivate')}>Deactivate</Button>}
          {st !== 'banned' && <Button color="red" variant="light" onClick={() => setStatusModal('ban')}>Ban</Button>}
          {app && can('onboarding') && <Button variant="default" leftSection={<FiUserCheck />} component={Link} to={`/onboarding/${app.id}`}>Application</Button>}
        </>}
      />
      {st !== 'active' && (
        <Alert color={st === 'banned' ? 'red' : 'orange'} mb="sm" icon={<FiShield />}>
          {humanize(st)} · {account.reason_label || account.reason_code || 'no reason code'}
          {account.suspended_until ? ` · until ${fmt.dateTime(account.suspended_until)}` : ''}
          {account.status_reason ? ` · “${account.status_reason}”` : ''}
        </Alert>
      )}
      {account.pending_account_status && <Alert color="yellow" mb="sm">Pending change to <b>{humanize(account.pending_account_status)}</b> when the current ride ends.</Alert>}
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm" mb="sm">
        <StatCard label="Rating" value={u.rating ? `★ ${Number(u.rating).toFixed(2)}` : '—'} hint={`${u.rating_count || 0} ratings`} />
        <StatCard label="Strikes (window)" value={strikes.in_window} hint={`${strikes.total} total`} color={strikes.in_window >= 3 ? 'red' : undefined} />
        <StatCard label="Phone" value={v.phone_verified_at ? 'Verified' : 'Unverified'} color={v.phone_verified_at ? 'green' : 'orange'} hint={v.phone_e164 || u.phone_number} />
        <StatCard label="Email" value={v.email_verified_at ? 'Verified' : 'Unverified'} color={v.email_verified_at ? 'green' : 'orange'} hint={u.email} />
      </SimpleGrid>
      <Tabs defaultValue="overview" keepMounted={false}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="rides">Rides</Tabs.Tab>
          {can('ratings') && <Tabs.Tab value="ratings">Ratings</Tabs.Tab>}
          <Tabs.Tab value="strikes">Strikes ({strikes.total})</Tabs.Tab>
          <Tabs.Tab value="documents">Documents ({documents.length})</Tabs.Tab>
          <Tabs.Tab value="legal">Legal ({acc.length})</Tabs.Tab>
          <Tabs.Tab value="support">Support ({tickets.length})</Tabs.Tab>
          <Tabs.Tab value="history">Audit history</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview">
          <Grid gutter="sm">
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Card withBorder radius="md" padding="sm">
                <Text fw={600} mb="xs">Profile</Text>
                <KV items={[
                  ['Email', u.email], ['Phone', v.phone_e164 || u.phone_number], ['Line type', v.phone_line_type],
                  ['Province', u.province], ['Address', u.current_address], ['Language', u.preferred_language],
                  ['Marketing opt-in', u.marketing_opt_in ? 'Yes' : 'No'], ['SMS opt-out', account.sms_opt_out_at ? fmt.dateTime(account.sms_opt_out_at) : 'No'],
                  ['Online', u.ready_for_trip], ['Vehicle', u.automobile], ['Licence', u.driving_license_number],
                  ['Last location', u.last_location_update ? fmt.dateTime(u.last_location_update) : '—'],
                ]} />
              </Card>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Stack gap="sm">
                <Card withBorder radius="md" padding="sm">
                  <Text fw={600} mb="xs">Account</Text>
                  <KV items={[
                    ['Status', <StatusBadge value={st} />], ['Changed', account.changed_at ? fmt.dateTime(account.changed_at) : '—'],
                    ['Changed by', account.status_changed_by ? <UserLink id={account.status_changed_by} /> : '—'],
                    ['Can appeal', account.can_appeal ? 'Yes' : 'No'], ['Can go online', account.can_go_online === null ? 'n/a' : account.can_go_online ? 'Yes' : `No — ${account.go_online_block_reason}`],
                    ['Token version', account.token_version],
                  ]} />
                </Card>
                <Card withBorder radius="md" padding="sm">
                  <Text fw={600} mb="xs">Driver onboarding</Text>
                  {app ? (
                    <KV items={[
                      ['Application', can('onboarding') ? <Anchor component={Link} to={`/onboarding/${app.id}`} size="sm">#{app.id}</Anchor> : `#${app.id}`],
                      ['Status', <StatusBadge value={app.status} />], ['Current step', humanize(app.current_step)],
                      ['Service types', (app.service_types || []).map(humanize).join(', ')],
                      ['Background check', bgcs[0] ? <StatusBadge value={bgcs[0].status} /> : 'none'],
                    ]} />
                  ) : <Text size="sm" c="dimmed">No driver application.</Text>}
                </Card>
                {v.recent_phone_verifications?.length > 0 && (
                  <Card withBorder radius="md" padding="sm">
                    <Text fw={600} mb="xs">Recent phone verifications</Text>
                    {v.recent_phone_verifications.map((p) => (
                      <Text key={p.id} size="xs">{fmt.dateTime(p.created_at)} · {p.purpose} · {p.channel} · {p.status}</Text>
                    ))}
                  </Card>
                )}
              </Stack>
            </Grid.Col>
          </Grid>
        </Tabs.Panel>
        <Tabs.Panel value="rides"><UserRides id={id} /></Tabs.Panel>
        {can('ratings') && <Tabs.Panel value="ratings"><UserRatings id={id} /></Tabs.Panel>}
        <Tabs.Panel value="strikes">
          <DataTable rows={strikes.items} empty="No reliability strikes."
            columns={[
              { key: 'created_at', label: 'When', render: (s) => <Time value={s.created_at} /> },
              { key: 'reason', label: 'Reason', render: (s) => humanize(s.reason) },
              { key: 'ride', label: 'Ride', render: (s) => (s.ride_type ? <RideLink type={s.ride_type} id={s.ride_id} /> : '—') },
              { key: 'note', label: 'Note' },
            ]} />
        </Tabs.Panel>
        <Tabs.Panel value="documents">
          {documents.length ? (
            <SimpleGrid cols={{ base: 2, sm: 3, lg: 5 }} spacing="sm">
              {documents.map((d) => (
                <Card key={d.id} withBorder padding="xs" radius="md">
                  <DocThumb doc={d} onOpen={() => setDoc(d)} />
                  <Text size="sm" fw={500} mt={4} truncate>{d.title}</Text>
                  <Group gap={4}><StatusBadge value={d.status} size="xs" />{d.expires_at && <Text size="xs" c="dimmed">exp {fmt.date(d.expires_at)}</Text>}</Group>
                </Card>
              ))}
            </SimpleGrid>
          ) : <Empty>No documents uploaded.</Empty>}
          {bgcs.length > 0 && (
            <Card withBorder radius="md" padding="sm" mt="sm">
              <Text fw={600} mb="xs">Background checks</Text>
              {bgcs.map((b) => <Text key={b.id} size="sm">#{b.id} · {b.provider} · <StatusBadge value={b.status} size="xs" /> · {b.result || ''} · paid {money(b.fee_cents)} ({b.paid_by}) · {fmt.dateTime(b.completed_at || b.initiated_at || b.created_at)}</Text>)}
            </Card>
          )}
        </Tabs.Panel>
        <Tabs.Panel value="legal">
          <DataTable rows={acc} empty="No legal acceptances recorded."
            columns={[
              { key: 'document_id', label: 'Document', render: (a) => `#${a.document_id} ${a.document_type || a.type || ''}` },
              { key: 'version', label: 'Version' }, { key: 'method', label: 'Method' },
              { key: 'accepted_at', label: 'Accepted', render: (a) => <Time value={a.accepted_at} seconds /> },
              { key: 'ip', label: 'IP' }, { key: 'app_version', label: 'App' },
            ]} />
        </Tabs.Panel>
        <Tabs.Panel value="support">
          <DataTable rows={tickets} empty="No support tickets."
            columns={[
              { key: 'id', label: '#', render: (t) => <Anchor component={Link} to={`/support/${t.id}`} size="sm">#{t.id}</Anchor> },
              { key: 'type', label: 'Type', render: (t) => humanize(t.type) }, { key: 'subject', label: 'Subject' },
              { key: 'status', label: 'Status', render: (t) => <StatusBadge value={t.status} /> },
              { key: 'created_at', label: 'Opened', render: (t) => <Time value={t.created_at} /> },
            ]} />
        </Tabs.Panel>
        <Tabs.Panel value="history"><History id={id} /></Tabs.Panel>
      </Tabs>
      <AccountStatusModal
        user={u} current={st} opened={!!statusModal} initialAction={statusModal} onClose={() => setStatusModal(null)}
        onDone={(msg) => { notifyOk(msg); qc.invalidateQueries({ queryKey: ['user-profile', id] }); qc.invalidateQueries({ queryKey: ['user-history', id] }); qc.invalidateQueries({ queryKey: ['users'] }); }}
      />
      <DocZoomModal doc={doc} opened={!!doc} onClose={() => setDoc(null)} />
    </>
  );
}
