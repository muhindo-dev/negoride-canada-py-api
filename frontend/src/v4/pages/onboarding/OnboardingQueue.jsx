import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Badge, Card, Grid, Group, MultiSelect, Select, SimpleGrid, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { http, page } from '../../lib/api';
import { humanize } from '../../lib/format';
import { DataTable, ErrorBox, PageHeader, StatCard, StatusBadge, Time } from '../../components/ui';

export const STEPS = ['account_created', 'phone_verified', 'email_verified', 'profile_completed', 'documents_submitted', 'background_check', 'payout_ready', 'review', 'orientation'];
const STATUSES = ['in_progress', 'submitted', 'under_review', 'needs_changes', 'approved', 'rejected'];

function Funnel() {
  const q = useQuery({ queryKey: ['onboarding', 'funnel'], queryFn: () => http.get('/admin/onboarding/funnel') });
  const d = q.data;
  return (
    <Card withBorder radius="md" padding="sm">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Onboarding funnel</Text>
        <Text size="xs" c="dimmed">{d?.total_applications ?? 0} applications</Text>
      </Group>
      <ErrorBox error={q.error} />
      {d && (
        <>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={d.steps.map((s) => ({ ...s, label: s.title }))} margin={{ left: -15 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={60} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v, n, p) => (n === 'Completed' ? [`${v} (drop-off ${p.payload.drop_off_pct}%)`, n] : [v, n])} />
              <Legend />
              <Bar dataKey="completed" name="Completed" fill="#ef9b11" radius={[4, 4, 0, 0]} />
              <Bar dataKey="currently_at" name="Currently here" fill="#1c7ed6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <Group gap={6} mt={4}>
            {Object.entries(d.by_status || {}).map(([k, v]) => <Badge key={k} variant="light" color="gray">{humanize(k)}: {v}</Badge>)}
          </Group>
        </>
      )}
    </Card>
  );
}

export default function OnboardingQueue() {
  const nav = useNavigate();
  const [status, setStatus] = useState(['submitted', 'under_review']);
  const [step, setStep] = useState('');
  const [search, setSearch] = useState('');
  const [dq] = useDebouncedValue(search, 350);
  const [p, setP] = useState(1);
  const params = { status: status.join(','), step, q: dq, page: p };
  const q = useQuery({ queryKey: ['onboarding', 'apps', params], queryFn: () => http.get('/admin/onboarding/applications', params) });
  const pg = page(q.data);
  return (
    <>
      <PageHeader title="Driver Onboarding" subtitle="Review queue (oldest submission first) · documents, Certn background checks, decisions" />
      <Grid gutter="sm" mb="sm">
        <Grid.Col span={{ base: 12, lg: 8 }}><Funnel /></Grid.Col>
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <SimpleGrid cols={2} spacing="sm">
            <StatCard label="In this queue" value={pg.total} />
            <StatCard label="Docs pending (page)" value={pg.items.reduce((s, a) => s + (a.documents_pending || 0), 0)} />
          </SimpleGrid>
        </Grid.Col>
      </Grid>
      <Group mb="sm" gap="xs" wrap="wrap">
        <MultiSelect size="xs" placeholder="Any status" data={STATUSES.map((s) => ({ value: s, label: humanize(s) }))} value={status} onChange={(v) => { setStatus(v); setP(1); }} clearable w={320} />
        <Select size="xs" placeholder="Any step" data={STEPS.map((s) => ({ value: s, label: humanize(s) }))} value={step} onChange={(v) => { setStep(v || ''); setP(1); }} clearable w={200} />
        <TextInput size="xs" placeholder="Name, email or phone" value={search} onChange={(e) => { setSearch(e.currentTarget.value); setP(1); }} w={220} />
      </Group>
      <DataTable
        loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} onRowClick={(a) => nav(`/onboarding/${a.id}`)}
        empty="No applications match."
        columns={[
          { key: 'id', label: '#' },
          { key: 'user', label: 'Applicant', render: (a) => <div><Text size="sm" fw={500}>{a.user?.name || `#${a.user_id}`}</Text><Text size="xs" c="dimmed">{a.user?.email || a.user?.phone}</Text></div> },
          { key: 'status', label: 'Status', render: (a) => <StatusBadge value={a.status} /> },
          { key: 'current_step', label: 'Step', render: (a) => humanize(a.current_step) },
          { key: 'bgc', label: 'Certn', render: (a) => <StatusBadge value={a.background_check_status} /> },
          { key: 'docs', label: 'Docs pending', render: (a) => (a.documents_pending ? <Badge color="yellow">{a.documents_pending}</Badge> : '0') },
          { key: 'province', label: 'Prov.', render: (a) => a.province || '—' },
          { key: 'submitted_at', label: 'Submitted', render: (a) => <Time value={a.submitted_at} relative /> },
        ]}
      />
    </>
  );
}
