import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Box, Card, Group, ScrollArea, SegmentedControl, Select, SimpleGrid, Table, Tabs, Text, TextInput,
} from '@mantine/core';
import {
  Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine,
} from 'recharts';
import { http } from '../lib/api';
import { humanize, money, pct, TZ } from '../lib/format';
import { useRoles } from '../lib/roles';
import MapView from '../components/map/MapView';
import { Empty, ErrorBox, Loading, PageHeader, StatCard } from '../components/ui';

function heatColor(t) {
  // yellow → orange → red
  const h = 50 - 50 * Math.min(1, Math.max(0, t));
  return `hsl(${h}, 95%, 50%)`;
}

function Demand({ range }) {
  const [cell, setCell] = useState('0.01');
  const q = useQuery({ queryKey: ['reports', 'heatmap', range, cell], queryFn: () => http.get('/admin/reports/demand-heatmap', { ...range, cell_deg: cell }) });
  const cells = q.data?.cells || [];
  const radius = Number(cell) * 111000 / 2;
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm">{q.data?.total_requests ?? 0} ride requests in {cells.length} cells (pickup points, anonymised to grid centres)</Text>
        <SegmentedControl size="xs" value={cell} onChange={setCell} data={[{ value: '0.005', label: '~500 m' }, { value: '0.01', label: '~1 km' }, { value: '0.05', label: '~5 km' }]} />
      </Group>
      <ErrorBox error={q.error} />
      <MapView height={520}
        circles={cells.map((c, i) => ({ id: `c${i}`, lat: c.lat, lng: c.lng, radiusM: radius, color: heatColor(c.intensity), fillOpacity: 0.25 + 0.5 * c.intensity, label: `${c.count} requests` }))}
        fitKey={cells.length ? `${range.from}-${range.to}-${cell}-${cells.length}` : undefined} />
      {!cells.length && !q.isLoading && <Text size="sm" c="dimmed">No requests with coordinates in this period.</Text>}
    </Stack>
  );
}

function Stack({ children }) { return <Box style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>{children}</Box>; }

function SupplyDemand({ range }) {
  const q = useQuery({ queryKey: ['reports', 'supply', range], queryFn: () => http.get('/admin/reports/supply-demand', { ...range, tz: TZ }) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  return (
    <Stack>
      <Card withBorder radius="md" padding="sm">
        <Text fw={600} mb="xs">Average by hour of day ({d.timezone})</Text>
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={d.by_hour_of_day}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="hour_of_day" tickFormatter={(h) => `${h}h`} />
            <YAxis yAxisId="l" allowDecimals />
            <YAxis yAxisId="r" orientation="right" />
            <Tooltip />
            <Legend />
            <Bar yAxisId="l" dataKey="avg_requests" name="Avg requests / hour" fill="#ef9b11" />
            <Line yAxisId="r" dataKey="avg_online_drivers" name="Avg online drivers" stroke="#1c7ed6" strokeWidth={2} dot={false} connectNulls />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>
      <Card withBorder radius="md" padding="sm">
        <Text fw={600} mb="xs">Hourly series · {d.totals?.requests ?? 0} requests</Text>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={d.series}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="hour" tickFormatter={(h) => new Date(h).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} minTickGap={40} />
            <YAxis />
            <Tooltip labelFormatter={(h) => new Date(h).toLocaleString()} />
            <Legend />
            <Line dataKey="requests" name="Requests" stroke="#ef9b11" dot={false} />
            <Line dataKey="online_drivers" name="Online drivers" stroke="#1c7ed6" dot={false} connectNulls />
            <Line dataKey="engaged_drivers" name="Engaged drivers" stroke="#37b24d" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </Card>
    </Stack>
  );
}

function Negotiations({ range }) {
  const q = useQuery({ queryKey: ['reports', 'nego', range], queryFn: () => http.get('/admin/reports/negotiations', range) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm">
        <StatCard label="Negotiations" value={d.negotiations} />
        <StatCard label="Acceptance rate" value={pct(d.acceptance_rate_pct)} hint={`${d.agreed} agreed`} />
        <StatCard label="Avg discount vs driver ask" value={pct(d.avg_discount_from_driver_initial_ask_pct)} hint={`${d.agreed_with_driver_ask} with a driver ask`} />
        <StatCard label="Agreed vs customer offer" value={pct(d.avg_change_vs_customer_offer_pct)} />
        <StatCard label="Avg rounds" value={d.avg_rounds ?? '—'} />
        <StatCard label="Avg rounds (agreed)" value={d.avg_rounds_when_agreed ?? '—'} />
      </SimpleGrid>
      <Card withBorder radius="md" padding="sm">
        <Text fw={600} mb="xs">Outcomes by stage</Text>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={Object.entries(d.by_stage || {}).map(([k, v]) => ({ stage: humanize(k), n: v }))}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="stage" tick={{ fontSize: 10 }} angle={-20} textAnchor="end" height={60} interval={0} />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="n" name="Negotiations" fill="#7048e8" />
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </Stack>
  );
}

function Cohorts({ range }) {
  const [weeks, setWeeks] = useState('8');
  const q = useQuery({ queryKey: ['reports', 'cohorts', range, weeks], queryFn: () => http.get('/admin/reports/cohorts', { ...range, weeks }) });
  return (
    <Card withBorder radius="md" padding="sm">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Weekly sign-up cohorts — % with a completed ride in week N</Text>
        <Select size="xs" value={weeks} onChange={(v) => setWeeks(v)} data={['4', '8', '12', '26']} w={90} allowDeselect={false} />
      </Group>
      <ErrorBox error={q.error} />
      {q.isLoading ? <Loading /> : !(q.data?.cohorts || []).length ? <Empty>No sign-ups in this range.</Empty> : (
        <ScrollArea>
          <Table withTableBorder withColumnBorders fz="xs" miw={600}>
            <Table.Thead><Table.Tr><Table.Th>Cohort (week of)</Table.Th><Table.Th>Users</Table.Th>{Array.from({ length: q.data.weeks }).map((_, i) => <Table.Th key={i}>W{i}</Table.Th>)}</Table.Tr></Table.Thead>
            <Table.Tbody>
              {q.data.cohorts.map((c) => (
                <Table.Tr key={c.cohort_week}>
                  <Table.Td>{c.cohort_week}</Table.Td><Table.Td>{c.users}</Table.Td>
                  {c.weeks.map((w) => (
                    <Table.Td key={w.week} style={{ background: w.pct ? `rgba(239,155,17,${Math.min(0.9, 0.12 + w.pct / 60)})` : undefined }} title={`${w.active_users} users`}>
                      {w.pct ? `${w.pct}%` : ''}
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
    </Card>
  );
}

function Earnings({ range }) {
  const q = useQuery({ queryKey: ['reports', 'earnings', range], queryFn: () => http.get('/admin/reports/earnings-distribution', range) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, md: 3, lg: 5 }} spacing="sm">
        <StatCard label="Earning drivers" value={d.drivers} />
        <StatCard label="Total paid out" value={money(d.total_cents)} />
        <StatCard label="Mean" value={money(d.mean_cents)} />
        <StatCard label="Median (p50)" value={money(d.p50_cents)} />
        <StatCard label="p90" value={money(d.p90_cents)} />
      </SimpleGrid>
      <Card withBorder radius="md" padding="sm">
        <Text fw={600} mb="xs">Drivers by earnings bucket ({money(d.bucket_cents)} wide)</Text>
        {d.histogram.length ? (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={d.histogram.map((h) => ({ ...h, label: `${money(h.from_cents)}–${money(h.to_cents)}` }))}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} angle={-25} textAnchor="end" height={70} interval={0} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="drivers" name="Drivers" fill="#37b24d" />
            </BarChart>
          </ResponsiveContainer>
        ) : <Empty>No driver earnings in this period.</Empty>}
      </Card>
    </Stack>
  );
}

function Latency() {
  const [days, setDays] = useState('7');
  const q = useQuery({ queryKey: ['reports', 'latency', days], queryFn: () => http.get('/admin/analytics/latency', { name: 'autocomplete_latency_ms', days }) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  const ms = (v) => (v === null || v === undefined ? '—' : `${Math.round(v)} ms`);
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm">Address autocomplete latency, measured in the apps (target p95 ≤ {d.target_p95_ms} ms)</Text>
        <SegmentedControl size="xs" value={days} onChange={setDays} data={['1', '7', '30'].map((v) => ({ value: v, label: `${v} d` }))} />
      </Group>
      <SimpleGrid cols={{ base: 2, md: 3, lg: 5 }} spacing="sm">
        <StatCard label="Samples" value={d.count} />
        <StatCard label="p50" value={ms(d.p50)} />
        <StatCard label="p95" value={ms(d.p95)} color={d.p95 && d.p95 > d.target_p95_ms ? 'red' : 'green'} />
        <StatCard label="p99" value={ms(d.p99)} />
        <StatCard label="Average" value={ms(d.avg)} />
      </SimpleGrid>
      <Card withBorder radius="md" padding="sm">
        <Text fw={600} mb="xs">Daily average</Text>
        {d.daily.length ? (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={d.daily}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="date" />
              <YAxis unit=" ms" />
              <Tooltip />
              <ReferenceLine y={d.target_p95_ms} stroke="#fa5252" strokeDasharray="4 4" label={{ value: 'p95 target', fontSize: 10 }} />
              <Line dataKey="avg" name="Avg ms" stroke="#1c7ed6" />
            </LineChart>
          </ResponsiveContainer>
        ) : <Empty>No latency samples yet.</Empty>}
      </Card>
    </Stack>
  );
}

export default function Reports() {
  const { can } = useRoles();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const range = { from: from || undefined, to: to || undefined };
  return (
    <>
      <PageHeader title="Reports & Analytics" subtitle="Defaults: last 7–84 days depending on the report · dates are UTC"
        actions={<>
          <TextInput size="xs" type="date" label="From" value={from} onChange={(e) => setFrom(e.currentTarget.value)} />
          <TextInput size="xs" type="date" label="To" value={to} onChange={(e) => setTo(e.currentTarget.value)} />
        </>} />
      <Tabs defaultValue="demand" keepMounted={false}>
        <Tabs.List mb="sm" style={{ flexWrap: 'wrap' }}>
          <Tabs.Tab value="demand">Demand heatmap</Tabs.Tab>
          <Tabs.Tab value="supply">Supply vs demand</Tabs.Tab>
          <Tabs.Tab value="nego">Negotiations</Tabs.Tab>
          <Tabs.Tab value="cohorts">Cohort retention</Tabs.Tab>
          {can('earningsReport') && <Tabs.Tab value="earnings">Driver earnings</Tabs.Tab>}
          <Tabs.Tab value="latency">Autocomplete latency</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="demand"><Demand range={range} /></Tabs.Panel>
        <Tabs.Panel value="supply"><SupplyDemand range={range} /></Tabs.Panel>
        <Tabs.Panel value="nego"><Negotiations range={range} /></Tabs.Panel>
        <Tabs.Panel value="cohorts"><Cohorts range={range} /></Tabs.Panel>
        {can('earningsReport') && <Tabs.Panel value="earnings"><Earnings range={range} /></Tabs.Panel>}
        <Tabs.Panel value="latency"><Latency /></Tabs.Panel>
      </Tabs>
    </>
  );
}
