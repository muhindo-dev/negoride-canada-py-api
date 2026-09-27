import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Avatar, Badge, Group, Select, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { FiSearch } from 'react-icons/fi';
import { http, page } from '../../lib/api';
import { initials } from '../../lib/format';
import { DataTable, PageHeader, StatusBadge, Time } from '../../components/ui';

export default function UsersList() {
  const nav = useNavigate();
  const [search, setSearch] = useState('');
  const [type, setType] = useState('');
  const [status, setStatus] = useState('');
  const [p, setP] = useState(1);
  const [dq] = useDebouncedValue(search, 350);
  const params = { search: dq, user_type: type, status, page: p, per_page: 25 };
  const q = useQuery({ queryKey: ['users', params], queryFn: () => http.get('/admin/users', params) });
  const pg = page(q.data);
  return (
    <>
      <PageHeader title="Users" subtitle="Customers and drivers · open a profile for verification, ratings, strikes, documents and account actions" />
      <Group mb="sm" gap="xs" wrap="wrap">
        <TextInput size="xs" leftSection={<FiSearch />} placeholder="Name, email, phone, username" value={search} onChange={(e) => { setSearch(e.currentTarget.value); setP(1); }} w={280} />
        <Select size="xs" placeholder="All types" clearable value={type} onChange={(v) => { setType(v || ''); setP(1); }} data={['Customer', 'Driver', 'Pending Driver', 'Admin']} w={160} />
        <Select size="xs" placeholder="Any status" clearable value={status} onChange={(v) => { setStatus(v || ''); setP(1); }} data={[{ value: '1', label: 'Active (1)' }, { value: '0', label: 'Inactive (0)' }]} w={150} />
      </Group>
      <DataTable
        loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={900}
        onRowClick={(u) => nav(`/users/${u.id}`)}
        columns={[
          { key: 'name', label: 'User', render: (u) => (
            <Group gap="xs" wrap="nowrap">
              <Avatar src={u.avatar || null} size={28} radius="xl">{initials(u.name)}</Avatar>
              <div style={{ minWidth: 0 }}>
                <Text size="sm" fw={500} truncate>{u.name || '—'}</Text>
                <Text size="xs" c="dimmed" truncate>#{u.id} · {u.email || u.phone_number || ''}</Text>
              </div>
            </Group>
          ) },
          { key: 'user_type', label: 'Type', render: (u) => <Badge variant="light" color={u.user_type === 'Driver' ? 'blue' : u.user_type === 'Pending Driver' ? 'yellow' : 'gray'}>{u.user_type}</Badge> },
          { key: 'account_status', label: 'Account', render: (u) => <StatusBadge value={u.account_status || (Number(u.status) === 1 ? 'active' : 'deactivated')} /> },
          { key: 'verified', label: 'Verified', render: (u) => (
            <Group gap={4}>
              {u.phone_verified && <Badge size="xs" color="green" variant="light">phone</Badge>}
              {u.email_verified && <Badge size="xs" color="green" variant="light">email</Badge>}
              {!u.phone_verified && !u.email_verified && <Text size="xs" c="dimmed">—</Text>}
            </Group>
          ) },
          { key: 'rating', label: 'Rating', render: (u) => (u.rating ? `★ ${Number(u.rating).toFixed(2)} (${u.rating_count || 0})` : '—') },
          { key: 'province', label: 'Prov.', render: (u) => u.province || '—' },
          { key: 'created_at', label: 'Joined', render: (u) => <Time value={u.created_at} /> },
        ]}
      />
    </>
  );
}
