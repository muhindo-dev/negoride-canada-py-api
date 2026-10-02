import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Anchor, Badge, Box, Button, Card, Checkbox, Divider, Group, NumberInput, ScrollArea, SimpleGrid, Stack, Switch, Tabs, TagsInput, Text, Textarea, TextInput, Tooltip,
} from '@mantine/core';
import { FiRotateCcw, FiSearch } from 'react-icons/fi';
import { http } from '../lib/api';
import { humanize, money } from '../lib/format';
import { useRoles } from '../lib/roles';
import { PROVINCE_NAMES } from '../lib/geo';
import { ErrorBox, Loading, notifyErr, notifyOk, PageHeader } from '../components/ui';

const ORDER = ['flags', 'app', 'pricing', 'cancellation', 'ride', 'safety', 'onboarding', 'ratings', 'company', 'identity', 'support', 'eta', 'custom'];
const TITLES = {
  flags: 'Feature flags', pricing: 'Fees & commission', cancellation: 'Cancellation, waiting & strikes', ride: 'Ride rules & geofences',
  safety: 'Safety, tracking & recordings', onboarding: 'Driver onboarding & background checks', ratings: 'Ratings & tips', identity: 'Phone verification & legal',
  support: 'Support SLAs', eta: 'ETA', app: 'App & services', company: 'Company & receipts', custom: 'Custom',
};
// Sub-section titles by key prefix (a category mixes several prefixes).
const PREFIX_TITLES = {
  ff: 'Flags', tracking: 'Live tracking', recording: 'Recordings', safety: 'Safety', tip: 'Tips', ratings: 'Ratings',
  receipts: 'Receipts', company: 'Company', carhire: 'Car hire', ride: 'Ride', services: 'Services', app: 'App',
  onboarding: 'Onboarding', otp: 'OTP', legal: 'Legal', pricing: 'Pricing', cancellation: 'Cancellation', strikes: 'Strikes',
  eta: 'ETA', support: 'Support', rideshare: 'Rideshare', geofence: 'Geofences',
};

export const SERVICES = [
  { value: 'car_hire', label: 'Car hire', hint: 'On-demand negotiation' },
  { value: 'rideshare', label: 'Rideshare', hint: 'Scheduled seats' },
  { value: 'courier', label: 'Courier', hint: 'Parcels' },
  { value: 'movers', label: 'Movers', hint: 'Moving help' },
  { value: 'airport', label: 'Airport', hint: 'Pickup / drop-off' },
  { value: 'special_car', label: 'Special car', hint: 'Premium / event' },
];

const DOC_TYPES = ['licence_front', 'licence_back', 'registration', 'insurance', 'vehicle_front', 'vehicle_back', 'vehicle_left', 'vehicle_right', 'vehicle_interior', 'selfie'];
// Comma-separated string settings edited as tag lists (+ suggestions).
const CSV_KEYS = {
  'safety.oncall_phones': { placeholder: '+14165550100', validate: (t) => /^\+[1-9]\d{7,14}$/.test(t) || 'must be E.164, e.g. +14165550100' },
  'otp.allowed_countries': { data: ['CA', 'US'] },
  'onboarding.allowed_provinces': { data: Object.keys(PROVINCE_NAMES) },
  'onboarding.rideshare_endorsement_provinces': { data: Object.keys(PROVINCE_NAMES) },
  'onboarding.required_documents': { data: DOC_TYPES },
  'onboarding.allowed_licence_classes': {},
  'onboarding.certn_check_types': {},
  'onboarding.expiry_reminder_days': { validate: (t) => /^\d+$/.test(t) || 'must be a number of days' },
};

function hint(key, value) {
  if (value === null || value === undefined || value === '') return null;
  if (/_cents$/.test(key)) return money(value);
  if (/_s$/.test(key)) return `${value}s = ${(value / 60).toFixed(1)} min`;
  if (/_min$/.test(key)) return `${value} min`;
  if (/_m$/.test(key)) return `${value} m`;
  if (/_km$/.test(key)) return `${value} km`;
  if (/_pct$/.test(key)) return `${value}%`;
  if (/_h$/.test(key)) return `${value} h${value >= 48 ? ` = ${(value / 24).toFixed(1)} days` : ''}`;
  if (/_days$/.test(key)) return `${value} days`;
  return null;
}

const splitCsv = (v) => String(v ?? '').split(',').map((x) => x.trim()).filter(Boolean);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const fmtDefault = (d) => (Array.isArray(d) ? d.join(', ') : typeof d === 'boolean' ? (d ? 'on' : 'off') : d === '' ? '(empty)' : String(d));

function Label({ s, changed }) {
  return (
    <Group gap={6} wrap="nowrap">
      <Text size="sm" ff="monospace" fw={500}>{s.key}</Text>
      {changed && <Badge size="xs" color="orange" variant="filled">unsaved</Badge>}
      {s.overridden && <Badge size="xs" variant="light">custom</Badge>}
      {s.is_public && <Tooltip label="Served to the apps via /api/app/config"><Badge size="xs" variant="outline" color="gray">public</Badge></Tooltip>}
    </Group>
  );
}

function JsonField({ s, value, onChange, disabled, label, desc }) {
  const [text, setText] = useState(() => (typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
  const [err, setErr] = useState(null);
  return (
    <Textarea
      label={label} description={desc} value={text} disabled={disabled} autosize minRows={2} error={err}
      styles={{ input: { fontFamily: 'monospace', fontSize: 12 } }}
      onChange={(e) => {
        const t = e.currentTarget.value;
        setText(t);
        try { onChange(JSON.parse(t)); setErr(null); } catch (x) { setErr(`Invalid JSON: ${x.message}`); onChange({ __invalid: t }); }
      }}
    />
  );
}

function Field({ s, value, onChange, disabled, changed }) {
  const label = <Label s={s} changed={changed} />;
  const extra = hint(s.key, value);
  const desc = <>{s.description}{extra ? ` · ${extra}` : ''}{s.default !== null && s.default !== undefined ? ` · default ${fmtDefault(s.default)}` : ''}</>;

  if (s.key === 'services.enabled') {
    const v = Array.isArray(value) ? value : [];
    return (
      <Stack gap={4} data-testid="setting-services">
        {label}
        <Text size="xs" c="dimmed">{s.description || 'Services offered in the apps (GET /api/app/config → services) and in driver onboarding.'}</Text>
        <Checkbox.Group value={v} onChange={(nv) => onChange(SERVICES.map((x) => x.value).filter((x) => nv.includes(x)))}>
          <SimpleGrid cols={{ base: 2, sm: 3 }} spacing="xs" mt={4}>
            {SERVICES.map((x) => (
              <Checkbox key={x.value} value={x.value} disabled={disabled} label={x.label} description={x.hint} />
            ))}
          </SimpleGrid>
        </Checkbox.Group>
        {!v.length && <Text size="xs" c="red">At least one service must stay enabled.</Text>}
      </Stack>
    );
  }
  if (s.type === 'bool') {
    return (
      <Group justify="space-between" wrap="nowrap" align="flex-start" py={2}>
        <Box style={{ minWidth: 0 }}>
          {label}
          <Text size="xs" c="dimmed">{s.description}{s.default !== null && s.default !== undefined ? ` · default ${fmtDefault(s.default)}` : ''}</Text>
        </Box>
        <Switch checked={!!value} onChange={(e) => onChange(e.currentTarget.checked)} disabled={disabled} onLabel="ON" offLabel="OFF" size="md" aria-label={s.key} />
      </Group>
    );
  }
  if (s.type === 'int' || s.type === 'float') {
    return <NumberInput label={label} description={desc} value={value ?? ''} onChange={(v) => onChange(v === '' ? null : v)} disabled={disabled} decimalScale={s.type === 'int' ? 0 : 4} allowDecimal={s.type !== 'int'} maw={420} />;
  }
  if (s.type === 'json') {
    const isList = Array.isArray(value) || Array.isArray(s.default);
    if (isList && (value || []).every((x) => typeof x !== 'object')) {
      return <TagsInput label={label} description={desc} value={(value || []).map(String)} onChange={onChange} disabled={disabled} clearable maw={620} splitChars={[',', ' ']} />;
    }
    return <JsonField s={s} value={value} onChange={onChange} disabled={disabled} label={label} desc={desc} />;
  }
  const csv = CSV_KEYS[s.key];
  if (csv) {
    const tags = splitCsv(value);
    const bad = csv.validate ? tags.map((t) => [t, csv.validate(t)]).filter(([, r]) => r !== true) : [];
    return (
      <TagsInput
        label={label} description={desc} value={tags} data={csv.data} placeholder={csv.placeholder} disabled={disabled} clearable maw={720}
        splitChars={[',', ' ']} onChange={(t) => onChange(t.map((x) => x.trim()).filter(Boolean).join(','))}
        error={bad.length ? bad.map(([t, r]) => `${t}: ${r}`).join(' · ') : undefined}
      />
    );
  }
  if (String(value ?? '').length > 90 || /_text(_fr)?$|address$/.test(s.key)) {
    return <Textarea label={label} description={desc} value={value ?? ''} onChange={(e) => onChange(e.currentTarget.value)} disabled={disabled} autosize minRows={2} maw={720} />;
  }
  return <TextInput label={label} description={desc} value={value ?? ''} onChange={(e) => onChange(e.currentTarget.value)} disabled={disabled} maw={620} />;
}

function prefixOf(key) {
  return key.includes('.') ? key.split('.')[0] : 'other';
}

export default function Settings() {
  const qc = useQueryClient();
  const { can } = useRoles();
  const editable = can('settingsEdit');
  const [sp] = useSearchParams();
  const q = useQuery({ queryKey: ['settings'], queryFn: () => http.get('/admin/settings') });
  const [draft, setDraft] = useState({});
  const [search, setSearch] = useState(sp.get('q') || '');
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
  const invalid = changed.filter((k) => draft[k] && typeof draft[k] === 'object' && !Array.isArray(draft[k]) && '__invalid' in draft[k]);
  const emptyServices = 'services.enabled' in draft && !(draft['services.enabled'] || []).length;
  const setValue = (s, v) => setDraft((d) => {
    const n = { ...d, [s.key]: v };
    if (same(v, s.value)) delete n[s.key];
    return n;
  });
  const save = async () => {
    setBusy(true);
    try {
      const values = {};
      changed.forEach((k) => { values[k] = draft[k]; });
      const r = await http.postFull('/admin/settings', { values });
      notifyOk(`${r.message} · audited as settings.update`);
      setDraft({});
      qc.invalidateQueries({ queryKey: ['settings'] });
      qc.invalidateQueries({ queryKey: ['readiness'] });
    } catch (e) { notifyErr(e, 'Save failed'); } finally { setBusy(false); }
  };
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const firstTab = groups.find(([, items]) => items.some((s) => s.key === search))?.[0] || groups[0]?.[0];
  return (
    <>
      <PageHeader title="Settings" subtitle="Every app_settings value, by category · changes apply immediately (≈30 s cache) and are audited with before/after"
        actions={<>
          <TextInput size="xs" leftSection={<FiSearch />} placeholder="Filter settings" value={search} onChange={(e) => setSearch(e.currentTarget.value)} data-testid="settings-search" />
          {changed.length > 0 && <Button size="xs" variant="default" leftSection={<FiRotateCcw />} onClick={() => setDraft({})}>Discard</Button>}
          {editable && <Button size="xs" onClick={save} loading={busy} disabled={!changed.length || invalid.length > 0 || emptyServices} data-testid="settings-save">Save {changed.length || ''} change{changed.length === 1 ? '' : 's'}</Button>}
        </>} />
      {!editable && <Alert color="gray" mb="sm">Read-only: editing settings needs the Ops, Finance or Super admin role.</Alert>}
      {changed.length > 0 && (
        <Alert color="orange" variant="light" mb="sm" py={6}>
          Unsaved: {changed.map((k) => <Text key={k} span ff="monospace" size="xs" mr={8}>{k}</Text>)}
          {invalid.length > 0 && <Text size="xs" c="red">Fix invalid JSON first: {invalid.join(', ')}</Text>}
        </Alert>
      )}
      <Text size="xs" c="dimmed" mb="sm">Help contacts are managed in <Anchor component={Link} to="/safety?tab=help" size="xs">Safety Center → Help contacts</Anchor>. Tax rates: <Anchor component={Link} to="/finance?tab=taxrates" size="xs">Finance → Tax rates</Anchor>. Every change is written to the <Anchor component={Link} to="/audit" size="xs">audit log</Anchor>.</Text>
      {!groups.length && <Text c="dimmed">No setting matches “{search}”.</Text>}
      <Tabs defaultValue={firstTab} orientation="vertical" variant="pills" keepMounted={false} key={`${search}-${firstTab}`}>
        <ScrollArea type="auto" style={{ flexShrink: 0 }} mah="75vh">
          <Tabs.List miw={220}>
            {groups.map(([c, items]) => (
              <Tabs.Tab key={c} value={c} rightSection={<Badge size="xs" variant="light" color={items.some((s) => s.key in draft) ? 'orange' : 'gray'}>{items.length}</Badge>}>
                {TITLES[c] || humanize(c)}
              </Tabs.Tab>
            ))}
          </Tabs.List>
        </ScrollArea>
        {groups.map(([c, items]) => {
          const byPrefix = {};
          items.forEach((s) => { (byPrefix[prefixOf(s.key)] ||= []).push(s); });
          const prefixes = Object.keys(byPrefix);
          const bools = (list) => list.filter((s) => s.type === 'bool');
          const others = (list) => list.filter((s) => s.type !== 'bool');
          return (
            <Tabs.Panel key={c} value={c} pl="md">
              <Card withBorder radius="md" padding="md">
                <Stack gap="lg">
                  {c === 'pricing' && (
                    <Alert color="blue" variant="light" title="How the typical fare is estimated">
                      Uses route distance, estimated driving time, the selected service type, and recent completed trips when enough history exists. The starting values use Toronto as a Canadian reference and should be tuned for each operating market. This is a guide for the rider’s offer, not a fixed or guaranteed fare.
                    </Alert>
                  )}
                  {prefixes.map((pfx) => (
                    <Stack key={pfx} gap="md">
                      {prefixes.length > 1 && <Divider label={<Text size="xs" fw={700} tt="uppercase" c="dimmed">{PREFIX_TITLES[pfx] || humanize(pfx)} · {pfx}.*</Text>} labelPosition="left" />}
                      {bools(byPrefix[pfx]).length > 0 && (
                        <Card withBorder radius="sm" padding="xs">
                          <Stack gap={6}>
                            {bools(byPrefix[pfx]).map((s, i) => (
                              <React.Fragment key={s.key}>
                                {i > 0 && <Divider />}
                                <Field s={s} value={s.key in draft ? draft[s.key] : s.value} disabled={!editable} changed={s.key in draft} onChange={(v) => setValue(s, v)} />
                              </React.Fragment>
                            ))}
                          </Stack>
                        </Card>
                      )}
                      {others(byPrefix[pfx]).map((s) => (
                        <Group key={s.key} align="flex-end" gap="xs" wrap="nowrap">
                          <Box style={{ flex: 1, minWidth: 0 }}>
                            <Field s={s} value={s.key in draft ? draft[s.key] : s.value} disabled={!editable} changed={s.key in draft} onChange={(v) => setValue(s, v)} />
                          </Box>
                          {editable && s.default !== null && s.default !== undefined && !same(s.key in draft ? draft[s.key] : s.value, s.default) && (
                            <Tooltip label={`Reset to default: ${fmtDefault(s.default)}`} withArrow>
                              <Button size="compact-xs" variant="subtle" color="gray" onClick={() => setValue(s, s.default)} aria-label={`Reset ${s.key}`}><FiRotateCcw /></Button>
                            </Tooltip>
                          )}
                        </Group>
                      ))}
                    </Stack>
                  ))}
                </Stack>
              </Card>
            </Tabs.Panel>
          );
        })}
      </Tabs>
    </>
  );
}
