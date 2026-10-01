// Audit history of one user (GET /api/admin/users/{id}/history): rows about
// the user, by the user, and about their driver application, documents,
// background checks, safety incidents and support tickets. Viewing is audited.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Anchor, Badge, Chip, Group, Text } from '@mantine/core';
import { http, page } from '../lib/api';
import { humanize } from '../lib/format';
import { DataTable, Json, Time } from './ui';

const CATS = [
  { value: 'all', label: 'All' },
  { value: 'account', label: 'Account', types: ['user'] },
  { value: 'onboarding', label: 'Onboarding', types: ['driver_application', 'driver_document'] },
  { value: 'bgc', label: 'Background checks', types: ['background_check'] },
  { value: 'safety', label: 'Safety', types: ['safety_incident', 'recording'] },
  { value: 'support', label: 'Support', types: ['support_ticket'] },
  { value: 'rides', label: 'Rides & other', types: null },
];
const CAT_COLOR = { account: 'blue', onboarding: 'teal', bgc: 'grape', safety: 'red', support: 'orange', rides: 'gray' };
const KNOWN = new Set(CATS.flatMap((c) => c.types || []));

function catOf(r) {
  const t = r.entity_type;
  const c = CATS.find((x) => x.types && x.types.includes(t));
  return c ? c.value : 'rides';
}

function EntityLink({ r }) {
  const id = r.entity_id;
  const t = r.entity_type;
  if (!t) return <Text size="sm" c="dimmed">—</Text>;
  const to = {
    driver_application: `/onboarding/${id}`,
    safety_incident: `/safety/incidents/${id}`,
    support_ticket: `/support/${id}`,
    user: `/users/${id}`,
    carhire: `/rides/carhire/${id}`,
    scheduled: `/rides/scheduled/${id}`,
    rideshare_trip: `/rides/rideshare_trip/${id}`,
    rideshare_booking: `/rides/rideshare_booking/${id}`,
  }[t];
  const label = `${humanize(t)} #${id}`;
  return to ? <Anchor component={Link} to={to} size="sm">{label}</Anchor> : <Text size="sm">{label}</Text>;
}

function Change({ r }) {
  const before = r.before_json;
  const after = r.after_json;
  if (before && after && typeof before === 'object' && typeof after === 'object') {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]));
    if (keys.length && keys.length <= 6 && keys.every((k) => typeof after[k] !== 'object' && typeof before[k] !== 'object')) {
      return (
        <div>
          {keys.map((k) => <Text key={k} size="xs"><b>{humanize(k)}</b>: {String(before[k] ?? '—')} → {String(after[k] ?? '—')}</Text>)}
          {r.meta?.reason && <Text size="xs" c="dimmed">“{r.meta.reason}”</Text>}
        </div>
      );
    }
  }
  return <Json value={after || r.meta} maxH={90} />;
}

export default function UserHistory({ id }) {
  const [p, setP] = useState(1);
  const [cat, setCat] = useState('all');
  const q = useQuery({ queryKey: ['user-history', String(id), p], queryFn: () => http.get(`/admin/users/${id}/history`, { page: p, per_page: 50 }) });
  const pg = page(q.data);
  const rows = pg.items.filter((r) => cat === 'all' || catOf(r) === cat || (cat === 'rides' && !KNOWN.has(r.entity_type)));
  const counts = pg.items.reduce((m, r) => { const c = catOf(r); m[c] = (m[c] || 0) + 1; return m; }, {});
  return (
    <>
      <Group mb="xs" gap="xs">
        <Chip.Group value={cat} onChange={setCat}>
          {CATS.map((c) => (
            <Chip key={c.value} value={c.value} size="xs" color={CAT_COLOR[c.value] || 'dark'} data-testid={`hist-${c.value}`}>
              {c.label}{c.value !== 'all' && counts[c.value] ? ` (${counts[c.value]})` : ''}
            </Chip>
          ))}
        </Chip.Group>
        <Text size="xs" c="dimmed">Counts are for this page. Viewing this history is audited.</Text>
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={rows} pageInfo={pg} onPage={setP} empty={cat === 'all' ? 'No audit history.' : 'Nothing in this category on this page.'} minWidth={900}
        columns={[
          { key: 'created_at', label: 'When', render: (r) => <Time value={r.created_at} seconds /> },
          { key: 'cat', label: 'Area', render: (r) => <Badge size="xs" variant="light" color={CAT_COLOR[catOf(r)]}>{CATS.find((c) => c.value === catOf(r))?.label}</Badge> },
          { key: 'action', label: 'Action', render: (r) => <Text size="sm" ff="monospace">{r.action}</Text> },
          { key: 'actor', label: 'Actor', render: (r) => (r.actor_id ? <Anchor component={Link} to={`/users/${r.actor_id}`} size="sm">{r.actor_name || `#${r.actor_id}`}</Anchor> : null) || <Text size="sm">{r.actor_type}</Text> },
          { key: 'entity', label: 'Entity', render: (r) => <EntityLink r={r} /> },
          { key: 'change', label: 'Change', render: (r) => <Change r={r} /> },
        ]} />
    </>
  );
}
