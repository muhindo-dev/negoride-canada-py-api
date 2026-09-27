import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Badge, Button, Group, Modal, Progress, Select, Stack, Tabs, Text, TextInput } from '@mantine/core';
import { FiPlus } from 'react-icons/fi';
import { http } from '../../lib/api';
import { humanize } from '../../lib/format';
import { useRoles } from '../../lib/roles';
import { DataTable, ErrorBox, notifyErr, PageHeader, StatusBadge, Time } from '../../components/ui';

export default function Legal() {
  const nav = useNavigate();
  const { can } = useRoles();
  const [type, setType] = useState('');
  const [lang, setLang] = useState('');
  const q = useQuery({ queryKey: ['legal', 'docs', type, lang], queryFn: () => http.get('/admin/legal/documents', { type, language: lang }) });
  const stats = useQuery({ queryKey: ['legal', 'stats'], queryFn: () => http.get('/admin/legal/stats') });
  const [create, setCreate] = useState(null);
  const [busy, setBusy] = useState(false);
  const types = q.data?.types || [];
  return (
    <>
      <PageHeader title="Legal" subtitle="Versioned documents (Markdown), publishing and acceptance proof (spec §12)"
        actions={can('legalEdit') && <Button leftSection={<FiPlus />} onClick={() => setCreate({ type: types[0] || 'terms', version: '', language: 'en' })}>New version</Button>} />
      <Tabs defaultValue="docs" keepMounted={false}>
        <Tabs.List mb="sm"><Tabs.Tab value="docs">Documents</Tabs.Tab><Tabs.Tab value="stats">Acceptance stats</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="docs">
          <Group mb="sm" gap="xs">
            <Select size="xs" placeholder="All types" clearable value={type} onChange={(v) => setType(v || '')} data={types.map((t) => ({ value: t, label: humanize(t) }))} w={220} />
            <Select size="xs" placeholder="All languages" clearable value={lang} onChange={(v) => setLang(v || '')} data={['en', 'fr']} w={140} />
          </Group>
          <DataTable loading={q.isLoading} error={q.error} rows={q.data?.items || []} onRowClick={(d) => nav(`/legal/${d.id}`)} minWidth={900} empty="No documents."
            columns={[
              { key: 'type', label: 'Type', render: (d) => <Text size="sm" fw={500}>{humanize(d.type)}</Text> },
              { key: 'title', label: 'Title' },
              { key: 'version', label: 'Version', render: (d) => <Badge variant="outline">v{d.version}</Badge> },
              { key: 'language', label: 'Lang', render: (d) => d.language.toUpperCase() },
              { key: 'status', label: 'Status', render: (d) => <StatusBadge value={d.status} /> },
              { key: 'audience', label: 'Audience', render: (d) => humanize(d.audience) },
              { key: 'req', label: 'Re-accept', render: (d) => (d.requires_reacceptance ? 'Yes' : '') },
              { key: 'published_at', label: 'Published', render: (d) => <Time value={d.published_at} /> },
              { key: 'updated_at', label: 'Updated', render: (d) => <Time value={d.updated_at} relative /> },
            ]} />
        </Tabs.Panel>
        <Tabs.Panel value="stats">
          <ErrorBox error={stats.error} />
          <Text size="sm" mb="xs">Out of {stats.data?.total_users ?? '—'} users.</Text>
          <DataTable loading={stats.isLoading} rows={(stats.data?.items || []).filter((d) => d.status !== 'draft')} minWidth={800} onRowClick={(d) => nav(`/legal/${d.id}?tab=acceptances`)}
            columns={[
              { key: 'type', label: 'Document', render: (d) => `${humanize(d.type)} v${d.version} (${d.language})` },
              { key: 'status', label: 'Status', render: (d) => <StatusBadge value={d.status} /> },
              { key: 'acceptances', label: 'Acceptances' },
              { key: 'rate', label: 'Rate', render: (d) => (
                <Stack gap={2} w={180}><Progress value={d.acceptance_rate_pct} size="sm" /><Text size="xs">{d.acceptance_rate_pct}%</Text></Stack>
              ) },
              { key: 'effective_at', label: 'Effective', render: (d) => <Time value={d.effective_at} /> },
            ]} />
        </Tabs.Panel>
      </Tabs>
      <Modal opened={!!create} onClose={() => setCreate(null)} title="New draft version" centered>
        {create && (
          <Stack>
            <Select label="Document type" value={create.type} onChange={(v) => setCreate({ ...create, type: v })} data={types.map((t) => ({ value: t, label: humanize(t) }))} allowDeselect={false} />
            <Group grow>
              <TextInput label="Version" placeholder="e.g. 1.1" required value={create.version} onChange={(e) => setCreate({ ...create, version: e.currentTarget.value })} />
              <Select label="Language" value={create.language} onChange={(v) => setCreate({ ...create, language: v })} data={['en', 'fr']} allowDeselect={false} />
            </Group>
            <Text size="xs" c="dimmed">The draft starts as a copy of the current published version.</Text>
            <Group justify="flex-end">
              <Button loading={busy} disabled={!create.version} onClick={async () => {
                setBusy(true);
                try { const d = await http.post('/admin/legal/documents', create); setCreate(null); nav(`/legal/${d.id}`); } catch (e) { notifyErr(e); } finally { setBusy(false); }
              }}>Create draft</Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}
