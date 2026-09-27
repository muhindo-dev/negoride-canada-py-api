import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Badge, Group, MultiSelect, Select, SimpleGrid, Switch, Text } from '@mantine/core';
import { http, page } from '../../lib/api';
import { duration, humanize, parseTs } from '../../lib/format';
import { DataTable, PageHeader, StatCard, StatusBadge, Time, UserLink } from '../../components/ui';

export function SlaTimer({ sla, status }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  if (!sla) return '—';
  if (sla.first_response_at) {
    return <Badge size="sm" variant="light" color={sla.breached ? 'orange' : 'green'}>{sla.breached ? 'Responded late' : 'Responded'}</Badge>;
  }
  if (['resolved', 'closed'].includes(status)) return <Badge size="sm" variant="light" color="gray">closed</Badge>;
  const due = parseTs(sla.due_at);
  if (!due) return '—';
  const left = Math.round((due.getTime() - Date.now()) / 1000);
  return (
    <Badge size="sm" color={left < 0 ? 'red' : left < 3600 ? 'orange' : 'blue'} variant={left < 0 ? 'filled' : 'light'} data-testid="sla-timer">
      {left < 0 ? `Overdue ${duration(-left)}` : `${duration(left)} left`}
    </Badge>
  );
}

export default function SupportQueue() {
  const nav = useNavigate();
  const [status, setStatus] = useState(['open', 'pending']);
  const [type, setType] = useState('');
  const [priority, setPriority] = useState('');
  const [assigned, setAssigned] = useState('');
  const [overdue, setOverdue] = useState(false);
  const [p, setP] = useState(1);
  const params = { status: status.join(','), type, priority, assigned_to: assigned, overdue: overdue ? 1 : undefined, page: p };
  const q = useQuery({ queryKey: ['support', params], queryFn: () => http.get('/admin/support/tickets', params), refetchInterval: 30000 });
  const pg = page(q.data);
  const counts = q.data?.counts || {};
  return (
    <>
      <PageHeader title="Disputes & Support" subtitle="Tickets, trip disputes and account appeals · sorted by SLA due time" />
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm" mb="sm">
        {['open', 'pending', 'resolved', 'closed'].map((s) => <StatCard key={s} label={humanize(s)} value={counts[s] ?? 0} onClick={() => { setStatus([s]); setP(1); }} />)}
      </SimpleGrid>
      <Group mb="sm" gap="xs" wrap="wrap">
        <MultiSelect size="xs" placeholder="Any status" data={['open', 'pending', 'resolved', 'closed']} value={status} onChange={(v) => { setStatus(v); setP(1); }} clearable w={260} />
        <Select size="xs" placeholder="Any type" clearable value={type} onChange={(v) => { setType(v || ''); setP(1); }} data={['general', 'appeal', 'dispute', 'lost_item', 'safety', 'billing'].map((x) => ({ value: x, label: humanize(x) }))} w={150} />
        <Select size="xs" placeholder="Any priority" clearable value={priority} onChange={(v) => { setPriority(v || ''); setP(1); }} data={['urgent', 'high', 'normal', 'low']} w={140} />
        <Select size="xs" placeholder="Anyone" clearable value={assigned} onChange={(v) => { setAssigned(v || ''); setP(1); }} data={[{ value: 'me', label: 'Assigned to me' }, { value: 'none', label: 'Unassigned' }]} w={160} />
        <Switch size="xs" label="SLA overdue" checked={overdue} onChange={(e) => { setOverdue(e.currentTarget.checked); setP(1); }} />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={1000} onRowClick={(t) => nav(`/support/${t.id}`)}
        highlight={(t) => t.sla?.breached && !t.sla?.first_response_at && ['open', 'pending'].includes(t.status)}
        empty="No tickets."
        columns={[
          { key: 'id', label: '#' },
          { key: 'type', label: 'Type', render: (t) => <Badge variant="light" color={t.type === 'appeal' ? 'grape' : t.type === 'dispute' ? 'orange' : t.type === 'safety' ? 'red' : 'gray'}>{humanize(t.type)}</Badge> },
          { key: 'subject', label: 'Subject', render: (t) => <Text size="sm" lineClamp={1} maw={300}>{t.subject}</Text> },
          { key: 'user', label: 'User', render: (t) => <UserLink id={t.user_id} name={t.user?.name} /> },
          { key: 'priority', label: 'Priority', render: (t) => <StatusBadge value={t.priority} /> },
          { key: 'status', label: 'Status', render: (t) => <StatusBadge value={t.status} /> },
          { key: 'sla', label: 'SLA', render: (t) => <SlaTimer sla={t.sla} status={t.status} /> },
          { key: 'assigned', label: 'Assignee', render: (t) => (t.assigned_to ? `#${t.assigned_to}` : <Text size="xs" c="dimmed">unassigned</Text>) },
          { key: 'created_at', label: 'Opened', render: (t) => <Time value={t.created_at} relative /> },
        ]} />
    </>
  );
}
