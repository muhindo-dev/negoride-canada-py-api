import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Anchor, Badge, Button, Card, Chip, Grid, Group, NumberInput, ScrollArea, Select, Stack, Switch, Tabs, Text, TextInput,
} from '@mantine/core';
import { FiCrosshair, FiPlayCircle, FiX } from 'react-icons/fi';
import { DRIVER_STATE_COLOR, DRIVER_STATE_LABEL, useLiveDrivers } from '../lib/liveDrivers';
import { ago, humanize, RIDE_TYPES } from '../lib/format';
import MapView, { MAP_PROVIDER } from '../components/map/MapView';
import RouteReplay from '../components/RouteReplay';
import { ErrorBox, KV, PageHeader, RideLink, StageBadge, UserLink } from '../components/ui';

const STATES = ['idle', 'en_route', 'on_trip', 'sos'];

function DriverPanel({ d, follow, setFollow, onClose, onReplay }) {
  return (
    <Card withBorder radius="md" padding="sm">
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Badge color={d.state === 'sos' ? 'red' : d.state === 'on_trip' ? 'orange' : d.state === 'en_route' ? 'blue' : 'gray'}>{DRIVER_STATE_LABEL[d.state]}</Badge>
          <Text fw={600}>{d.name || d.first_name}</Text>
        </Group>
        <Button size="compact-xs" variant="subtle" onClick={onClose} leftSection={<FiX />}>Close</Button>
      </Group>
      <KV items={[
        ['Driver', <UserLink id={d.driver_id} name={`#${d.driver_id} ${d.name || ''}`} />],
        ['Online', d.online ? 'Yes' : 'No (active ride)'],
        ['Rating', d.rating ?? '—'],
        ['Last position', d.position ? `${ago(d.position.at)}${d.stale ? ' (stale)' : ''}${d.live ? ' · live' : ''}` : 'unknown'],
        d.position && ['Coordinates', `${Number(d.position.lat).toFixed(5)}, ${Number(d.position.lng).toFixed(5)}`],
        d.position?.speed !== null && d.position?.speed !== undefined && ['Speed', `${Math.round(Number(d.position.speed) * 3.6)} km/h`],
        d.ride && ['Ride', <RideLink type={d.ride.ride_type} id={d.ride.ride_id} />],
        d.ride && ['Stage', <StageBadge stage={d.ride.stage} />],
        d.ride && ['Customers', (d.ride.customer_ids || []).map((c, i) => <UserLink key={c} id={c} name={d.ride.customer_first_names?.[i] || `#${c}`} />)],
        d.incident_id && ['SOS', <Anchor component={Link} to={`/safety/incidents/${d.incident_id}`} c="red">Incident #{d.incident_id}</Anchor>],
      ]} />
      <Group mt="sm" gap="xs">
        <Switch label="Follow" checked={follow} onChange={(e) => setFollow(e.currentTarget.checked)} />
        {d.ride && <Button size="xs" variant="light" leftSection={<FiPlayCircle />} onClick={() => onReplay(d.ride.ride_type, d.ride.ride_id)}>Route so far</Button>}
      </Group>
    </Card>
  );
}

export default function LiveMap() {
  const [sp, setSp] = useSearchParams();
  const [states, setStates] = useState(STATES);
  const [search, setSearch] = useState('');
  const [hideStale, setHideStale] = useState(false);
  const [sel, setSel] = useState(null);
  const [follow, setFollow] = useState(false);
  const [tab, setTab] = useState(sp.get('replay') ? 'replay' : 'live');
  const [rt, setRt] = useState(sp.get('type') || 'carhire');
  const [rid, setRid] = useState(sp.get('replay') ? Number(sp.get('replay')) : '');
  const [replay, setReplay] = useState(sp.get('replay') ? { type: sp.get('type') || 'carhire', id: sp.get('replay') } : null);
  const { drivers, counts, error, isLoading, generatedAt } = useLiveDrivers({ interval: 10000 });

  const shown = useMemo(() => drivers.filter((d) => states.includes(d.state)
    && (!hideStale || !d.stale)
    && (!search || `${d.name} ${d.driver_id}`.toLowerCase().includes(search.toLowerCase()))), [drivers, states, search, hideStale]);
  const selected = drivers.find((d) => d.driver_id === sel);
  const markers = shown.filter((d) => d.position).map((d) => ({
    id: `d${d.driver_id}`, lat: Number(d.position.lat), lng: Number(d.position.lng), color: DRIVER_STATE_COLOR[d.state],
    radius: d.driver_id === sel ? 11 : d.state === 'sos' ? 10 : 7, ring: d.driver_id === sel ? '#000' : d.stale ? '#adb5bd' : '#fff',
    ringWeight: d.driver_id === sel ? 3 : 2,
    label: `${d.name || d.first_name} · ${DRIVER_STATE_LABEL[d.state]}${d.stale ? ' · stale' : ''}`,
    onClick: () => setSel(d.driver_id),
  }));
  const startReplay = (type, id) => {
    setReplay({ type, id: String(id) });
    setRt(type);
    setRid(Number(id));
    setTab('replay');
    setSp({ replay: String(id), type });
  };

  return (
    <>
      <PageHeader
        title="Live Operations Map"
        subtitle={`Every online driver, coloured by state · ${MAP_PROVIDER === 'google' ? 'Google Maps' : 'OpenStreetMap'} · updated ${ago(generatedAt)}`}
      />
      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="live">Live drivers</Tabs.Tab>
          <Tabs.Tab value="replay">Route replay</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="live">
          <ErrorBox error={error} />
          <Group mb="sm" gap="xs" wrap="wrap">
            <Chip.Group multiple value={states} onChange={setStates}>
              {STATES.map((s) => (
                <Chip key={s} value={s} size="xs" color={s === 'sos' ? 'red' : s === 'on_trip' ? 'orange' : s === 'en_route' ? 'blue' : 'gray'}>
                  {DRIVER_STATE_LABEL[s]} {counts ? `(${counts[s] ?? 0})` : ''}
                </Chip>
              ))}
            </Chip.Group>
            <TextInput size="xs" placeholder="Search driver" value={search} onChange={(e) => setSearch(e.currentTarget.value)} w={180} />
            <Switch size="xs" label="Hide stale (>10 min)" checked={hideStale} onChange={(e) => setHideStale(e.currentTarget.checked)} />
          </Group>
          <Grid gutter="sm">
            <Grid.Col span={{ base: 12, md: 8 }}>
              <MapView
                height="calc(100vh - 260px)"
                markers={markers}
                fitKey={isLoading ? undefined : 'initial'}
                follow={follow && selected?.position ? [Number(selected.position.lat), Number(selected.position.lng)] : null}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Stack gap="sm">
                {selected && (
                  <DriverPanel d={selected} follow={follow} setFollow={setFollow} onClose={() => { setSel(null); setFollow(false); }} onReplay={startReplay} />
                )}
                <Card withBorder radius="md" padding={0}>
                  <Text fw={600} p="sm" pb={4}>Drivers ({shown.length})</Text>
                  <ScrollArea h={selected ? 260 : 520}>
                    {shown.map((d) => (
                      <Group
                        key={d.driver_id} px="sm" py={6} justify="space-between" wrap="nowrap"
                        onClick={() => setSel(d.driver_id)}
                        style={{ cursor: 'pointer', background: d.driver_id === sel ? 'var(--mantine-color-default-hover)' : undefined }}
                      >
                        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
                          <span style={{ width: 10, height: 10, borderRadius: 5, background: DRIVER_STATE_COLOR[d.state], flexShrink: 0 }} />
                          <Text size="sm" truncate>{d.name || d.first_name || `#${d.driver_id}`}</Text>
                        </Group>
                        <Group gap={4} wrap="nowrap">
                          {d.ride && <StageBadge stage={d.ride.stage} size="xs" />}
                          {!d.position && <Badge size="xs" color="gray" variant="outline">no GPS</Badge>}
                          <Button size="compact-xs" variant="subtle" onClick={(e) => { e.stopPropagation(); setSel(d.driver_id); setFollow(true); }} aria-label="Follow"><FiCrosshair /></Button>
                        </Group>
                      </Group>
                    ))}
                    {!shown.length && <Text size="sm" c="dimmed" p="sm">No drivers match.</Text>}
                  </ScrollArea>
                </Card>
              </Stack>
            </Grid.Col>
          </Grid>
        </Tabs.Panel>
        <Tabs.Panel value="replay">
          <Group mb="sm" align="flex-end" gap="xs" wrap="wrap">
            <Select label="Ride type" value={rt} onChange={(v) => setRt(v)} data={Object.entries(RIDE_TYPES).map(([value, label]) => ({ value, label }))} w={180} allowDeselect={false} />
            <NumberInput label="Ride ID" value={rid} onChange={setRid} w={140} min={1} hideControls />
            <Button onClick={() => rid && startReplay(rt, rid)} leftSection={<FiPlayCircle />}>Load route</Button>
            {replay && <Anchor component={Link} to={`/rides/${replay.type}/${replay.id}`} size="sm">Open ride detail</Anchor>}
          </Group>
          {replay ? (
            <RouteReplay rideType={replay.type} rideId={replay.id} height="calc(100vh - 330px)" />
          ) : <Text c="dimmed" size="sm">Pick a ride (or a driver on the live tab) to replay its recorded route with a time slider.</Text>}
          <Text size="xs" c="dimmed" mt="xs">Tip: {humanize('completed rides keep breadcrumbs for the retention window')}.</Text>
        </Tabs.Panel>
      </Tabs>
    </>
  );
}
