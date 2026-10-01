import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Badge, Button, Card, Divider, Grid, Group, Modal, NumberInput, SegmentedControl, Select, Stack, Switch, Tabs, Text, Textarea, TextInput, Tooltip,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from 'recharts';
import { http, page } from '../lib/api';
import { fmt, humanize, statusColor } from '../lib/format';
import { useRoles } from '../lib/roles';
import { DataTable, ErrorBox, notifyErr, notifyOk, PageHeader, Time, UserLink } from '../components/ui';

export const PROVINCES = ['AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT'];
const STATUS_ORDER = ['queued', 'sent', 'delivered', 'opened', 'failed', 'skipped'];
const COLORS = { queued: '#adb5bd', sent: '#339af0', delivered: '#40c057', opened: '#12b886', failed: '#fa5252', skipped: '#868e96' };

function Log() {
  const [userId, setUserId] = useState('');
  const [eventKey, setEventKey] = useState('');
  const [dk] = useDebouncedValue(eventKey, 350);
  const [p, setP] = useState(1);
  const params = { user_id: userId || undefined, event_key: dk || undefined, page: p, per_page: 25 };
  const q = useQuery({ queryKey: ['notifications', 'log', params], queryFn: () => http.get('/admin/notifications', params), refetchInterval: 30000 });
  const pg = page(q.data);
  return (
    <>
      <Group mb="sm" gap="xs">
        <NumberInput size="xs" placeholder="User ID" value={userId} onChange={(v) => { setUserId(v ? String(v) : ''); setP(1); }} w={110} hideControls />
        <TextInput size="xs" placeholder="Event key prefix (e.g. ride.)" value={eventKey} onChange={(e) => { setEventKey(e.currentTarget.value); setP(1); }} w={220} />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={1000} empty="No notifications."
        columns={[
          { key: 'created_at', label: 'When', render: (n) => <Time value={n.created_at} /> },
          { key: 'user', label: 'User', render: (n) => <UserLink id={n.user_id} name={n.user_name} /> },
          { key: 'event_key', label: 'Event', render: (n) => <Group gap={4}><Text size="xs" ff="monospace">{n.event_key}</Text>{n.is_critical && <Badge size="xs" color="red">critical</Badge>}</Group> },
          { key: 'title', label: 'Message', render: (n) => <div><Text size="sm" fw={500} lineClamp={1}>{n.title}</Text><Text size="xs" c="dimmed" lineClamp={1}>{n.body}</Text></div> },
          { key: 'deliveries', label: 'Channels', render: (n) => (
            <Group gap={4}>
              {(n.deliveries || []).map((d) => (
                <Tooltip key={d.id} label={`${d.status}${d.error ? ` — ${d.error}` : ''} · attempts ${d.attempts}${d.sent_at ? ` · sent ${fmt.time(d.sent_at)}` : ''}`} multiline w={260}>
                  <Badge size="sm" variant="light" color={statusColor(d.status)}>{d.channel}: {d.status}</Badge>
                </Tooltip>
              ))}
              {!n.deliveries?.length && <Text size="xs" c="dimmed">inbox only</Text>}
            </Group>
          ) },
          { key: 'read', label: 'Read', render: (n) => (n.opened_at ? 'opened' : n.read_at ? 'read' : '—') },
        ]} />
    </>
  );
}

function Stats() {
  const [days, setDays] = useState('7');
  const q = useQuery({ queryKey: ['notifications', 'stats', days], queryFn: () => http.get('/admin/notifications/stats', { days }) });
  const rows = Object.entries(q.data || {}).map(([channel, st]) => ({ channel, ...st }));
  const statuses = STATUS_ORDER.filter((s) => rows.some((r) => r[s])).concat(
    [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((k) => k !== 'channel' && !STATUS_ORDER.includes(k)),
  );
  return (
    <Card withBorder radius="md" padding="sm">
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Delivery status by channel</Text>
        <SegmentedControl size="xs" value={days} onChange={setDays} data={['1', '7', '30'].map((d) => ({ value: d, label: `${d} d` }))} />
      </Group>
      <ErrorBox error={q.error} />
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={rows}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="channel" />
          <YAxis allowDecimals={false} />
          <RTooltip />
          <Legend />
          {statuses.map((s) => <Bar key={s} dataKey={s} stackId="a" fill={COLORS[s] || '#7950f2'} name={humanize(s)} />)}
        </BarChart>
      </ResponsiveContainer>
      {!rows.length && !q.isLoading && <Text size="sm" c="dimmed">No deliveries in this window.</Text>}
    </Card>
  );
}

function Compose() {
  const { can } = useRoles();
  const [f, setF] = useState({ title: '', body: '', role: 'all', province: '', city: '', route: 'home', marketing_only: true });
  const [count, setCount] = useState(null);
  const [busy, setBusy] = useState(null);
  const set = (k, v) => { setF({ ...f, [k]: v }); setCount(null); };
  const send = async (dry) => {
    setBusy(dry ? 'dry' : 'send');
    try {
      const body = { ...f, province: f.province || undefined, city: f.city || undefined, dry_run: dry };
      if (dry) {
        const r = await http.post('/admin/notifications/broadcast', body);
        setCount(r.recipients);
      } else {
        if (!window.confirm(`Send “${f.title}” to ${count ?? 'all matching'} user(s)?`)) return;
        const r = await http.postFull('/admin/notifications/broadcast', body);
        notifyOk(r.message);
      }
    } catch (e) { notifyErr(e); } finally { setBusy(null); }
  };
  if (!can('broadcast')) return <Alert color="yellow">Composing broadcasts needs the Ops role.</Alert>;
  return (
    <Grid gutter="sm">
      <Grid.Col span={{ base: 12, md: 7 }}>
        <Card withBorder radius="md" padding="sm">
          <Stack gap="xs">
            <TextInput label="Title" required value={f.title} onChange={(e) => set('title', e.currentTarget.value)} maxLength={120} />
            <Textarea label="Body" required value={f.body} onChange={(e) => set('body', e.currentTarget.value)} autosize minRows={3} maxLength={500} />
            <Group grow>
              <Select label="Audience" value={f.role} onChange={(v) => set('role', v)} data={[{ value: 'all', label: 'Everyone' }, { value: 'customers', label: 'Customers' }, { value: 'drivers', label: 'Drivers' }]} allowDeselect={false} />
              <Select label="Province" clearable value={f.province} onChange={(v) => set('province', v || '')} data={PROVINCES} />
              <TextInput label="City contains" value={f.city} onChange={(e) => set('city', e.currentTarget.value)} placeholder="e.g. Toronto" />
            </Group>
            <Group grow>
              <TextInput label="Deep link route" value={f.route} onChange={(e) => set('route', e.currentTarget.value)} />
              <Switch label="Only users who opted in to marketing (CASL)" checked={f.marketing_only} onChange={(e) => set('marketing_only', e.currentTarget.checked)} mt="lg" />
            </Group>
            <Group justify="space-between" mt="xs">
              <Text size="sm" data-testid="broadcast-count">{count === null ? 'Run a dry run to count recipients.' : <>Would reach <b>{count}</b> user(s).</>}</Text>
              <Group gap="xs">
                <Button variant="default" loading={busy === 'dry'} disabled={!f.title || !f.body} onClick={() => send(true)}>Dry run (count)</Button>
                <Button color="orange" loading={busy === 'send'} disabled={!f.title || !f.body || count === null} onClick={() => send(false)}>Send broadcast</Button>
              </Group>
            </Group>
          </Stack>
        </Card>
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 5 }}>
        <Card withBorder radius="md" padding="sm">
          <Text size="xs" c="dimmed" mb={6}>Push preview</Text>
          <Card radius="lg" padding="sm" bg="var(--mantine-color-default-hover)">
            <Group gap={6} mb={4}><Badge size="xs" color="orange">NegoRide</Badge><Text size="xs" c="dimmed">now</Text></Group>
            <Text fw={600} size="sm">{f.title || 'Title'}</Text>
            <Text size="sm">{f.body || 'Message body'}</Text>
          </Card>
          <Text size="xs" c="dimmed" mt="xs">Sent as the “broadcast” event (push + in-app inbox). Delivery appears in the log. Audited.</Text>
        </Card>
      </Grid.Col>
    </Grid>
  );
}

function TemplateEditor({ eventKey, onClose, canEdit }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['notifications', 'template', eventKey], queryFn: () => http.get(`/admin/notifications/templates/${encodeURIComponent(eventKey)}`) });
  const [lang, setLang] = useState('en');
  const [draft, setDraft] = useState({}); // lang → {title, body}
  const [ctxText, setCtxText] = useState('');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const t = q.data;
  const ov = t?.overrides?.[lang];
  const base = { title: ov?.title ?? t?.default?.title?.[lang] ?? '', body: ov?.body ?? t?.default?.body?.[lang] ?? '' };
  const cur = draft[lang] || base;
  const dirty = !!draft[lang] && (draft[lang].title !== base.title || draft[lang].body !== base.body);
  const set = (k, v) => setDraft((d) => ({ ...d, [lang]: { ...(d[lang] || base), [k]: v } }));
  const refresh = () => { qc.invalidateQueries({ queryKey: ['notifications', 'template', eventKey] }); qc.invalidateQueries({ queryKey: ['notifications', 'templates'] }); };
  const parseCtx = () => {
    if (!ctxText.trim()) return undefined;
    try { return JSON.parse(ctxText); } catch { throw new Error('Sample context must be a JSON object, e.g. {"driver_first": "Ana"}'); }
  };
  const runPreview = async (which = cur) => {
    setBusy('preview'); setErr(null);
    try {
      const r = await http.post(`/admin/notifications/templates/${encodeURIComponent(eventKey)}/preview`, { lang, title: which.title, body: which.body, context: parseCtx() });
      setPreview({ ...r, lang });
    } catch (e) { setErr(e.message); } finally { setBusy(null); }
  };
  const vars = Object.keys(preview?.context || {});
  return (
    <Modal opened onClose={onClose} size="xl" centered title={<Group gap="xs"><Text fw={700} ff="monospace">{eventKey}</Text>{t && <Badge size="xs" variant="light">{t.group}</Badge>}</Group>}>
      {q.isLoading ? <Text size="sm" c="dimmed">Loading…</Text> : q.error ? <ErrorBox error={q.error} /> : (
        <Stack gap="sm">
          <Group justify="space-between" wrap="wrap">
            <SegmentedControl value={lang} onChange={(v) => { setLang(v); setPreview(null); setErr(null); }} data={[
              { value: 'en', label: `English${t.overrides?.en ? ' · custom' : ''}` },
              { value: 'fr', label: `Français${t.overrides?.fr ? ' · custom' : ''}` },
            ]} data-testid="tpl-lang" />
            <Group gap={4}>{(t.channels || []).map((c) => <Badge key={c} size="xs" variant="light">{c}</Badge>)}</Group>
          </Group>
          {ov ? (
            <Alert color="blue" variant="light" py={6}>Custom {lang.toUpperCase()} copy in use — last changed {fmt.dateTime(ov.updated_at)}{ov.updated_by ? <> by <UserLink id={ov.updated_by} /></> : ''}. Every save and reset is written to the audit log (notifications.template_override / template_reset).</Alert>
          ) : (
            <Alert color="gray" variant="light" py={6}>Using the built-in catalogue copy for {lang.toUpperCase()}. Saving creates an override (audited as notifications.template_override); “Reset to default” removes it.</Alert>
          )}
          <Grid gutter="sm">
            <Grid.Col span={{ base: 12, md: 7 }}>
              <Stack gap="xs">
                <TextInput label="Title" value={cur.title} onChange={(e) => set('title', e.currentTarget.value)} disabled={!canEdit} maxLength={255} data-testid="tpl-title"
                  description="Jinja2, same variables as the default. ≤ 255 characters." />
                <Textarea label="Body" value={cur.body} onChange={(e) => set('body', e.currentTarget.value)} disabled={!canEdit} autosize minRows={4} maxLength={2000} data-testid="tpl-body"
                  description={`${cur.body.length}/2000 · push/SMS show the body; keep it short.`} styles={{ input: { fontFamily: 'monospace', fontSize: 13 } }} />
                <Textarea label="Sample context (optional JSON)" placeholder='{"driver_first": "Ana", "eta_min": 3}' value={ctxText} onChange={(e) => setCtxText(e.currentTarget.value)} autosize minRows={1} styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }} />
                {vars.length > 0 && (
                  <Group gap={4}>
                    <Text size="xs" c="dimmed">Variables:</Text>
                    {vars.map((v) => (
                      <Badge key={v} size="xs" variant="outline" style={{ cursor: canEdit ? 'copy' : 'default', textTransform: 'none' }}
                        onClick={() => canEdit && set('body', `${cur.body}{{ ${v} }}`)}>{`{{ ${v} }}`}</Badge>
                    ))}
                  </Group>
                )}
              </Stack>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 5 }}>
              <Card withBorder radius="md" padding="sm" data-testid="tpl-preview">
                <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb={4}>Preview ({lang.toUpperCase()}) — nothing is sent</Text>
                {preview ? (
                  <>
                    <Text fw={700} size="sm">{preview.title}</Text>
                    <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{preview.body}</Text>
                  </>
                ) : <Text size="sm" c="dimmed">Click “Preview” to render the draft with sample data.</Text>}
                <Divider my="xs" />
                <Text size="xs" c="dimmed" tt="uppercase" fw={700} mb={2}>Default copy</Text>
                <Text size="xs" fw={600}>{t.default?.title?.[lang]}</Text>
                <Text size="xs" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>{t.default?.body?.[lang]}</Text>
              </Card>
            </Grid.Col>
          </Grid>
          {err && <Alert color="red" py={6}>{err}</Alert>}
          <Group justify="space-between">
            <Group gap="xs">
              {canEdit && ov && (
                <Button color="red" variant="light" loading={busy === 'reset'} data-testid="tpl-reset" onClick={async () => {
                  if (!window.confirm(`Reset the ${lang.toUpperCase()} copy of ${eventKey} to the built-in default?`)) return;
                  setBusy('reset'); setErr(null);
                  try {
                    await http.del(`/admin/notifications/templates/${encodeURIComponent(eventKey)}?lang=${lang}`);
                    notifyOk(`${eventKey} (${lang.toUpperCase()}) reset to default · audited`);
                    setDraft((d) => { const n = { ...d }; delete n[lang]; return n; });
                    setPreview(null);
                    refresh();
                  } catch (e) { setErr(e.message); } finally { setBusy(null); }
                }}>Reset to default</Button>
              )}
              {dirty && <Button variant="subtle" color="gray" onClick={() => setDraft((d) => { const n = { ...d }; delete n[lang]; return n; })}>Discard</Button>}
            </Group>
            <Group gap="xs">
              <Button variant="default" loading={busy === 'preview'} onClick={() => runPreview()} data-testid="tpl-preview-btn">Preview</Button>
              {canEdit && (
                <Button disabled={!dirty} loading={busy === 'save'} data-testid="tpl-save" onClick={async () => {
                  setBusy('save'); setErr(null);
                  try {
                    await http.put(`/admin/notifications/templates/${encodeURIComponent(eventKey)}`, { lang, title: cur.title, body: cur.body });
                    notifyOk(`${eventKey} (${lang.toUpperCase()}) saved · audited`);
                    setDraft((d) => { const n = { ...d }; delete n[lang]; return n; });
                    refresh();
                    runPreview(cur);
                  } catch (e) { setErr(e.message); } finally { setBusy(null); }
                }}>Save {lang.toUpperCase()} copy</Button>
              )}
            </Group>
          </Group>
          {!canEdit && <Text size="xs" c="dimmed">Read-only: editing templates needs the Ops or Super admin role.</Text>}
        </Stack>
      )}
    </Modal>
  );
}

function Templates() {
  const { can } = useRoles();
  const q = useQuery({ queryKey: ['notifications', 'templates'], queryFn: () => http.get('/admin/notifications/templates'), staleTime: 60000 });
  const [group, setGroup] = useState('');
  const [lang, setLang] = useState('en');
  const [search, setSearch] = useState('');
  const [onlyCustom, setOnlyCustom] = useState(false);
  const [edit, setEdit] = useState(null);
  const all = q.data?.items || [];
  const items = all.filter((t) => (!group || t.group === group) && (!search || t.event_key.includes(search.toLowerCase()))
    && (!onlyCustom || Object.keys(t.overrides || {}).length));
  const groups = [...new Set(all.map((t) => t.group))].sort();
  const customCount = all.filter((t) => Object.keys(t.overrides || {}).length).length;
  return (
    <>
      <Group mb="sm" gap="xs" wrap="wrap">
        <TextInput size="xs" placeholder="Event key" value={search} onChange={(e) => setSearch(e.currentTarget.value)} w={200} />
        <Select size="xs" placeholder="All groups" clearable value={group} onChange={(v) => setGroup(v || '')} data={groups} w={170} />
        <SegmentedControl size="xs" value={lang} onChange={setLang} data={[{ value: 'en', label: 'EN' }, { value: 'fr', label: 'FR' }]} />
        <Switch size="xs" label={`Customised only (${customCount})`} checked={onlyCustom} onChange={(e) => setOnlyCustom(e.currentTarget.checked)} />
        {q.data && <Text size="xs" c="dimmed">Mandatory groups (users can’t mute): {q.data.mandatory_groups.join(', ')}</Text>}
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={items} rowKey="event_key" minWidth={1000} empty="No templates." onRowClick={(t) => setEdit(t.event_key)}
        columns={[
          { key: 'event_key', label: 'Event', render: (t) => <Group gap={4}><Text size="xs" ff="monospace">{t.event_key}</Text>{t.critical && <Badge size="xs" color="red">critical</Badge>}</Group> },
          { key: 'group', label: 'Group', render: (t) => <Group gap={4}><Text size="sm">{t.group}</Text>{t.mandatory && <Badge size="xs" variant="outline">mandatory</Badge>}</Group> },
          { key: 'channels', label: 'Channels', render: (t) => <Group gap={2}>{t.channels.map((c) => <Badge key={c} size="xs" variant="light">{c}</Badge>)}{t.sms_fallback && <Badge size="xs" color="orange" variant="light">SMS fallback</Badge>}</Group> },
          { key: 'copy', label: `Copy (${lang.toUpperCase()})`, render: (t) => {
            const o = t.overrides?.[lang];
            return (
              <div>
                <Group gap={4} wrap="nowrap"><Text size="sm" fw={500}>{o?.title ?? t.title?.[lang]}</Text>{o && <Badge size="xs" color="blue">custom</Badge>}</Group>
                <Text size="xs" c="dimmed" lineClamp={2} maw={420}>{o?.body ?? t.body?.[lang]}</Text>
              </div>
            );
          } },
          { key: 'custom', label: 'Overrides', render: (t) => <Group gap={2}>{['en', 'fr'].filter((l) => t.overrides?.[l]).map((l) => <Badge key={l} size="xs" color="blue" variant="light">{l.toUpperCase()}</Badge>)}</Group> },
          { key: 'x', label: '', render: (t) => <Button size="compact-xs" variant="subtle" data-testid="tpl-edit" onClick={(e) => { e.stopPropagation(); setEdit(t.event_key); }}>{can('notificationTemplatesEdit') ? 'Edit' : 'View'}</Button> },
        ]} />
      <Text size="xs" c="dimmed" mt="xs">Defaults live in backend/services/notify/catalogue.py; overrides are per event and language, validated as Jinja2 and audited.</Text>
      {edit && <TemplateEditor eventKey={edit} canEdit={can('notificationTemplatesEdit')} onClose={() => setEdit(null)} />}
    </>
  );
}

export default function Notifications() {
  return (
    <>
      <PageHeader title="Notifications" subtitle="Delivery log with per-channel status · broadcast composer" />
      <Tabs defaultValue="log" keepMounted={false}>
        <Tabs.List mb="sm"><Tabs.Tab value="log">Delivery log</Tabs.Tab><Tabs.Tab value="stats">Channel stats</Tabs.Tab><Tabs.Tab value="templates">Templates</Tabs.Tab><Tabs.Tab value="compose">Compose broadcast</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="log"><Log /></Tabs.Panel>
        <Tabs.Panel value="stats"><Stats /></Tabs.Panel>
        <Tabs.Panel value="templates"><Templates /></Tabs.Panel>
        <Tabs.Panel value="compose"><Compose /></Tabs.Panel>
      </Tabs>
    </>
  );
}
