import React, { useEffect, useState } from 'react';
import { useSearchParams, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import {
  Alert, Badge, Button, Card, Checkbox, Grid, Group, Modal, ScrollArea, SegmentedControl, Select, Stack, Tabs, Text, Textarea, TextInput,
} from '@mantine/core';
import { http, page } from '../../lib/api';
import { humanize } from '../../lib/format';
import { useRoles } from '../../lib/roles';
import { DataTable, ErrorBox, Loading, notifyErr, notifyOk, PageHeader, StatusBadge, Time, UserLink } from '../../components/ui';

function Acceptances({ id }) {
  const [p, setP] = useState(1);
  const q = useQuery({ queryKey: ['legal', 'acc', id, p], queryFn: () => http.get(`/admin/legal/documents/${id}/acceptances`, { page: p }) });
  const pg = page(q.data);
  return (
    <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={800} empty="Nobody has accepted this version yet."
      columns={[
        { key: 'user', label: 'User', render: (a) => <UserLink id={a.user_id} name={a.user?.name} /> },
        { key: 'accepted_at', label: 'Accepted', render: (a) => <Time value={a.accepted_at} seconds /> },
        { key: 'method', label: 'Method' }, { key: 'ip', label: 'IP' }, { key: 'app_version', label: 'App' },
        { key: 'ua', label: 'User agent', render: (a) => <Text size="xs" lineClamp={1} maw={260}>{a.user_agent}</Text> },
      ]} />
  );
}

export default function LegalEditor() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const qc = useQueryClient();
  const { can } = useRoles();
  const q = useQuery({ queryKey: ['legal', 'doc', id], queryFn: () => http.get(`/admin/legal/documents/${id}`) });
  const [f, setF] = useState(null);
  const [view, setView] = useState('split');
  const [serverPreview, setServerPreview] = useState(null);
  const [pub, setPub] = useState(null);
  const [busy, setBusy] = useState(null);
  useEffect(() => { if (q.data) setF({ title: q.data.title, summary_markdown: q.data.summary_markdown || '', body_markdown: q.data.body_markdown || '', what_changed: q.data.what_changed || '', audience: q.data.audience }); }, [q.data]);

  if (q.isLoading || !f) return q.error ? <ErrorBox error={q.error} /> : <Loading />;
  const d = q.data;
  const editable = d.status === 'draft' && can('legalEdit');
  const dirty = ['title', 'summary_markdown', 'body_markdown', 'what_changed', 'audience'].some((k) => (f[k] || '') !== (d[k] || ''));
  const save = async () => {
    setBusy('save');
    try { await http.put(`/admin/legal/documents/${id}`, f); notifyOk('Draft saved'); qc.invalidateQueries({ queryKey: ['legal'] }); } catch (e) { notifyErr(e); } finally { setBusy(null); }
  };
  const preview = async () => {
    setBusy('preview');
    try { setServerPreview(await http.post(`/admin/legal/documents/${id}/preview`, { body_markdown: f.body_markdown, summary_markdown: f.summary_markdown })); setView('preview'); } catch (e) { notifyErr(e); } finally { setBusy(null); }
  };
  const bodyShown = view === 'preview' && serverPreview ? serverPreview.body_markdown : f.body_markdown;
  const summaryShown = view === 'preview' && serverPreview ? serverPreview.summary_markdown : f.summary_markdown;

  return (
    <>
      <PageHeader
        title={<Group gap="xs">{humanize(d.type)} <Badge variant="outline">v{d.version}</Badge> <Badge variant="light">{d.language.toUpperCase()}</Badge> <StatusBadge value={d.status} size="lg" /></Group>}
        subtitle={d.published_at ? `Published ${new Date(d.published_at).toLocaleString()}` : 'Draft — not visible to users yet'}
        actions={<>
          {editable && <Button variant="default" onClick={preview} loading={busy === 'preview'}>Preview with variables</Button>}
          {editable && <Button onClick={save} loading={busy === 'save'} disabled={!dirty}>Save draft</Button>}
          {editable && <Button color="green" disabled={dirty} onClick={() => setPub({ requires_reacceptance: false, what_changed: f.what_changed, effective_at: '' })}>Publish…</Button>}
        </>}
      />
      {!editable && d.status !== 'draft' && <Alert color="gray" mb="sm">Published versions are read-only. Create a new version from the Legal list to change the text.</Alert>}
      {editable && dirty && <Alert color="yellow" mb="sm" py={6}>Unsaved changes — save before publishing.</Alert>}
      <Tabs defaultValue={sp.get('tab') || 'edit'} keepMounted={false}>
        <Tabs.List mb="sm"><Tabs.Tab value="edit">{editable ? 'Editor' : 'Content'}</Tabs.Tab><Tabs.Tab value="acceptances">Acceptances</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="edit">
          <Group mb="sm" gap="xs" align="flex-end" wrap="wrap">
            <TextInput label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.currentTarget.value })} disabled={!editable} w={320} />
            <Select label="Audience" value={f.audience} onChange={(v) => setF({ ...f, audience: v })} data={['all', 'customer', 'driver']} disabled={!editable} w={140} allowDeselect={false} />
            <SegmentedControl value={view} onChange={setView} data={[{ value: 'edit', label: 'Markdown' }, { value: 'split', label: 'Split' }, { value: 'preview', label: 'Preview' }]} />
          </Group>
          <Grid gutter="sm">
            {view !== 'preview' && (
              <Grid.Col span={{ base: 12, md: view === 'split' ? 6 : 12 }}>
                <Stack gap="xs">
                  <Textarea label="Plain-language summary (shown in a box above the text)" value={f.summary_markdown} onChange={(e) => setF({ ...f, summary_markdown: e.currentTarget.value })} autosize minRows={3} maxRows={8} disabled={!editable} styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }} />
                  <Textarea label="Body (Markdown)" value={f.body_markdown} onChange={(e) => setF({ ...f, body_markdown: e.currentTarget.value })} autosize minRows={18} maxRows={40} disabled={!editable} styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }} />
                  <Textarea label="What changed (shown in the re-acceptance modal)" value={f.what_changed} onChange={(e) => setF({ ...f, what_changed: e.currentTarget.value })} autosize minRows={2} disabled={!editable} />
                </Stack>
              </Grid.Col>
            )}
            {view !== 'edit' && (
              <Grid.Col span={{ base: 12, md: view === 'split' ? 6 : 12 }}>
                <Card withBorder radius="md" padding="md">
                  <ScrollArea.Autosize mah="75vh">
                    <Text fw={700} fz="xl" mb="xs">{f.title}</Text>
                    {summaryShown && <Card withBorder bg="var(--mantine-color-orange-light)" padding="sm" mb="sm" className="md-preview"><ReactMarkdown>{summaryShown}</ReactMarkdown></Card>}
                    <div className="md-preview" data-testid="legal-preview"><ReactMarkdown>{bodyShown}</ReactMarkdown></div>
                  </ScrollArea.Autosize>
                  {view === 'preview' && serverPreview && <Text size="xs" c="dimmed" mt="xs">Rendered by the server with live variables: {Object.entries(serverPreview.variables || {}).slice(0, 6).map(([k, v]) => `${k}=${v}`).join(', ')}</Text>}
                </Card>
              </Grid.Col>
            )}
          </Grid>
        </Tabs.Panel>
        <Tabs.Panel value="acceptances"><Acceptances id={id} /></Tabs.Panel>
      </Tabs>
      <Modal opened={!!pub} onClose={() => setPub(null)} title={`Publish ${humanize(d.type)} v${d.version}`} centered>
        {pub && (
          <Stack>
            <Text size="sm">The current published {d.language.toUpperCase()} version will be archived.</Text>
            <Checkbox label="Users must re-accept (blocking modal on next app open)" checked={pub.requires_reacceptance} onChange={(e) => setPub({ ...pub, requires_reacceptance: e.currentTarget.checked })} />
            <Textarea label="What changed" value={pub.what_changed} onChange={(e) => setPub({ ...pub, what_changed: e.currentTarget.value })} autosize minRows={2} />
            <TextInput type="datetime-local" label="Effective at (your time; blank = now)" value={pub.effective_at} onChange={(e) => setPub({ ...pub, effective_at: e.currentTarget.value })} />
            <Group justify="flex-end">
              <Button color="green" loading={busy === 'publish'} onClick={async () => {
                setBusy('publish');
                try {
                  const eff = pub.effective_at ? new Date(pub.effective_at).toISOString().slice(0, 19) : undefined;
                  const r = await http.postFull(`/admin/legal/documents/${id}/publish`, { requires_reacceptance: pub.requires_reacceptance, what_changed: pub.what_changed || undefined, effective_at: eff });
                  notifyOk(r.message); setPub(null); qc.invalidateQueries({ queryKey: ['legal'] });
                } catch (e) { notifyErr(e); } finally { setBusy(null); }
              }}>Publish</Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}
