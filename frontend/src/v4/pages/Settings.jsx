import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Anchor, Badge, Button, Card, Group, NumberInput, ScrollArea, Stack, Switch, Tabs, Text, Textarea, TextInput, Tooltip,
} from '@mantine/core';
import { FiRotateCcw, FiSearch } from 'react-icons/fi';
import { http } from '../lib/api';
import { humanize, money } from '../lib/format';
import { useRoles } from '../lib/roles';
import { ErrorBox, Loading, notifyErr, notifyOk, PageHeader } from '../components/ui';

const ORDER = ['flags', 'pricing', 'cancellation', 'ride', 'safety', 'onboarding', 'ratings', 'identity', 'support', 'eta', 'app', 'custom'];
const TITLES = {
  flags: 'Feature flags', pricing: 'Fees & commission', cancellation: 'Cancellation, waiting & strikes', ride: 'Ride rules & geofences',
  safety: 'Safety, tracking & recordings', onboarding: 'Driver onboarding & background checks', ratings: 'Ratings', identity: 'Phone verification (OTP)',
  support: 'Support SLAs', eta: 'ETA', app: 'App',
};

function hint(key, value) {
  if (value === null || value === undefined || value === '') return null;
  if (/_cents$/.test(key)) return money(value);
  if (/_s$/.test(key)) return `${value}s = ${(value / 60).toFixed(1)} min`;
  if (/_m$/.test(key)) return `${value} m`;
  if (/_pct$/.test(key)) return `${value}%`;
  if (/_h$/.test(key)) return `${value} h`;
  return null;
}

function Field({ s, value, onChange, disabled }) {
  const label = (
    <Group gap={6} wrap="nowrap">
      <Text size="sm" ff="monospace" fw={500}>{s.key}</Text>
      {s.overridden && <Badge size="xs" variant="light">custom</Badge>}
      {s.is_public && <Tooltip label="Served to the apps via /api/app/config"><Badge size="xs" variant="outline" color="gray">public</Badge></Tooltip>}
    </Group>
  );
  const desc = <>{s.description}{hint(s.key, value) ? ` · ${hint(s.key, value)}` : ''}{s.default !== null && s.default !== undefined ? ` · default ${String(s.default)}` : ''}</>;
  if (s.type === 'bool') {
    return <Switch label={label} description={s.description} checked={!!value} onChange={(e) => onChange(e.currentTarget.checked)} disabled={disabled} />;
  }
  if (s.type === 'int' || s.type === 'float') {
    return <NumberInput label={label} description={desc} value={value ?? ''} onChange={(v) => onChange(v === '' ? null : v)} disabled={disabled} decimalScale={s.type === 'int' ? 0 : 4} allowDecimal={s.type !== 'int'} maw={420} />;
  }
  if (s.type === 'json') {
    return <Textarea label={label} description={desc} value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)} onChange={(e) => onChange(e.currentTarget.value)} disabled={disabled} autosize minRows={2} styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }} />;
  }
  return <TextInput label={label} description={desc} value={value ?? ''} onChange={(e) => onChange(e.currentTarget.value)} disabled={disabled} maw={620} />;
}

export default function Settings() {
  const qc = useQueryClient();
  const { can } = useRoles();
  const editable = can('settingsEdit');
  const q = useQuery({ queryKey: ['settings'], queryFn: () => http.get('/admin/settings') });
  const [draft, setDraft] = useState({});
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const groups = useMemo(() => {
    const g = {};
    (q.data?.items || []).forEach((s) => {
      if (search && !`${s.key} ${s.description}`.toLowerCase().includes(search.toLowerCase())) return;
      (g[s.category] ||= []).push(s);
    });
    return Object.keys(g).sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99)).map((c) => [c, g[c]]);
  }, [q.data, search]);
  const changed = Object.keys(draft);
  const save = async () => {
    setBusy(true);
    try {
      const values = {};
      changed.forEach((k) => {
        const s = q.data.items.find((x) => x.key === k);
        let v = draft[k];
        if (s?.type === 'json' && typeof v === 'string') v = JSON.parse(v);
        values[k] = v;
      });
      const r = await http.postFull('/admin/settings', { values });
      notifyOk(r.message);
      setDraft({});
      qc.invalidateQueries({ queryKey: ['settings'] });
    } catch (e) { notifyErr(e, 'Save failed'); } finally { setBusy(false); }
  };
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  return (
    <>
      <PageHeader title="Settings" subtitle="Every app_settings value, by category · changes apply immediately and are audited"
        actions={<>
          <TextInput size="xs" leftSection={<FiSearch />} placeholder="Filter settings" value={search} onChange={(e) => setSearch(e.currentTarget.value)} />
          {changed.length > 0 && <Button size="xs" variant="default" leftSection={<FiRotateCcw />} onClick={() => setDraft({})}>Discard</Button>}
          {editable && <Button size="xs" onClick={save} loading={busy} disabled={!changed.length} data-testid="settings-save">Save {changed.length || ''} change{changed.length === 1 ? '' : 's'}</Button>}
        </>} />
      {!editable && <Alert color="gray" mb="sm">Read-only: editing settings needs the Ops, Finance or Super admin role.</Alert>}
      <Text size="xs" c="dimmed" mb="sm">Help contacts are managed in <Anchor component={Link} to="/safety?tab=help" size="xs">Safety Center → Help contacts</Anchor>. On-call SOS phones: <code>safety.oncall_phones</code> (comma-separated E.164).</Text>
      <Tabs defaultValue={groups[0]?.[0]} orientation="vertical" variant="pills" keepMounted={false} key={search}>
        <ScrollArea type="auto" style={{ flexShrink: 0 }} mah="75vh">
          <Tabs.List miw={200}>
            {groups.map(([c, items]) => (
              <Tabs.Tab key={c} value={c} rightSection={<Badge size="xs" variant="light" color={items.some((s) => s.key in draft) ? 'orange' : 'gray'}>{items.length}</Badge>}>
                {TITLES[c] || humanize(c)}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </ScrollArea>
        {groups.map(([c, items]) => (
          <Tabs.Panel key={c} value={c} pl="md">
            <Card withBorder radius="md" padding="md">
              <Stack gap="md">
                {items.map((s) => (
                  <Field key={s.key} s={s} value={s.key in draft ? draft[s.key] : s.value} disabled={!editable}
                    onChange={(v) => setDraft((d) => {
                      const n = { ...d, [s.key]: v };
                      if (JSON.stringify(v) === JSON.stringify(s.value)) delete n[s.key];
                      return n;
                    })} />
                ))}
              </Stack>
            </Card>
          </Tabs.Panel>
        ))}
      </Tabs>
    </>
  );
}
