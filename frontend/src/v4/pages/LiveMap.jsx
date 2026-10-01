import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Anchor, Badge, Button, Card, Chip, Grid, Group, MultiSelect, NumberInput, ScrollArea, SegmentedControl, Select, Stack, Switch, Tabs, Text, TextInput, Tooltip,
} from '@mantine/core';
import { FiAlertOctagon, FiCrosshair, FiPlayCircle, FiX } from 'react-icons/fi';
import { DRIVER_STATE_COLOR, DRIVER_STATE_LABEL, useLiveDrivers } from '../lib/liveDrivers';
import { useLiveRides } from '../lib/liveRides';
import { CITIES, inArea, PROVINCE_NAMES } from '../lib/geo';
import { ago, humanize, money, RIDE_TYPES } from '../lib/format';
import MapView, { MAP_PROVIDER } from '../components/map/MapView';
import RouteReplay from '../components/RouteReplay';
import { ErrorBox, KV, PageHeader, RideLink, StageBadge, UserLink } from '../components/ui';

const STATES = ['idle', 'en_route', 'on_trip', 'sos'];
const LAYERS = [
  { value: 'drivers', label: 'Drivers', color: 'gray' },
  { value: 'requests', label: 'Open requests', color: 'violet' },
  { value: 'trips', label: 'Rideshare trips', color: 'teal' },
  { value: 'sos', label: 'SOS', color: 'red' },
];
const LIVE_RIDE_TYPES = ['carhire', 'scheduled', 'rideshare_trip'];
const LAYER_COLOR = { request: '#7048e8', trip: '#0ca678', sos: '#e03131' };
const KNOWN_SERVICES = ['car_hire', 'rideshare', 'courier', 'movers', 'airport', 'special_car'];

const num = (v) => (v === null || v === undefined || v === '' ? NaN : Number(v));
const hasPos = (p) => p && Number.isFinite(num(p.lat)) && Number.isFinite(num(p.lng));

const AREA_OPTIONS = [
  { group: 'Cities', items: CITIES.map((c) => ({ value: `city:${c.key}`, label: c.label })) },
  { group: 'Provinces & territories', items: Object.entries(PROVINCE_NAMES).map(([k, v]) => ({ value: `prov:${k}`, label: `${v} (${k})` })) },
];

function DriverPanel({ d, follow, setFollow, onClose, onReplay }) {
  return (
    <Card withBorder radius="md" padding="sm" data-testid="panel-driver">
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Badge color={d.state === 'sos' ? 'red' : d.state === 'on_trip' ? 'orange' : d.state === 'en_route' ? 'blue' : 'gray'}>{DRIVER_STATE_LABEL[d.state]}</Badge>
          <Text fw={600}>{d.name || d.first_name}</Text>
        </Group>
        <Button size="compact-xs" variant="subtle" onClick={onClose} leftSection={<FiX />}>Close</Button>
      </Group>
      <KV items={[
        ['Driver', <UserLink id={d.driver_id} name={`#${d.driver_id} ${d.name || ''}`} />],
        ['Online', d.online ? 'Yes' : 'No (shown because of an active ride)'],
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

function RequestPanel({ r, onClose }) {
  return (
    <Card withBorder radius="md" padding="sm" data-testid="panel-request">
      <Group justify="space-between" mb="xs">
        <Group gap="xs"><Badge color="violet">{r.kind === 'ride_request' ? 'Ride request' : 'Negotiation'}</Badge><Text fw={600}>#{r.id}</Text></Group>
        <Button size="compact-xs" variant="subtle" onClick={onClose} leftSection={<FiX />}>Close</Button>
      </Group>
      <KV items={[
        ['Status', <Badge size="sm" variant="light">{humanize(r.status)}</Badge>],
        r.mode && ['Mode', humanize(r.mode)],
        ['Service', humanize(r.service_type)],
        ['Customer', <UserLink id={r.customer?.id} name={r.customer?.first_name} />],
        ['Pickup', r.pickup?.address], ['Drop-off', r.dropoff?.address],
        ['Offer', money(r.offer_cents)],
        r.driver_id && ['Driver', <UserLink id={r.driver_id} />],
        ['Created', ago(r.created_at)],
        r.expires_at && ['Expires', ago(r.expires_at)],
        (r.kind === 'negotiation' || r.negotiation_id) && ['Ride', <RideLink type="carhire" id={r.kind === 'negotiation' ? r.id : r.negotiation_id} />],
      ]} />
    </Card>
  );
}

function TripPanel({ t, follow, setFollow, onClose, onReplay }) {
  return (
    <Card withBorder radius="md" padding="sm" data-testid="panel-trip">
      <Group justify="space-between" mb="xs">
        <Group gap="xs"><Badge color="teal">Rideshare trip</Badge><Text fw={600}>#{t.trip_id}</Text><StageBadge stage={t.stage} size="xs" /></Group>
        <Button size="compact-xs" variant="subtle" onClick={onClose} leftSection={<FiX />}>Close</Button>
      </Group>
      <KV items={[
        ['Driver', <UserLink id={t.driver?.id} name={t.driver?.first_name} />],
        ['From', t.start?.address], ['To', t.end?.address],
        ['Passengers', `${t.passengers} / ${t.seats ?? '—'} seats`],
        ['Departure', t.departure_at ? ago(t.departure_at) : '—'],
        t.started_at && ['Started', ago(t.started_at)],
        ['Position', t.position ? `${t.position.source === 'live' ? 'live' : 'last known'} · ${ago(t.position.at)}` : 'unknown'],
        ['Ride', <RideLink type="rideshare_trip" id={t.trip_id} />],
      ]} />
      <Group mt="sm" gap="xs">
        <Switch label="Follow" checked={follow} onChange={(e) => setFollow(e.currentTarget.checked)} />
        <Button size="xs" variant="light" leftSection={<FiPlayCircle />} onClick={() => onReplay('rideshare_trip', t.trip_id)}>Route so far</Button>
      </Group>
    </Card>
  );
}

function SosPanel({ s, follow, setFollow, onClose }) {
  return (
    <Card withBorder radius="md" padding="sm" data-testid="panel-sos" style={{ borderColor: 'var(--mantine-color-red-6)' }}>
      <Group justify="space-between" mb="xs">
        <Group gap="xs"><Badge color="red" leftSection={<FiAlertOctagon size={10} />}>SOS</Badge><Text fw={600}>#{s.incident_id}</Text><Badge size="xs" variant="light" color={s.status === 'open' ? 'red' : 'orange'}>{humanize(s.status)}</Badge>{s.silent && <Badge size="xs" color="dark">silent</Badge>}</Group>
        <Button size="compact-xs" variant="subtle" onClick={onClose} leftSection={<FiX />}>Close</Button>
      </Group>
      <KV items={[
        ['User', <UserLink id={s.user?.id} name={`${s.user?.first_name || `#${s.user?.id}`} (${s.user?.role || '?'})`} />],
        ['Ride', s.ride_type ? <RideLink type={s.ride_type} id={s.ride_id} /> : <Text span size="sm" c="orange">No ride — standalone SOS</Text>],
        ['Position', s.position ? `${s.live ? 'live' : humanize(s.position.source)} · ${ago(s.position.at)}${s.position.accuracy_m ? ` · ±${Math.round(s.position.accuracy_m)} m` : ''}` : 'unknown'],
        s.position && ['Coordinates', `${Number(s.position.lat).toFixed(5)}, ${Number(s.position.lng).toFixed(5)}`],
        ['Battery', s.battery_pct !== null && s.battery_pct !== undefined ? `${s.battery_pct}%` : '—'],
        ['Raised', ago(s.created_at)],
        s.acknowledged_at && ['Acknowledged', ago(s.acknowledged_at)],
        s.escalated_at && ['Escalated', ago(s.escalated_at)],
      ]} />
      <Group mt="sm" gap="xs">
        <Switch label="Follow" checked={follow} onChange={(e) => setFollow(e.currentTarget.checked)} />
        <Button size="xs" color="red" variant="light" component={Link} to={`/safety/incidents/${s.incident_id}`}>Open incident</Button>
      </Group>
    </Card>
  );
}

function Legend() {
  const dot = (c, r = 10, ring = '#fff') => <span style={{ width: r, height: r, borderRadius: r, background: c, border: `2px solid ${ring}`, boxShadow: '0 0 0 1px rgba(0,0,0,.25)', display: 'inline-block' }} />;
  return (
    <Group gap="md" wrap="wrap">
      {STATES.map((s) => <Group key={s} gap={4}>{dot(DRIVER_STATE_COLOR[s])}<Text size="xs">{DRIVER_STATE_LABEL[s]} driver</Text></Group>)}
      <Group gap={4}>{dot(LAYER_COLOR.request, 9)}<Text size="xs">Open request (pickup)</Text></Group>
      <Group gap={4}>{dot(LAYER_COLOR.trip, 12, '#000')}<Text size="xs">Rideshare trip</Text></Group>
      <Group gap={4}>{dot(LAYER_COLOR.sos, 14, '#000')}<Text size="xs">SOS</Text></Group>
    </Group>
  );
}

function ListRow({ active, color, title, right, onClick, testid }) {
  return (
    <Group
      px="sm" py={6} justify="space-between" wrap="nowrap" onClick={onClick} data-testid={testid}
      style={{ cursor: 'pointer', background: active ? 'var(--mantine-color-default-hover)' : undefined }}
    >
      <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
        <span style={{ width: 10, height: 10, borderRadius: 5, background: color, flexShrink: 0 }} />
        <Text size="sm" truncate>{title}</Text>
      </Group>
      <Group gap={4} wrap="nowrap">{right}</Group>
    </Group>
  );
}

export default function LiveMap() {
  const [sp, setSp] = useSearchParams();
  const [layers, setLayers] = useState(['drivers', 'requests', 'trips', 'sos']);
  const [states, setStates] = useState(STATES);
  const [rideTypes, setRideTypes] = useState([]);
  const [services, setServices] = useState([]);
  const [area, setArea] = useState(sp.get('area') || '');
  const [offlineActive, setOfflineActive] = useState(true);
  const [search, setSearch] = useState('');
  const [hideStale, setHideStale] = useState(false);
  const [sel, setSel] = useState(null); // {type: driver|request|trip|sos, id}
  const [follow, setFollow] = useState(false);
  const [listTab, setListTab] = useState('drivers');
  const [tab, setTab] = useState(sp.get('replay') ? 'replay' : 'live');
  const [rt, setRt] = useState(sp.get('type') || 'carhire');
  const [rid, setRid] = useState(sp.get('replay') ? Number(sp.get('replay')) : '');
  const [replay, setReplay] = useState(sp.get('replay') ? { type: sp.get('type') || 'carhire', id: sp.get('replay') } : null);
  const drv = useLiveDrivers({ interval: 10000, includeOfflineActive: offlineActive });
  const live = useLiveRides();
  const { drivers, counts } = drv;

  const serviceOptions = useMemo(() => {
    const seen = new Set(KNOWN_SERVICES);
    live.requests.forEach((r) => r.service_type && seen.add(r.service_type));
    return [...seen].map((s) => ({ value: s, label: humanize(s) }));
  }, [live.requests]);

  const q = search.trim().toLowerCase();
  const rtOk = (t) => !rideTypes.length || rideTypes.includes(t);
  const shownDrivers = useMemo(() => (layers.includes('drivers') ? drivers : []).filter((d) => states.includes(d.state)
    && (!hideStale || !d.stale)
    && (!rideTypes.length || (d.ride && rideTypes.includes(d.ride.ride_type)))
    && (!area || (d.position && inArea(area, d.position.lat, d.position.lng)))
    && (!q || `${d.name} ${d.first_name} ${d.driver_id}`.toLowerCase().includes(q))), [drivers, layers, states, hideStale, rideTypes, area, q]);
  const shownRequests = useMemo(() => (layers.includes('requests') ? live.requests : []).filter((r) => rtOk(r.ride_type || 'carhire')
    && (!services.length || services.includes(r.service_type))
    && (!area || (hasPos(r.pickup) && inArea(area, r.pickup.lat, r.pickup.lng)))
    && (!q || `${r.id} ${r.customer?.first_name || ''} ${r.pickup?.address || ''} ${r.dropoff?.address || ''}`.toLowerCase().includes(q))), [live.requests, layers, rideTypes, services, area, q]); // eslint-disable-line react-hooks/exhaustive-deps
  const shownTrips = useMemo(() => (layers.includes('trips') ? live.trips : []).filter((t) => rtOk('rideshare_trip')
    && (!area || [t.position, t.start, t.end].some((p) => hasPos(p) && inArea(area, p.lat, p.lng)))
    && (!q || `${t.trip_id} ${t.driver?.first_name || ''} ${t.start?.address || ''} ${t.end?.address || ''}`.toLowerCase().includes(q))), [live.trips, layers, rideTypes, area, q]); // eslint-disable-line react-hooks/exhaustive-deps
  // SOS pins are never hidden by ride-type / service / area / search filters —
  // only by switching the SOS layer off.
  const shownSos = layers.includes('sos') ? live.sos : [];

  const selDriver = sel?.type === 'driver' ? drivers.find((d) => d.driver_id === sel.id) : null;
  const selRequest = sel?.type === 'request' ? live.requests.find((r) => `${r.kind}-${r.id}` === sel.id) : null;
  const selTrip = sel?.type === 'trip' ? live.trips.find((t) => t.trip_id === sel.id) : null;
  const selSos = sel?.type === 'sos' ? live.sos.find((s) => s.incident_id === sel.id) : null;
  const followPos = selDriver?.position || selTrip?.position || selSos?.position || null;
  const pick = (type, id) => { setSel({ type, id }); };
  const isSel = (type, id) => sel?.type === type && sel?.id === id;

  const markers = [
    ...shownDrivers.filter((d) => hasPos(d.position)).map((d) => ({
      id: `d${d.driver_id}`, lat: num(d.position.lat), lng: num(d.position.lng), color: DRIVER_STATE_COLOR[d.state],
      radius: isSel('driver', d.driver_id) ? 11 : d.state === 'sos' ? 10 : 7, ring: isSel('driver', d.driver_id) ? '#000' : d.stale ? '#adb5bd' : '#fff',
      ringWeight: isSel('driver', d.driver_id) ? 3 : 2,
      label: `${d.name || d.first_name} · ${DRIVER_STATE_LABEL[d.state]}${d.online ? '' : ' · offline (active ride)'}${d.stale ? ' · stale' : ''}`,
      onClick: () => pick('driver', d.driver_id),
    })),
    ...shownRequests.filter((r) => hasPos(r.pickup)).map((r) => ({
      id: `r${r.kind}${r.id}`, lat: num(r.pickup.lat), lng: num(r.pickup.lng), color: LAYER_COLOR.request,
      radius: isSel('request', `${r.kind}-${r.id}`) ? 10 : 6, ring: isSel('request', `${r.kind}-${r.id}`) ? '#000' : '#fff',
      label: `Request #${r.id} · ${humanize(r.status)} · ${humanize(r.service_type)} · ${money(r.offer_cents)}`,
      onClick: () => pick('request', `${r.kind}-${r.id}`),
    })),
    ...shownTrips.map((t) => {
      const p = hasPos(t.position) ? t.position : t.start;
      if (!hasPos(p)) return null;
      return {
        id: `t${t.trip_id}`, lat: num(p.lat), lng: num(p.lng), color: LAYER_COLOR.trip, radius: isSel('trip', t.trip_id) ? 12 : 9,
        ring: '#000', ringWeight: isSel('trip', t.trip_id) ? 3 : 2,
        label: `Rideshare #${t.trip_id} · ${humanize(t.stage)} · ${t.passengers}/${t.seats ?? '?'} pax`,
        onClick: () => pick('trip', t.trip_id),
      };
    }).filter(Boolean),
    ...shownSos.filter((s) => hasPos(s.position)).map((s) => ({
      id: `s${s.incident_id}`, lat: num(s.position.lat), lng: num(s.position.lng), color: LAYER_COLOR.sos,
      radius: isSel('sos', s.incident_id) ? 15 : 13, ring: s.status === 'open' ? '#000' : '#fd7e14', ringWeight: 3,
      label: `SOS #${s.incident_id} · ${s.user?.first_name || ''} (${s.user?.role || '?'}) · ${s.ride_type ? `${s.ride_type} #${s.ride_id}` : 'no ride'} · ${humanize(s.status)}`,
      onClick: () => pick('sos', s.incident_id),
    })),
  ];
  const circles = shownSos.filter((s) => hasPos(s.position) && s.position.accuracy_m).map((s) => ({
    id: `sa${s.incident_id}`, lat: num(s.position.lat), lng: num(s.position.lng), radiusM: Math.min(2000, Number(s.position.accuracy_m)),
    color: '#e03131', fillOpacity: 0.12, weight: 1,
  }));
  const polylines = [];
  if (selRequest && hasPos(selRequest.pickup) && hasPos(selRequest.dropoff)) {
    polylines.push({ id: 'req', points: [[num(selRequest.pickup.lat), num(selRequest.pickup.lng)], [num(selRequest.dropoff.lat), num(selRequest.dropoff.lng)]], color: LAYER_COLOR.request, dashed: true, weight: 3 });
    markers.push({ id: 'req-drop', lat: num(selRequest.dropoff.lat), lng: num(selRequest.dropoff.lng), color: '#1c7ed6', radius: 6, label: `Drop-off: ${selRequest.dropoff.address || ''}` });
  }
  if (selTrip && hasPos(selTrip.start) && hasPos(selTrip.end)) {
    polylines.push({ id: 'trip', points: [[num(selTrip.start.lat), num(selTrip.start.lng)], [num(selTrip.end.lat), num(selTrip.end.lng)]], color: LAYER_COLOR.trip, dashed: true, weight: 3 });
    markers.push({ id: 'trip-end', lat: num(selTrip.end.lat), lng: num(selTrip.end.lng), color: '#1c7ed6', radius: 6, label: `To: ${selTrip.end.address || ''}` });
  }

  const startReplay = (type, id) => {
    setReplay({ type, id: String(id) });
    setRt(type);
    setRid(Number(id));
    setTab('replay');
    setSp({ replay: String(id), type });
  };
  const close = () => { setSel(null); setFollow(false); };
  const openSos = live.sos.filter((s) => s.status === 'open').length;
  const filtersOn = rideTypes.length || services.length || area || q;

  return (
    <>
      <PageHeader
        title="Live Operations Map"
        subtitle={`Drivers, open requests, rideshare trips and SOS · ${MAP_PROVIDER === 'google' ? 'Google Maps' : 'OpenStreetMap'} · drivers ${ago(drv.generatedAt)} · rides ${ago(live.generatedAt)} (every ${live.refreshS}s + on events)`}
      />
      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List mb="sm">
          <Tabs.Tab value="live">Live operations</Tabs.Tab>
          <Tabs.Tab value="replay">Route replay</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="live">
          <ErrorBox error={drv.error} title="Drivers unavailable" />
          <ErrorBox error={live.error} title="Rides layer unavailable" />
          <Stack gap={6} mb="sm">
            <Group gap="xs" wrap="wrap">
              <Chip.Group multiple value={layers} onChange={setLayers}>
                {LAYERS.map((l) => (
                  <Chip key={l.value} value={l.value} size="xs" color={l.color} variant="outline" data-testid={`layer-${l.value}`}>
                    {l.label} ({l.value === 'drivers' ? drivers.length : l.value === 'requests' ? live.requests.length : l.value === 'trips' ? live.trips.length : live.sos.length})
                  </Chip>
                ))}
              </Chip.Group>
              {openSos > 0 && <Badge color="red" variant="filled" leftSection={<FiAlertOctagon size={10} />}>{openSos} open SOS</Badge>}
            </Group>
            <Group gap="xs" wrap="wrap" align="flex-end">
              <MultiSelect size="xs" placeholder={rideTypes.length ? undefined : 'All ride types'} data={LIVE_RIDE_TYPES.map((v) => ({ value: v, label: RIDE_TYPES[v] }))} value={rideTypes} onChange={setRideTypes} clearable w={230} data-testid="filter-ride-type" />
              <MultiSelect size="xs" placeholder={services.length ? undefined : 'All services'} data={serviceOptions} value={services} onChange={setServices} clearable w={220} searchable data-testid="filter-service" />
              <Select size="xs" placeholder="All areas" data={AREA_OPTIONS} value={area || null} onChange={(v) => setArea(v || '')} clearable searchable w={220} data-testid="filter-area" />
              <TextInput size="xs" placeholder="Search name, #id, address" value={search} onChange={(e) => setSearch(e.currentTarget.value)} w={200} />
              {filtersOn ? <Button size="compact-xs" variant="subtle" onClick={() => { setRideTypes([]); setServices([]); setArea(''); setSearch(''); }}>Clear filters</Button> : null}
            </Group>
            <Group gap="xs" wrap="wrap">
              <Chip.Group multiple value={states} onChange={setStates}>
                {STATES.map((s) => (
                  <Chip key={s} value={s} size="xs" color={s === 'sos' ? 'red' : s === 'on_trip' ? 'orange' : s === 'en_route' ? 'blue' : 'gray'}>
                    {DRIVER_STATE_LABEL[s]} {counts ? `(${counts[s] ?? 0})` : ''}
                  </Chip>
                ))}
              </Chip.Group>
              <Tooltip label="Drivers on an active ride stay visible even after they toggle offline" withArrow>
                <Switch size="xs" label="Include offline drivers on an active ride" checked={offlineActive} onChange={(e) => setOfflineActive(e.currentTarget.checked)} data-testid="toggle-offline-active" />
              </Tooltip>
              <Switch size="xs" label="Hide stale (>10 min)" checked={hideStale} onChange={(e) => setHideStale(e.currentTarget.checked)} />
            </Group>
            {filtersOn ? <Text size="xs" c="dimmed">Filters apply to drivers, requests and trips; service filters requests only (drivers carry no service); SOS pins are always shown.</Text> : null}
          </Stack>
          <Grid gutter="sm">
            <Grid.Col span={{ base: 12, md: 8 }}>
              <MapView
                height="calc(100vh - 330px)"
                markers={markers}
                circles={circles}
                polylines={polylines}
                fitKey={drv.isLoading || live.isLoading ? undefined : `initial-${area}`}
                follow={follow && hasPos(followPos) ? [num(followPos.lat), num(followPos.lng)] : null}
              />
              <Group mt={6}><Legend /></Group>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Stack gap="sm">
                {selDriver && <DriverPanel d={selDriver} follow={follow} setFollow={setFollow} onClose={close} onReplay={startReplay} />}
                {selRequest && <RequestPanel r={selRequest} onClose={close} />}
                {selTrip && <TripPanel t={selTrip} follow={follow} setFollow={setFollow} onClose={close} onReplay={startReplay} />}
                {selSos && <SosPanel s={selSos} follow={follow} setFollow={setFollow} onClose={close} />}
                <Card withBorder radius="md" padding={0}>
                  <SegmentedControl
                    fullWidth size="xs" value={listTab} onChange={setListTab} m={6}
                    data={[
                      { value: 'drivers', label: `Drivers ${shownDrivers.length}` },
                      { value: 'requests', label: `Requests ${shownRequests.length}` },
                      { value: 'trips', label: `Trips ${shownTrips.length}` },
                      { value: 'sos', label: `SOS ${shownSos.length}` },
                    ]}
                    data-testid="list-tabs"
                  />
                  <ScrollArea h={sel ? 250 : 470}>
                    {listTab === 'drivers' && shownDrivers.map((d) => (
                      <ListRow key={d.driver_id} testid="row-driver" active={isSel('driver', d.driver_id)} color={DRIVER_STATE_COLOR[d.state]} onClick={() => pick('driver', d.driver_id)}
                        title={d.name || d.first_name || `#${d.driver_id}`}
                        right={<>
                          {d.ride && <StageBadge stage={d.ride.stage} size="xs" />}
                          {!d.online && <Badge size="xs" color="yellow" variant="outline">offline</Badge>}
                          {!d.position && <Badge size="xs" color="gray" variant="outline">no GPS</Badge>}
                          <Button size="compact-xs" variant="subtle" onClick={(e) => { e.stopPropagation(); pick('driver', d.driver_id); setFollow(true); }} aria-label="Follow"><FiCrosshair /></Button>
                        </>} />
                    ))}
                    {listTab === 'requests' && shownRequests.map((r) => (
                      <ListRow key={`${r.kind}-${r.id}`} testid="row-request" active={isSel('request', `${r.kind}-${r.id}`)} color={LAYER_COLOR.request} onClick={() => pick('request', `${r.kind}-${r.id}`)}
                        title={`#${r.id} ${r.customer?.first_name || ''} · ${r.pickup?.address || 'no address'}`}
                        right={<><Badge size="xs" variant="light" color="violet">{humanize(r.status)}</Badge><Text size="xs" ff="monospace">{money(r.offer_cents)}</Text></>} />
                    ))}
                    {listTab === 'trips' && shownTrips.map((t) => (
                      <ListRow key={t.trip_id} testid="row-trip" active={isSel('trip', t.trip_id)} color={LAYER_COLOR.trip} onClick={() => pick('trip', t.trip_id)}
                        title={`#${t.trip_id} ${t.driver?.first_name || ''} · ${t.start?.address || ''} → ${t.end?.address || ''}`}
                        right={<><StageBadge stage={t.stage} size="xs" /><Text size="xs">{t.passengers}/{t.seats ?? '?'}</Text></>} />
                    ))}
                    {listTab === 'sos' && shownSos.map((s) => (
                      <ListRow key={s.incident_id} testid="row-sos" active={isSel('sos', s.incident_id)} color={LAYER_COLOR.sos} onClick={() => { pick('sos', s.incident_id); setFollow(true); }}
                        title={`SOS #${s.incident_id} · ${s.user?.first_name || `#${s.user?.id}`} (${s.user?.role || '?'})`}
                        right={<>
                          {!s.ride_type && <Badge size="xs" color="orange" variant="outline">no ride</Badge>}
                          {!hasPos(s.position) && <Badge size="xs" color="gray" variant="outline">no GPS</Badge>}
                          <Badge size="xs" color={s.status === 'open' ? 'red' : 'orange'}>{humanize(s.status)}</Badge>
                        </>} />
                    ))}
                    {((listTab === 'drivers' && !shownDrivers.length) || (listTab === 'requests' && !shownRequests.length)
                      || (listTab === 'trips' && !shownTrips.length) || (listTab === 'sos' && !shownSos.length)) && (
                      <Text size="sm" c="dimmed" p="sm">{listTab === 'sos' ? 'No open SOS.' : 'Nothing matches the filters.'}</Text>
                    )}
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
            <RouteReplay rideType={replay.type} rideId={replay.id} height="calc(100vh - 380px)" />
          ) : <Text c="dimmed" size="sm">Pick a ride (or a driver / trip on the live tab) to replay its recorded route with a time slider, the planned route and optional snap-to-roads.</Text>}
          <Text size="xs" c="dimmed" mt="xs">Completed rides keep breadcrumbs for the retention window (tracking.retention_days).</Text>
        </Tabs.Panel>
      </Tabs>
    </>
  );
}
