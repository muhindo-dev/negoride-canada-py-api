import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Drawer, Grid, Group, NumberInput, Stack, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { http, page } from '../lib/api';
import { DataTable, Json, KV, PageHeader, Time, UserLink } from '../components/ui';
import { fmt } from '../lib/format';

export default function AuditLog() {
  const [f, setF] = useState({ action: '', entity_type: '', entity_id: '', actor_id: '' });
  const [df] = useDebouncedValue(f, 350);
  const [p, setP] = useState(1);
  const [sel, setSel] = useState(null);
  const params = { ...df, page: p, per_page: 50 };
  const q = useQuery({ queryKey: ['audit', params], queryFn: () => http.get('/admin/audit-logs', params) });
  const pg = page(q.data);
  const set = (k) => (v) => { setF({ ...f, [k]: v }); setP(1); };
  return (
    <>
      <PageHeader title="Audit log" subtitle="Every admin action, safety event and access to personal data (PIPEDA)" />
      <Group mb="sm" gap="xs" wrap="wrap">
        <TextInput size="xs" label="Action prefix" placeholder="e.g. safety. or ride.admin" value={f.action} onChange={(e) => set('action')(e.currentTarget.value)} w={200} />
        <TextInput size="xs" label="Entity type" placeholder="user, ride, safety_incident…" value={f.entity_type} onChange={(e) => set('entity_type')(e.currentTarget.value)} w={180} />
        <TextInput size="xs" label="Entity ID" value={f.entity_id} onChange={(e) => set('entity_id')(e.currentTarget.value)} w={110} />
        <NumberInput size="xs" label="Actor ID" value={f.actor_id} onChange={(v) => set('actor_id')(v ? String(v) : '')} w={100} hideControls />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} onRowClick={setSel} minWidth={900} empty="No audit entries."
        columns={[
          { key: 'created_at', label: 'When', render: (r) => <Time value={r.created_at} seconds /> },
          { key: 'action', label: 'Action', render: (r) => <Text size="sm" ff="monospace">{r.action}</Text> },
          { key: 'actor', label: 'Actor', render: (r) => (r.actor_id ? <UserLink id={r.actor_id} name={`${r.actor_name || ''} #${r.actor_id}`} /> : r.actor_type) },
          { key: 'actor_type', label: 'Type' },
          { key: 'entity', label: 'Entity', render: (r) => <Text size="sm">{r.entity_type} {r.entity_id}</Text> },
          { key: 'ip', label: 'IP', render: (r) => <Text size="xs" c="dimmed">{r.ip}</Text> },
        ]} />
      <Drawer opened={!!sel} onClose={() => setSel(null)} position="right" size="lg" title={sel ? `Audit #${sel.id}` : ''}>
        {sel && (
          <Stack>
            <KV items={[['Action', sel.action], ['When', fmt.dateTimeSec(sel.created_at)], ['Actor', `${sel.actor_type} #${sel.actor_id ?? '—'} ${sel.actor_name || ''}`], ['Entity', `${sel.entity_type} ${sel.entity_id}`], ['IP', sel.ip], ['User agent', sel.user_agent]]} />
            <Grid>
              <Grid.Col span={6}><Text size="xs" c="dimmed">Before</Text><Json value={sel.before_json} maxH={400} /></Grid.Col>
              <Grid.Col span={6}><Text size="xs" c="dimmed">After</Text><Json value={sel.after_json} maxH={400} /></Grid.Col>
            </Grid>
            <Text size="xs" c="dimmed">Meta</Text><Json value={sel.meta} />
          </Stack>
        )}
      </Drawer>
    </>
  );
}
