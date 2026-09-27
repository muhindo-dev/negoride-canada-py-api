import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Alert, Badge, Button, Card, Grid, Group, NumberInput, SegmentedControl, Select, Stack, Switch, Tabs, Text, Textarea, TextInput, Tooltip,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from 'recharts';
import { http, page } from '../lib/api';
import { fmt, humanize, statusColor } from '../lib/format';
import { useRoles } from '../lib/roles';
import { DataTable, ErrorBox, notifyErr, notifyOk, PageHeader, Time, UserLink } from '../components/ui';

export const PROVINCES = ['AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'];
const STATUS_ORDER = ['queued', 'sent', 'delivered', 'opened', 'failed', 'skipped'];
const COLORS = { queued: '#adb5bd', sent: '#339af0', delivered: '#40c057', opened: '#12b886', failed: '#fa5252', skipped: '#868e96' };

function Log() {
  const [userId, setUserId] = useState('');
  const [eventKey, setEventKey] = useState('');
  const [dk] = useDebouncedValue(eventKey, 350);
  const [p, setP] = useState(1);
  const params = { user_id: userId || undefined, event_key: dk || undefined, page: p, per_page: 25 };
  const q = useQuery({ queryKey: ['notifications', 'log', params], queryFn: () => http.get('/admin/notifications', params), refetchInterval: 30000 });
  const pg = page(q.data);
  return (
    <>
      <Group mb="sm" gap="xs">
        <NumberInput size="xs" placeholder="User ID" value={userId} onChange={(v) => { setUserId(v ? String(v) : ''); setP(1); }} w={110} hideControls />
        <TextInput size="xs" placeholder="Event key prefix (e.g. ride.)" value={eventKey} onChange={(e) => { setEventKey(e.currentTarget.value); setP(1); }} w={220} />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={1000} empty="No notifications."
        columns={[
          { key: 'created_at', label: 'When', render: (n) => <Time value={n.created_at} /> },
          { key: 'user', label: 'User', render: (n) => <UserLink id={n.user_id} name={n.user_name} /> },
          { key: 'event_key', label: 'Event', render: (n) => <Group gap={4}><Text size="xs" ff="monospace">{n.event_key}</Text>{n.is_critical && <Badge size="xs" color="red">critical</Badge>}</Group> },
          { key: 'title', label: 'Message', render: (n) => <div><Text size="sm" fw={500} lineClamp={1}>{n.title}</Text><Text size="xs" c="dimmed" lineClamp={1}>{n.body}</Text></div> },
          { key: 'deliveries', label: 'Channels', render: (n) => (
            <Group gap={4}>
              {(n.deliveries || []).map((d) => (
                <Tooltip key={d.id} label={`${d.status}${d.error ? ` — ${d.error}` : ''} · attempts ${d.attempts}${d.sent_at ? ` · sent ${fmt.time(d.sent_at)}` : ''}`} multiline w={260}>
                  <Badge size="sm" variant="light" color={statusColor(d.status)}>{d.channel}: {d.status}</Badge>
                </Tooltip>
              ))}
              {!n.deliveries?.length && <Text size="xs" c="dimmed">inbox only</Text>}
            </Group>
          ) },
          { key: 'read', label: 'Read', render: (n) => (n.opened_at ? 'opened' : n.read_at ? 'read' : '—') },
        ]} />
    </>
  );
}

function Stats() {
  const [days, setDays] = useState('7');
  const q = useQuery({ queryKey: ['notifications', 'stats', days], queryFn: () => http.get('/admin/notifications/stats', { days }) });
  const rows = Object.entries(q.data || {}).map(([channel, st]) => ({ channel, ...st }));
  const statuses = STATUS_ORDER.filter((s) => rows.some((r) => r[s])).concat(
    [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((k) => k !== 'channel' && !STATUS_ORDER.includes(k)),
  );
  return (
    <Card withBorder radius="md" padding="sm">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Delivery status by channel</Text>
        <SegmentedControl size="xs" value={days} onChange={setDays} data={['1', '7', '30'].map((d) => ({ value: d, label: `${d} d` }))} />
      </Group>
      <ErrorBox error={q.error} />
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="channel" />
          <YAxis allowDecimals={false} />
          <RTooltip />
          <Legend />
          {statuses.map((s) => <Bar key={s} dataKey={s} stackId="a" fill={COLORS[s] || '#7950f2'} name={humanize(s)} />)}
        </BarChart>
      </ResponsiveContainer>
      {!rows.length && !q.isLoading && <Text size="sm" c="dimmed">No deliveries in this window.</Text>}
    </Card>
  );
}

function Compose() {
  const { can } = useRoles();
  const [f, setF] = useState({ title: '', body: '', role: 'all', province: '', city: '', route: 'home', marketing_only: true });
  const [count, setCount] = useState(null);
  const [busy, setBusy] = useState(null);
  const set = (k, v) => { setF({ ...f, [k]: v }); setCount(null); };
  const send = async (dry) => {
    setBusy(dry ? 'dry' : 'send');
    try {
      const body = { ...f, province: f.province || undefined, city: f.city || undefined, dry_run: dry };
      if (dry) {
        const r = await http.post('/admin/notifications/broadcast', body);
        setCount(r.recipients);
      } else {
        if (!window.confirm(`Send “${f.title}” to ${count ?? 'all matching'} user(s)?`)) return;
        const r = await http.postFull('/admin/notifications/broadcast', body);
        notifyOk(r.message);
      }
    } catch (e) { notifyErr(e); } finally { setBusy(null); }
  };
  if (!can('broadcast')) return <Alert color="yellow">Composing broadcasts needs the Ops role.</Alert>;
  return (
    <Grid gutter="sm">
      <Grid.Col span={{ base: 12, md: 7 }}>
        <Card withBorder radius="md" padding="sm">
          <Stack gap="xs">
            <TextInput label="Title" required value={f.title} onChange={(e) => set('title', e.currentTarget.value)} maxLength={120} />
            <Textarea label="Body" required value={f.body} onChange={(e) => set('body', e.currentTarget.value)} autosize minRows={3} maxLength={500} />
            <Group grow>
              <Select label="Audience" value={f.role} onChange={(v) => set('role', v)} data={[{ value: 'all', label: 'Everyone' }, { value: 'customers', label: 'Customers' }, { value: 'drivers', label: 'Drivers' }]} allowDeselect={false} />
              <Select label="Province" clearable value={f.province} onChange={(v) => set('province', v || '')} data={PROVINCES} />
              <TextInput label="City contains" value={f.city} onChange={(e) => set('city', e.currentTarget.value)} placeholder="e.g. Toronto" />
            </Group>
            <Group grow>
              <TextInput label="Deep link route" value={f.route} onChange={(e) => set('route', e.currentTarget.value)} />
              <Switch label="Only users who opted in to marketing (CASL)" checked={f.marketing_only} onChange={(e) => set('marketing_only', e.currentTarget.checked)} mt="lg" />
            </Group>
            <Group justify="space-between" mt="xs">
              <Text size="sm" data-testid="broadcast-count">{count === null ? 'Run a dry run to count recipients.' : <>Would reach <b>{count}</b> user(s).</>}</Text>
              <Group gap="xs">
                <Button variant="default" loading={busy === 'dry'} disabled={!f.title || !f.body} onClick={() => send(true)}>Dry run (count)</Button>
                <Button color="orange" loading={busy === 'send'} disabled={!f.title || !f.body || count === null} onClick={() => send(false)}>Send broadcast</Button>
              </Group>
            </Group>
          </Stack>
        </Card>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 5 }}>
        <Card withBorder radius="md" padding="sm">
          <Text size="xs" c="dimmed" mb={6}>Push preview</Text>
          <Card radius="lg" padding="sm" bg="var(--mantine-color-default-hover)">
            <Group gap={6} mb={4}><Badge size="xs" color="orange">NegoRide</Badge><Text size="xs" c="dimmed">now</Text></Group>
            <Text fw={600} size="sm">{f.title || 'Title'}</Text>
            <Text size="sm">{f.body || 'Message body'}</Text>
          </Card>
          <Text size="xs" c="dimmed" mt="xs">Sent as the “broadcast” event (push + in-app inbox). Delivery appears in the log. Audited.</Text>
        </Card>
      </Grid.Col>
    </Grid>
  );
}

export default function Notifications() {
  return (
    <>
      <PageHeader title="Notifications" subtitle="Delivery log with per-channel status · broadcast composer" />
      <Tabs defaultValue="log" keepMounted={false}>
        <Tabs.List mb="sm"><Tabs.Tab value="log">Delivery log</Tabs.Tab><Tabs.Tab value="stats">Channel stats</Tabs.Tab><Tabs.Tab value="compose">Compose broadcast</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="log"><Log /></Tabs.Panel>
        <Tabs.Panel value="stats"><Stats /></Tabs.Panel>
        <Tabs.Panel value="compose"><Compose /></Tabs.Panel>
      </Tabs>
    </>
  );
}
