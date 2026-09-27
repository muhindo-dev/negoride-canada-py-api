import React, { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Anchor, Badge, Button, Card, Drawer, Grid, Group, Modal, NumberInput, Select, SimpleGrid, Stack, Switch, Tabs, Text, Textarea, TextInput,
} from '@mantine/core';
import { FiPlus } from 'react-icons/fi';
import { http, page } from '../../lib/api';
import { humanize } from '../../lib/format';
import { useRoles } from '../../lib/roles';
import MapView from '../../components/map/MapView';
import {
  DataTable, ErrorBox, KV, Loading, notifyErr, notifyOk, PageHeader, RideLink, StatCard, StatusBadge, Time, UserLink,
} from '../../components/ui';
import RecordingPlayer from './RecordingPlayer';

function Incidents() {
  const nav = useNavigate();
  const [status, setStatus] = useState('');
  const [kind, setKind] = useState('');
  const [p, setP] = useState(1);
  const q = useQuery({
    queryKey: ['safety', 'incidents', status, kind, p],
    queryFn: () => http.get('/admin/safety/incidents', { status, kind, page: p, per_page: 25 }),
    refetchInterval: 10000,
  });
  const pg = page(q.data);
  const openOnes = pg.items.filter((i) => i.is_open && Number.isFinite(i.last_lat ?? i.lat));
  return (
    <Stack gap="sm">
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm">
        <StatCard label="Open (unacknowledged)" value={q.data?.open_count ?? '—'} color={q.data?.open_count ? 'red' : undefined} />
        <StatCard label="Shown" value={pg.total} />
      </SimpleGrid>
      {openOnes.length > 0 && (
        <MapView
          height={260}
          markers={openOnes.map((i) => ({
            id: `i${i.id}`, lat: i.last_lat ?? i.lat, lng: i.last_lng ?? i.lng, color: i.status === 'open' ? '#e03131' : '#f08c00',
            radius: 10, label: `#${i.id} ${i.user?.name || ''} (${i.status})`, onClick: () => nav(`/safety/incidents/${i.id}`),
          }))}
          fitKey={openOnes.map((i) => i.id).join(',')}
        />
      )}
      <Group gap="xs">
        <Select size="xs" placeholder="Status" value={status} onChange={(v) => { setStatus(v || ''); setP(1); }} clearable
          data={[{ value: 'open', label: 'Open + acknowledged' }, 'acknowledged', 'resolved', 'false_alarm'].map((x) => (typeof x === 'string' ? { value: x, label: humanize(x) } : x))} w={200} />
        <Select size="xs" placeholder="Kind" value={kind} onChange={(v) => { setKind(v || ''); setP(1); }} clearable data={['sos', 'check_in_timeout'].map((x) => ({ value: x, label: humanize(x) }))} w={160} />
      </Group>
      <DataTable
        loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP}
        onRowClick={(r) => nav(`/safety/incidents/${r.id}`)}
        highlight={(r) => r.status === 'open'}
        empty="No incidents."
        columns={[
          { key: 'id', label: '#', render: (r) => <Text fw={600}>#{r.id}</Text> },
          { key: 'status', label: 'Status', render: (r) => <StatusBadge value={r.status} variant={r.status === 'open' ? 'filled' : 'light'} /> },
          { key: 'kind', label: 'Kind', render: (r) => humanize(r.kind) },
          { key: 'severity', label: 'Severity', render: (r) => <StatusBadge value={r.severity} /> },
          { key: 'user', label: 'Raised by', render: (r) => <UserLink id={r.user_id} name={`${r.user?.name || '#' + r.user_id} (${r.role})`} /> },
          { key: 'ride', label: 'Ride', render: (r) => (r.ride_type ? <RideLink type={r.ride_type} id={r.ride_id} /> : '—') },
          { key: 'created_at', label: 'Raised', render: (r) => <Time value={r.created_at} relative /> },
          { key: 'ack', label: 'Acknowledged', render: (r) => (r.acknowledged_at ? <Time value={r.acknowledged_at} relative /> : '—') },
        ]}
      />
    </Stack>
  );
}

function Reports() {
  const qc = useQueryClient();
  const [status, setStatus] = useState('');
  const [p, setP] = useState(1);
  const [open, setOpen] = useState(null);
  const q = useQuery({ queryKey: ['safety', 'reports', status, p], queryFn: () => http.get('/admin/safety/reports', { status, page: p }) });
  const detail = useQuery({ queryKey: ['safety', 'report', open], queryFn: () => http.get(`/admin/safety/reports/${open}`), enabled: !!open });
  const [resolution, setResolution] = useState('');
  const [busy, setBusy] = useState(false);
  const pg = page(q.data);
  const review = async (st) => {
    setBusy(true);
    try {
      await http.post(`/admin/safety/reports/${open}/review`, { status: st, resolution: resolution || undefined });
      notifyOk(`Report marked ${st}`);
      qc.invalidateQueries({ queryKey: ['safety'] });
    } catch (e) { notifyErr(e); } finally { setBusy(false); }
  };
  const r = detail.data;
  return (
    <>
      <Group mb="sm"><Select size="xs" placeholder="Status" clearable value={status} onChange={(v) => { setStatus(v || ''); setP(1); }} data={['open', 'reviewing', 'resolved', 'dismissed']} w={160} /></Group>
      <DataTable
        loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} onRowClick={(x) => { setOpen(x.id); setResolution(''); }}
        empty="No safety reports."
        columns={[
          { key: 'id', label: '#' },
          { key: 'status', label: 'Status', render: (x) => <StatusBadge value={x.status} /> },
          { key: 'category', label: 'Category', render: (x) => humanize(x.category) },
          { key: 'reporter', label: 'Reporter', render: (x) => <UserLink id={x.reporter?.id} name={x.reporter?.name} /> },
          { key: 'reported', label: 'About', render: (x) => (x.reported_user ? <UserLink id={x.reported_user.id} name={x.reported_user.name} /> : '—') },
          { key: 'ride', label: 'Ride', render: (x) => (x.ride_type ? <RideLink type={x.ride_type} id={x.ride_id} /> : '—') },
          { key: 'att', label: 'Files', render: (x) => (x.attachments?.length || 0) },
          { key: 'created_at', label: 'Filed', render: (x) => <Time value={x.created_at} relative /> },
        ]}
      />
      <Drawer opened={!!open} onClose={() => setOpen(null)} position="right" size="lg" title={`Safety report #${open}`}>
        {detail.isLoading ? <Loading /> : detail.error ? <ErrorBox error={detail.error} /> : r && (
          <Stack>
            <KV items={[
              ['Status', <StatusBadge value={r.status} />], ['Category', humanize(r.category)],
              ['Reporter', <UserLink id={r.reporter?.id} name={r.reporter?.name} />],
              ['About', r.reported_user ? <UserLink id={r.reported_user.id} name={r.reported_user.name} /> : '—'],
              ['Ride', r.ride_type ? <RideLink type={r.ride_type} id={r.ride_id} /> : '—'], ['Filed', <Time value={r.created_at} />],
              ['Reviewed', r.reviewed_at ? <Time value={r.reviewed_at} /> : '—'],
            ]} />
            <Card withBorder><Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{r.description || '—'}</Text></Card>
            {r.attachments?.length > 0 && (
              <Stack gap={4}>
                <Text fw={600} size="sm">Attachments (links expire in 5 min, access audited)</Text>
                {r.attachments.map((a, i) => (
                  <Anchor key={i} href={a.url} target="_blank" rel="noopener" size="sm">{a.name || `file ${i + 1}`} ({a.content_type})</Anchor>
                ))}
              </Stack>
            )}
            {r.resolution && <KV items={[['Resolution', r.resolution]]} />}
            <Textarea label="Resolution note" value={resolution} onChange={(e) => setResolution(e.currentTarget.value)} autosize minRows={2} />
            <Group>
              <Button size="xs" variant="light" loading={busy} onClick={() => review('reviewing')}>Mark reviewing</Button>
              <Button size="xs" color="green" loading={busy} onClick={() => review('resolved')}>Resolve</Button>
              <Button size="xs" color="gray" loading={busy} onClick={() => review('dismissed')}>Dismiss</Button>
            </Group>
          </Stack>
        )}
      </Drawer>
    </>
  );
}

function Checks() {
  const [status, setStatus] = useState('');
  const [p, setP] = useState(1);
  const q = useQuery({ queryKey: ['safety', 'checks', status, p], queryFn: () => http.get('/admin/safety/checks', { status, page: p }), refetchInterval: 20000 });
  const pg = page(q.data);
  return (
    <>
      <Group mb="sm"><Select size="xs" placeholder="Status" clearable value={status} onChange={(v) => { setStatus(v || ''); setP(1); }} data={['pending', 'ok', 'help', 'escalated'].map((x) => ({ value: x, label: humanize(x) }))} w={160} /></Group>
      <Text size="xs" c="dimmed" mb="xs">“Are you OK?” checks raised by route deviation / long-stop detection (spec §8.4).</Text>
      <DataTable
        loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} empty="No safety checks."
        columns={[
          { key: 'id', label: '#' },
          { key: 'kind', label: 'Kind', render: (x) => humanize(x.kind) },
          { key: 'status', label: 'Status', render: (x) => <StatusBadge value={x.status} /> },
          { key: 'user', label: 'User', render: (x) => <UserLink id={x.user_id} /> },
          { key: 'ride', label: 'Ride', render: (x) => <RideLink type={x.ride_type} id={x.ride_id} /> },
          { key: 'incident', label: 'Incident', render: (x) => (x.incident_id ? <Anchor href={`/safety/incidents/${x.incident_id}`} size="sm">#{x.incident_id}</Anchor> : '—') },
          { key: 'created_at', label: 'Raised', render: (x) => <Time value={x.created_at} relative /> },
          { key: 'responded_at', label: 'Answered', render: (x) => (x.responded_at ? <Time value={x.responded_at} relative /> : '—') },
        ]}
      />
    </>
  );
}

function Recordings({ initial }) {
  const [p, setP] = useState(1);
  const [filters, setFilters] = useState({ ride_id: '', incident_id: '', status: '' });
  const [sel, setSel] = useState(initial || null);
  const q = useQuery({ queryKey: ['safety', 'recordings', filters, p], queryFn: () => http.get('/admin/safety/recordings', { ...filters, page: p }) });
  const pg = page(q.data);
  return (
    <Grid gutter="sm">
      <Grid.Col span={{ base: 12, lg: sel ? 5 : 12 }}>
        <Group mb="sm" gap="xs">
          <TextInput size="xs" placeholder="Ride ID" value={filters.ride_id} onChange={(e) => setFilters({ ...filters, ride_id: e.currentTarget.value })} w={100} />
          <TextInput size="xs" placeholder="Incident ID" value={filters.incident_id} onChange={(e) => setFilters({ ...filters, incident_id: e.currentTarget.value })} w={110} />
          <Select size="xs" placeholder="Status" clearable value={filters.status} onChange={(v) => setFilters({ ...filters, status: v || '' })} data={['recording', 'stopped', 'deleted']} w={130} />
        </Group>
        <DataTable
          loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} onRowClick={(r) => setSel(r.id)} minWidth={500}
          highlight={(r) => r.id === sel} empty="No recordings."
          columns={[
            { key: 'id', label: '#' },
            { key: 'status', label: 'Status', render: (r) => <StatusBadge value={r.status} /> },
            { key: 'ride', label: 'Ride', render: (r) => (r.ride_type ? `${humanize(r.ride_type)} #${r.ride_id}` : '—') },
            { key: 'chunk_count', label: 'Chunks' },
            { key: 'legal_hold', label: 'Hold', render: (r) => (r.legal_hold ? <Badge size="xs" color="grape">hold</Badge> : '') },
            { key: 'started_at', label: 'Started', render: (r) => <Time value={r.started_at} relative /> },
          ]}
        />
      </Grid.Col>
      {sel && <Grid.Col span={{ base: 12, lg: 7 }}><RecordingPlayer id={sel} key={sel} /></Grid.Col>}
    </Grid>
  );
}

const EMPTY_HC = { name: '', phone: '', email: '', url: '', category: 'support', province: '', description: '', is_emergency: false, sort_order: 100, is_active: true };

function HelpContacts() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['safety', 'help-contacts'], queryFn: () => http.get('/admin/safety/help-contacts') });
  const [edit, setEdit] = useState(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      if (edit.id) await http.put(`/admin/safety/help-contacts/${edit.id}`, edit);
      else await http.post('/admin/safety/help-contacts', edit);
      notifyOk('Help contact saved');
      setEdit(null);
      qc.invalidateQueries({ queryKey: ['safety', 'help-contacts'] });
    } catch (e) { notifyErr(e); } finally { setBusy(false); }
  };
  const remove = async (row) => {
    if (!window.confirm(`Delete ${row.name}?`)) return;
    try { await http.del(`/admin/safety/help-contacts/${row.id}`); qc.invalidateQueries({ queryKey: ['safety', 'help-contacts'] }); } catch (e) { notifyErr(e); }
  };
  return (
    <>
      <Group justify="space-between" mb="sm">
        <Text size="sm" c="dimmed">Shown in the app’s Safety Toolkit (by province). On-call SOS phones live in Settings → safety.oncall_phones.</Text>
        <Button size="xs" leftSection={<FiPlus />} onClick={() => setEdit({ ...EMPTY_HC })}>Add contact</Button>
      </Group>
      <DataTable
        loading={q.isLoading} error={q.error} rows={q.data || []} onRowClick={(r) => setEdit({ ...EMPTY_HC, ...r })} empty="No help contacts."
        columns={[
          { key: 'name', label: 'Name', render: (r) => <Text fw={500} size="sm">{r.name}</Text> },
          { key: 'category', label: 'Category', render: (r) => humanize(r.category) },
          { key: 'province', label: 'Province', render: (r) => r.province || 'All' },
          { key: 'phone', label: 'Phone' },
          { key: 'is_emergency', label: 'Emergency', render: (r) => (r.is_emergency ? <Badge color="red" size="xs">yes</Badge> : '') },
          { key: 'is_active', label: 'Active', render: (r) => (r.is_active ? 'Yes' : 'No') },
          { key: 'x', label: '', render: (r) => <Button size="compact-xs" color="red" variant="subtle" onClick={(e) => { e.stopPropagation(); remove(r); }}>Delete</Button> },
        ]}
      />
      <Modal opened={!!edit} onClose={() => setEdit(null)} title={edit?.id ? `Edit ${edit.name}` : 'New help contact'} centered>
        {edit && (
          <Stack gap="xs">
            <TextInput label="Name" required value={edit.name || ''} onChange={(e) => setEdit({ ...edit, name: e.currentTarget.value })} />
            <Group grow>
              <Select label="Category" required value={edit.category} onChange={(v) => setEdit({ ...edit, category: v })}
                data={['emergency', 'support', 'police_non_emergency', 'roadside', 'crisis', 'other'].map((x) => ({ value: x, label: humanize(x) }))} searchable />
              <TextInput label="Province (2 letters, blank = all)" value={edit.province || ''} onChange={(e) => setEdit({ ...edit, province: e.currentTarget.value.toUpperCase() })} maxLength={2} />
            </Group>
            <Group grow>
              <TextInput label="Phone" value={edit.phone || ''} onChange={(e) => setEdit({ ...edit, phone: e.currentTarget.value })} />
              <TextInput label="Email" value={edit.email || ''} onChange={(e) => setEdit({ ...edit, email: e.currentTarget.value })} />
            </Group>
            <TextInput label="URL" value={edit.url || ''} onChange={(e) => setEdit({ ...edit, url: e.currentTarget.value })} />
            <Textarea label="Description" value={edit.description || ''} onChange={(e) => setEdit({ ...edit, description: e.currentTarget.value })} />
            <Group>
              <NumberInput label="Sort order" value={edit.sort_order} onChange={(v) => setEdit({ ...edit, sort_order: v })} w={120} />
              <Switch label="Emergency" checked={!!edit.is_emergency} onChange={(e) => setEdit({ ...edit, is_emergency: e.currentTarget.checked })} mt="lg" />
              <Switch label="Active" checked={!!edit.is_active} onChange={(e) => setEdit({ ...edit, is_active: e.currentTarget.checked })} mt="lg" />
            </Group>
            <Group justify="flex-end"><Button onClick={save} loading={busy}>Save</Button></Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}

export default function SafetyCenter() {
  const { can } = useRoles();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') || 'incidents';
  return (
    <>
      <PageHeader title="Safety Center" subtitle="Open incidents first · realtime alarm on every new SOS until acknowledged" />
      <Tabs value={tab} onChange={(v) => setSp({ tab: v })} keepMounted={false}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="incidents">Incidents</Tabs.Tab>
          <Tabs.Tab value="reports">Reports</Tabs.Tab>
          <Tabs.Tab value="checks">Safety checks</Tabs.Tab>
          {can('recordings') && <Tabs.Tab value="recordings">Recordings</Tabs.Tab>}
          {can('helpContacts') && <Tabs.Tab value="help">Help contacts</Tabs.Tab>}
        </Tabs.List>
        <Tabs.Panel value="incidents"><Incidents /></Tabs.Panel>
        <Tabs.Panel value="reports"><Reports /></Tabs.Panel>
        <Tabs.Panel value="checks"><Checks /></Tabs.Panel>
        {can('recordings') && <Tabs.Panel value="recordings"><Recordings initial={sp.get('recording') ? Number(sp.get('recording')) : null} /></Tabs.Panel>}
        {can('helpContacts') && <Tabs.Panel value="help"><HelpContacts /></Tabs.Panel>}
      </Tabs>
    </>
  );
}
