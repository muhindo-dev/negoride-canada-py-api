import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge, Button, Card, Grid, Group, NumberInput, Pagination, Select, Switch, Tabs, Text, TextInput } from '@mantine/core';
import { http } from '../lib/api';
import { money } from '../lib/format';
import { DataTable, notifyOk, PageHeader, ReasonModal, RideLink, Time, UserLink } from '../components/ui';

function Explorer() {
  const qc = useQueryClient();
  const [f, setF] = useState({ role: '', max_stars: '', ratee_id: '', tag: '', hidden: '', has_comment: false, from: '', to: '' });
  const [p, setP] = useState(1);
  const [target, setTarget] = useState(null);
  const params = { ...f, has_comment: f.has_comment ? 1 : undefined, page: p, per_page: 25 };
  const q = useQuery({ queryKey: ['ratings', 'explorer', params], queryFn: () => http.get('/admin/ratings', params) });
  const set = (k) => (v) => { setF({ ...f, [k]: v ?? '' }); setP(1); };
  const last = Math.max(1, Math.ceil((q.data?.total || 0) / 25));
  return (
    <>
      <Group mb="sm" gap="xs" wrap="wrap" align="flex-end">
        <Select size="xs" label="Rated by" clearable value={f.role} onChange={set('role')} data={[{ value: 'customer', label: 'Customer → driver' }, { value: 'driver', label: 'Driver → customer' }]} w={170} />
        <Select size="xs" label="Max stars" clearable value={f.max_stars} onChange={set('max_stars')} data={['1', '2', '3', '4', '5']} w={100} />
        <NumberInput size="xs" label="Ratee ID" value={f.ratee_id} onChange={(v) => set('ratee_id')(v ? String(v) : '')} w={100} hideControls />
        <TextInput size="xs" label="Tag" value={f.tag} onChange={(e) => set('tag')(e.currentTarget.value)} w={130} placeholder="e.g. unsafe_driving" />
        <Select size="xs" label="Visibility" clearable value={f.hidden} onChange={set('hidden')} data={[{ value: '0', label: 'Visible' }, { value: '1', label: 'Hidden' }]} w={110} />
        <TextInput size="xs" type="date" label="From" value={f.from} onChange={(e) => set('from')(e.currentTarget.value)} />
        <TextInput size="xs" type="date" label="To" value={f.to} onChange={(e) => set('to')(e.currentTarget.value)} />
        <Switch size="xs" label="With comment" checked={f.has_comment} onChange={(e) => set('has_comment')(e.currentTarget.checked)} />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={q.data?.items || []} minWidth={1050} empty="No ratings match."
        highlight={(r) => r.hidden_by_admin}
        columns={[
          { key: 'stars', label: 'Stars', render: (r) => <Text c={r.stars <= 2 ? 'red' : 'orange'}>{'★'.repeat(r.stars)}{'☆'.repeat(5 - r.stars)}</Text> },
          { key: 'rater', label: 'From', render: (r) => <UserLink id={r.rater_id} name={`${r.rater?.name || '#' + r.rater_id} (${r.role})`} /> },
          { key: 'ratee', label: 'About', render: (r) => <UserLink id={r.ratee_id} name={r.ratee?.name} /> },
          { key: 'ride', label: 'Ride', render: (r) => <RideLink type={r.ride_type} id={r.ride_id} /> },
          { key: 'tags', label: 'Tags', render: (r) => <Group gap={2}>{(r.tags || []).map((t) => <Badge key={t} size="xs" variant="light">{t}</Badge>)}</Group> },
          { key: 'comment', label: 'Comment', render: (r) => <Text size="xs" lineClamp={2} maw={240}>{r.comment}</Text> },
          { key: 'tip', label: 'Tip', render: (r) => (r.tip_cents ? money(r.tip_cents) : '') },
          { key: 'created_at', label: 'When', render: (r) => <Time value={r.created_at} /> },
          { key: 'x', label: '', render: (r) => (
            <Button size="compact-xs" variant="light" color={r.hidden_by_admin ? 'green' : 'gray'} onClick={() => setTarget(r)}>
              {r.hidden_by_admin ? 'Unhide' : 'Hide'}
            </Button>
          ) },
        ]} />
      {last > 1 && <Group justify="flex-end" mt="xs"><Pagination size="sm" total={last} value={p} onChange={setP} /></Group>}
      <ReasonModal
        opened={!!target} onClose={() => setTarget(null)} title={target?.hidden_by_admin ? 'Restore rating' : 'Hide rating (abusive / discriminatory)'}
        confirmLabel={target?.hidden_by_admin ? 'Unhide' : 'Hide'} color={target?.hidden_by_admin ? 'green' : 'red'}
        description={target && <Text size="sm">{'★'.repeat(target.stars)} — “{target.comment || 'no comment'}”. The driver’s score is recomputed.{target.hidden_reason ? ` Hidden because: ${target.hidden_reason}` : ''}</Text>}
        onSubmit={async (reason) => {
          const r = await http.post(`/admin/ratings/${target.id}/${target.hidden_by_admin ? 'unhide' : 'hide'}`, { reason });
          notifyOk(`Rating ${target.hidden_by_admin ? 'restored' : 'hidden'} · new score ${r?.ratee_score?.rating ?? r?.ratee_score ?? '—'}`);
          qc.invalidateQueries({ queryKey: ['ratings'] });
        }}
      />
    </>
  );
}

function Alerts() {
  const [minCount, setMinCount] = useState(10);
  const low = useQuery({ queryKey: ['ratings', 'lowest', minCount], queryFn: () => http.get('/admin/ratings/lowest-drivers', { min_count: minCount, limit: 50 }) });
  const trend = useQuery({ queryKey: ['ratings', 'trend'], queryFn: () => http.get('/admin/ratings/trend-alerts') });
  return (
    <Grid gutter="sm">
      <Grid.Col span={{ base: 12, lg: 6 }}>
        <Card withBorder radius="md" padding="sm">
          <Group justify="space-between" mb="xs">
            <Text fw={600}>Lowest-rated drivers</Text>
            <NumberInput size="xs" label="Min ratings" value={minCount} onChange={(v) => setMinCount(Number(v) || 1)} w={110} min={1} />
          </Group>
          <DataTable loading={low.isLoading} error={low.error} rows={low.data?.drivers || []} rowKey="driver_id" minWidth={420} empty="No drivers with enough ratings."
            columns={[
              { key: 'name', label: 'Driver', render: (d) => <UserLink id={d.driver_id} name={d.name} /> },
              { key: 'avg', label: 'Avg', render: (d) => <Text c={d.avg_stars < 4 ? 'red' : d.avg_stars < 4.3 ? 'orange' : undefined} fw={600}>{d.avg_stars.toFixed(2)}</Text> },
              { key: 'ratings', label: 'Ratings' },
              { key: 'score', label: 'Score', render: (d) => (d.score ? d.score.toFixed(2) : '—') },
            ]} />
        </Card>
      </Grid.Col>
      <Grid.Col span={{ base: 12, lg: 6 }}>
        <Card withBorder radius="md" padding="sm">
          <Text fw={600} mb="xs">Trend alerts — last 7 days vs the 28 before</Text>
          <DataTable loading={trend.isLoading} error={trend.error} rows={trend.data?.alerts || []} rowKey="driver_id" minWidth={420} empty="No drivers with a significant drop."
            columns={[
              { key: 'name', label: 'Driver', render: (d) => <UserLink id={d.driver_id} name={d.name} /> },
              { key: 'prior', label: 'Before', render: (d) => `${d.prior_avg} (${d.prior_count})` },
              { key: 'recent', label: 'Last 7 d', render: (d) => `${d.recent_avg} (${d.recent_count})` },
              { key: 'drop', label: 'Drop', render: (d) => <Badge color="red">−{d.drop}</Badge> },
            ]} />
        </Card>
      </Grid.Col>
    </Grid>
  );
}

export default function Ratings() {
  return (
    <>
      <PageHeader title="Ratings" subtitle="Explorer, low-rating alerts, and hiding abusive ratings (audited, score recomputed)" />
      <Tabs defaultValue="explorer" keepMounted={false}>
        <Tabs.List mb="sm"><Tabs.Tab value="explorer">Explorer</Tabs.Tab><Tabs.Tab value="alerts">Low-rating alerts</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="explorer"><Explorer /></Tabs.Panel>
        <Tabs.Panel value="alerts"><Alerts /></Tabs.Panel>
      </Tabs>
    </>
  );
}
