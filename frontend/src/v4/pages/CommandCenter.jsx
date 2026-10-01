import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Anchor, Badge, Button, Card, Grid, Group, ScrollArea, SimpleGrid, Stack, Text, Timeline } from '@mantine/core';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from 'recharts';
import { FiActivity, FiAlertOctagon, FiCheckCircle, FiClock, FiDollarSign, FiLock, FiMap, FiNavigation, FiUsers, FiXCircle } from 'react-icons/fi';
import { http, page } from '../lib/api';
import { ago, duration, humanize, money, statusColor } from '../lib/format';
import { useRealtime } from '../lib/realtime';
import { useRoles } from '../lib/roles';
import { DRIVER_STATE_COLOR, useLiveDrivers } from '../lib/liveDrivers';
import MapView from '../components/map/MapView';
import ReadinessPanel from '../components/ReadinessPanel';
import { Empty, ErrorBox, PageHeader, StatCard, Time } from '../components/ui';

function MiniMap() {
  const nav = useNavigate();
  const { drivers, counts, error } = useLiveDrivers({ interval: 20000 });
  const markers = drivers.filter((d) => d.position).map((d) => ({
    id: `d${d.driver_id}`, lat: d.position.lat, lng: d.position.lng, color: DRIVER_STATE_COLOR[d.state],
    label: `${d.name || d.first_name} · ${humanize(d.state)}`, radius: d.state === 'sos' ? 10 : 7,
  }));
  return (
    <Card withBorder radius="md" padding="sm" h="100%">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Live map</Text>
        <Group gap={6}>
          {counts && Object.entries(counts).map(([k, v]) => (
            <Badge key={k} size="xs" variant="dot" color={k === 'sos' ? 'red' : k === 'on_trip' ? 'orange' : k === 'en_route' ? 'blue' : 'gray'}>{humanize(k)} {v}</Badge>
          ))}
          <Button size="compact-xs" variant="light" leftSection={<FiMap />} onClick={() => nav('/live')}>Open</Button>
        </Group>
      </Group>
      <ErrorBox error={error} />
      <MapView height={320} markers={markers} fitKey={markers.length ? `n${markers.length > 0}` : undefined} />
    </Card>
  );
}

// Socket `alert` payloads → feed items. Kinds: pin_locked (ride PIN locked
// after too many wrong attempts), oncall_not_configured (SOS escalation had no
// on-call phones), sos_unacknowledged (escalated). The same alert may arrive
// via admin:ops and admin:sos — deduped on `_k`.
function alertItem(p) {
  const at = p.at || new Date().toISOString();
  if (p.kind === 'pin_locked') {
    return {
      kind: 'pin_locked', severity: 'warning', ride_type: p.ride_type, ride_id: p.ride_id, at,
      text: p.message || `Ride PIN locked on ${p.ride_type} #${p.ride_id} after ${p.attempts} wrong attempts`,
      _k: `pin-${p.ride_type}-${p.ride_id}-${p.attempts ?? ''}`,
    };
  }
  if (p.kind === 'oncall_not_configured') {
    return { kind: 'oncall', severity: 'critical', incident_id: p.incident_id, at, text: p.message || 'SOS escalation failed: no on-call phones configured', _k: `oncall-${p.incident_id}` };
  }
  return { kind: 'alert', severity: p.level || 'critical', incident_id: p.incident_id, ride_type: p.ride_type, ride_id: p.ride_id, at, text: p.message || humanize(p.kind), _k: `a-${p.kind}-${p.incident_id || p.ride_id || Date.now()}` };
}

function FeedTitle({ a }) {
  if (a.kind === 'oncall') {
    return (
      <Text size="sm" c="red" fw={600}>
        {a.text} <Anchor component={Link} to="/settings?q=safety.oncall_phones" size="xs">Configure</Anchor>
        {a.incident_id && <> · <Anchor component={Link} to={`/safety/incidents/${a.incident_id}`} size="xs" c="red">SOS #{a.incident_id}</Anchor></>}
      </Text>
    );
  }
  if (a.kind === 'pin_locked') {
    return (
      <Group gap={6} wrap="nowrap">
        <Badge size="xs" color="orange" leftSection={<FiLock size={9} />}>PIN locked</Badge>
        {a.ride_id ? <Anchor component={Link} to={`/rides/${a.ride_type}/${a.ride_id}`} size="sm" c="orange">{a.text}</Anchor> : <Text size="sm">{a.text}</Text>}
      </Group>
    );
  }
  if (a.kind === 'sos' || a.incident_id) return <Anchor component={Link} to={`/safety/incidents/${a.incident_id}`} size="sm" c="red">{a.text}</Anchor>;
  if (a.ride_id) return <Anchor component={Link} to={`/rides/${a.ride_type}/${a.ride_id}`} size="sm">{a.text}</Anchor>;
  return <Text size="sm">{a.text}</Text>;
}

function AlertsFeed() {
  const q = useQuery({ queryKey: ['alerts'], queryFn: () => http.get('/admin/alerts', { limit: 40 }), refetchInterval: 20000 });
  // Persisted PIN lockouts (audit `ride.pin_locked`) so they survive a reload.
  const pins = useQuery({
    queryKey: ['alerts', 'pin-locks'],
    queryFn: () => http.get('/admin/audit-logs', { action: 'ride.pin_locked', per_page: 10 }),
    refetchInterval: 60000,
    retry: false,
  });
  const [live, setLive] = useState([]);
  useRealtime('alert', (p) => setLive((l) => {
    const it = alertItem(p || {});
    if (l.some((x) => x._k === it._k)) return l;
    return [it, ...l].slice(0, 30);
  }));
  useRealtime('ride.stage_changed', (p) => setLive((l) => {
    if (l.some((x) => x._k === `e${p.event_id}`)) return l; // same event via several rooms
    return [{ kind: 'ride', severity: /CANCEL|NO_SHOW|EXPIRED/.test(p.to_stage) ? 'warning' : 'info', text: `${p.ride_type} #${p.ride_id}: ${p.from_stage} → ${p.to_stage}`, ride_type: p.ride_type, ride_id: p.ride_id, at: p.at, _k: `e${p.event_id}` }, ...l].slice(0, 30);
  }));
  const persistedPins = page(pins.data).items.map((r) => alertItem({
    kind: 'pin_locked', ride_type: r.entity_type, ride_id: r.entity_id, attempts: r.meta?.attempts, at: r.created_at,
  }));
  const seen = new Set();
  const items = [...live, ...persistedPins, ...(q.data || [])]
    .filter((a) => { if (!a._k) return true; if (seen.has(a._k)) return false; seen.add(a._k); return true; })
    .sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0))
    .slice(0, 60);
  return (
    <Card withBorder radius="md" padding="sm" h="100%">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Alerts feed</Text>
        {live.length > 0 && <Badge size="xs" color="green" variant="light">{live.length} live</Badge>}
      </Group>
      <ErrorBox error={q.error} />
      {!items.length && !q.isLoading && <Empty>No alerts.</Empty>}
      <ScrollArea h={320}>
        <Timeline bulletSize={14} lineWidth={2}>
          {items.map((a, i) => (
            <Timeline.Item key={a._k || `${a.kind}-${a.incident_id || a.ride_id}-${a.at}-${i}`} color={statusColor(a.severity)} title={<FeedTitle a={a} />}>
              <Text size="xs" c="dimmed">{ago(a.at)}</Text>
            </Timeline.Item>
          ))}
        </Timeline>
      </ScrollArea>
    </Card>
  );
}

export default function CommandCenter() {
  const { can } = useRoles();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ['command-center'], queryFn: () => http.get('/admin/command-center'), refetchInterval: 15000 });
  const d = q.data || {};
  const stages = Object.entries(d.active_rides_by_stage || {}).map(([stage, n]) => ({ stage: humanize(stage), n }));
  return (
    <>
      <PageHeader
        title="Command Center"
        subtitle={d.generated_at ? `Live · updated ${ago(d.generated_at)} · refreshes on every ride/SOS event and every 15 s` : 'Live KPIs'}
      />
      <ReadinessPanel />
      <ErrorBox error={q.error} />
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm" mb="sm">
        <StatCard label="Online drivers" value={d.online_drivers} icon={FiUsers} onClick={can('liveMap') ? () => nav('/live') : undefined} />
        <StatCard label="Active rides" value={d.active_rides} icon={FiNavigation} onClick={() => nav('/rides?active=1')} />
        <StatCard label="Rides today" value={d.rides_today} icon={FiActivity} />
        <StatCard label="GMV today" value={money(d.gmv_today_cents)} icon={FiDollarSign} hint="Captured ride payments (UTC day)" />
        <StatCard label="Completion rate" value={d.completion_rate === null || d.completion_rate === undefined ? '—' : `${Math.round(d.completion_rate * 100)}%`} icon={FiCheckCircle} hint={`${d.completed_today ?? 0} completed today`} />
        <StatCard label="Avg pickup time" value={d.avg_pickup_seconds ? duration(d.avg_pickup_seconds) : '—'} icon={FiClock} hint="Confirmed → driver arrived" />
        <StatCard label="Cancellations today" value={d.cancelled_today} icon={FiXCircle} color={d.cancelled_today ? 'orange' : undefined} />
        <StatCard label="Open SOS" value={d.open_sos} icon={FiAlertOctagon} color={d.open_sos ? 'red' : undefined} onClick={can('safety') ? () => nav('/safety') : undefined} />
      </SimpleGrid>
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, md: 7 }}>
          {can('liveMap') ? <MiniMap /> : (
            <Card withBorder radius="md" h="100%"><Empty>The live map needs the Ops or Safety role.</Empty></Card>
          )}
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <AlertsFeed />
        </Grid.Col>
        <Grid.Col span={12}>
          <Card withBorder radius="md" padding="sm">
            <Text fw={600} mb="xs">Active rides by stage</Text>
            {stages.length ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={stages} margin={{ left: -10, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="stage" tick={{ fontSize: 11 }} interval={0} angle={-15} textAnchor="end" height={50} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <RTooltip />
                  <Bar dataKey="n" name="Rides" fill="#ef9b11" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : <Empty>No active rides right now.</Empty>}
          </Card>
        </Grid.Col>
      </Grid>
      <Stack gap={0} mt="xs"><Text size="xs" c="dimmed">Times shown in your time zone. {d.generated_at && <>Server time: <Time value={d.generated_at} seconds /></>}</Text></Stack>
    </>
  );
}
