import React, { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Badge, Group, MultiSelect, NumberInput, Switch, Text, TextInput } from '@mantine/core';
import { http, page } from '../../lib/api';
import { RIDE_TYPES } from '../../lib/format';
import { useRealtime } from '../../lib/realtime';
import { DataTable, Money, PageHeader, StageBadge, Time, UserLink } from '../../components/ui';

export const ALL_STAGES = [
  'REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT', 'PENDING_PAYMENT', 'CONFIRMED', 'DRAFT', 'PUBLISHED',
  'BOARDING', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING', 'DRIVER_ARRIVED', 'CHECKED_IN', 'IN_PROGRESS', 'RIDING',
  'COMPLETED', 'DROPPED_OFF', 'CLOSED', 'EXPIRED', 'DECLINED', 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER',
  'CUSTOMER_NO_SHOW', 'DRIVER_NO_SHOW', 'NO_SHOW',
];

export default function RidesList() {
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [types, setTypes] = useState(sp.get('type') ? sp.get('type').split(',') : []);
  const [stages, setStages] = useState(sp.get('stage') ? sp.get('stage').split(',') : []);
  const [active, setActive] = useState(sp.get('active') === '1');
  const [disputed, setDisputed] = useState(sp.get('disputed') === '1');
  const [userId, setUserId] = useState(sp.get('user_id') || '');
  const [since, setSince] = useState(sp.get('since') || '');
  const [p, setP] = useState(1);
  const params = {
    type: types.join(','), stage: stages.join(','), active: active ? 1 : undefined, disputed: disputed ? 1 : undefined,
    user_id: userId || undefined, since: since || undefined, page: p, per_page: 25,
  };
  const q = useQuery({ queryKey: ['rides', params], queryFn: () => http.get('/admin/rides', params), refetchInterval: 30000 });
  useRealtime('ride.stage_changed', () => q.refetch());
  const pg = page(q.data);
  const sync = (patch) => {
    const next = { type: types.join(','), stage: stages.join(','), active: active ? '1' : '', disputed: disputed ? '1' : '', user_id: userId, since, ...patch };
    setSp(Object.fromEntries(Object.entries(next).filter(([, v]) => v)));
    setP(1);
  };
  return (
    <>
      <PageHeader title="Rides" subtitle="Car Hire, Scheduled and Rideshare in one list · live-updates on stage changes" />
      <Group mb="sm" gap="xs" align="flex-end" wrap="wrap">
        <MultiSelect size="xs" label="Type" placeholder="All types" data={Object.entries(RIDE_TYPES).map(([value, label]) => ({ value, label }))} value={types}
          onChange={(v) => { setTypes(v); sync({ type: v.join(',') }); }} w={260} clearable />
        <MultiSelect size="xs" label="Stage" placeholder="Any stage" data={ALL_STAGES} value={stages} searchable
          onChange={(v) => { setStages(v); sync({ stage: v.join(',') }); }} w={280} clearable />
        <NumberInput size="xs" label="User ID" value={userId} onChange={(v) => { setUserId(v ? String(v) : ''); sync({ user_id: v ? String(v) : '' }); }} w={110} hideControls />
        <TextInput size="xs" type="date" label="Created since" value={since} onChange={(e) => { setSince(e.currentTarget.value); sync({ since: e.currentTarget.value }); }} w={150} />
        <Switch size="xs" label="Active only" checked={active} onChange={(e) => { setActive(e.currentTarget.checked); sync({ active: e.currentTarget.checked ? '1' : '' }); }} />
        <Switch size="xs" label="Disputed" checked={disputed} onChange={(e) => { setDisputed(e.currentTarget.checked); sync({ disputed: e.currentTarget.checked ? '1' : '' }); }} />
      </Group>
      <DataTable
        loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} rowKey="_k" minWidth={980}
        onRowClick={(r) => nav(`/rides/${r.ride_type}/${r.id}`)}
        empty="No rides match these filters."
        columns={[
          { key: 'id', label: 'Ride', render: (r) => <Text size="sm" fw={600}>{RIDE_TYPES[r.ride_type]} #{r.id}</Text> },
          { key: 'stage', label: 'Stage', render: (r) => <Group gap={4}><StageBadge stage={r.stage} />{r.disputed && <Badge color="red" size="xs">disputed</Badge>}</Group> },
          { key: 'route', label: 'Route', render: (r) => <Text size="xs" lineClamp={2} maw={320}>{r.pickup || '—'} → {r.dropoff || '—'}</Text> },
          { key: 'customer', label: 'Customer', render: (r) => (r.customer_ids?.length ? <UserLink id={r.customer_ids[0]} name={r.customer_name} /> : '—') },
          { key: 'driver', label: 'Driver', render: (r) => <UserLink id={r.driver_id} name={r.driver_name} /> },
          { key: 'fare', label: 'Fare', align: 'right', render: (r) => <Money cents={r.fare_cents} size="sm" /> },
          { key: 'created_at', label: 'Created', render: (r) => <Time value={r.created_at} /> },
          { key: 'changed', label: 'Stage changed', render: (r) => <Time value={r.stage_changed_at} relative /> },
        ]}
      />
    </>
  );
}
