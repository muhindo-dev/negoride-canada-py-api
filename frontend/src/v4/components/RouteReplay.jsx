// Ride route replay with a time slider (spec §9.1): breadcrumbs from
// GET /api/admin/rides/{type}/{id}/route, trip events pinned on the map.
import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ActionIcon, Badge, Group, SegmentedControl, Slider, Stack, Text } from '@mantine/core';
import { FiPause, FiPlay, FiSkipBack } from 'react-icons/fi';
import { http } from '../lib/api';
import { fmt, humanize, parseTs } from '../lib/format';
import MapView from './map/MapView';
import { ErrorBox, Loading, StageBadge } from './ui';

export default function RouteReplay({ rideType, rideId, height = 380, extraMarkers = [], live = false }) {
  const q = useQuery({
    queryKey: ['ride-route', rideType, String(rideId)],
    queryFn: () => http.get(`/admin/rides/${rideType}/${rideId}/route`),
    refetchInterval: live ? 10000 : false,
  });
  const pts = q.data?.points || [];
  const [idx, setIdx] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState('8');
  const cur = idx === null ? pts.length - 1 : Math.min(idx, pts.length - 1);

  useEffect(() => {
    if (!playing || pts.length < 2) return undefined;
    const t = setInterval(() => {
      setIdx((i) => {
        const n = (i === null ? 0 : i) + Number(speed) / 4;
        if (n >= pts.length - 1) { setPlaying(false); return pts.length - 1; }
        return n;
      });
    }, 250);
    return () => clearInterval(t);
  }, [playing, pts.length, speed]);

  const at = pts[Math.floor(cur)]?.at;
  const stageAt = useMemo(() => {
    if (!q.data?.events || !at) return q.data?.stage;
    const t = parseTs(at)?.getTime() || 0;
    let s = null;
    q.data.events.forEach((e) => { if ((parseTs(e.at)?.getTime() || 0) <= t) s = e.to_stage; });
    return s || q.data.events[0]?.from_stage;
  }, [q.data, at]);

  if (q.isLoading) return <Loading h={height} />;
  if (q.error) return <ErrorBox error={q.error} title="Route unavailable" />;
  const d = q.data;
  const i = Math.floor(cur);
  const done = pts.slice(0, i + 1).map((p) => [p.lat, p.lng]);
  const rest = pts.slice(i).map((p) => [p.lat, p.lng]);
  const markers = [
    d.pickup?.lat && { id: 'pickup', lat: d.pickup.lat, lng: d.pickup.lng, color: '#2f9e44', label: `Pickup: ${d.pickup.address || ''}`, radius: 8 },
    d.dropoff?.lat && { id: 'dropoff', lat: d.dropoff.lat, lng: d.dropoff.lng, color: '#1c7ed6', label: `Drop-off: ${d.dropoff.address || ''}`, radius: 8 },
    ...(d.events || []).filter((e) => e.lat).map((e, k) => ({ id: `ev${k}`, lat: e.lat, lng: e.lng, color: '#7048e8', radius: 5, label: `${humanize(e.to_stage)} · ${fmt.time(e.at)}` })),
    ...(d.incidents || []).filter((x) => x.lat).map((x) => ({ id: `inc${x.id}`, lat: x.lat, lng: x.lng, color: '#e03131', radius: 9, label: `SOS #${x.id}` })),
    pts[i] && { id: 'car', lat: pts[i].lat, lng: pts[i].lng, color: '#f08c00', radius: 9, ring: '#000', label: `Driver · ${fmt.dateTimeSec(pts[i].at)}` },
    ...extraMarkers,
  ].filter(Boolean);
  return (
    <Stack gap="xs">
      <MapView
        height={height}
        markers={markers}
        polylines={[
          { id: 'rest', points: rest, color: '#adb5bd', dashed: true, weight: 3 },
          { id: 'done', points: done, color: '#f08c00', weight: 5 },
        ]}
        fitKey={`${rideType}-${rideId}-${pts.length > 0}`}
      />
      {pts.length > 1 ? (
        <Stack gap={4}>
          <Group gap="xs" wrap="nowrap">
            <ActionIcon variant="light" onClick={() => { setIdx(0); setPlaying(false); }} aria-label="Restart"><FiSkipBack /></ActionIcon>
            <ActionIcon variant="filled" onClick={() => { if (cur >= pts.length - 1) setIdx(0); setPlaying((p) => !p); }} aria-label={playing ? 'Pause' : 'Play'}>
              {playing ? <FiPause /> : <FiPlay />}
            </ActionIcon>
            <Slider
              style={{ flex: 1 }} min={0} max={pts.length - 1} step={1} value={i}
              onChange={(v) => { setIdx(v); setPlaying(false); }}
              label={(v) => fmt.time(pts[v]?.at)}
              marks={(d.events || []).map((e) => {
                const t = parseTs(e.at)?.getTime() || 0;
                let k = pts.findIndex((p) => (parseTs(p.at)?.getTime() || 0) >= t);
                if (k < 0) k = pts.length - 1;
                return { value: k };
              })}
            />
            <SegmentedControl size="xs" value={speed} onChange={setSpeed} data={['2', '8', '32'].map((v) => ({ value: v, label: `${v}×` }))} />
          </Group>
          <Group gap="sm" wrap="wrap">
            <Text size="xs" c="dimmed">{fmt.dateTimeSec(at)}</Text>
            <StageBadge stage={stageAt} size="xs" />
            <Text size="xs" c="dimmed">point {i + 1}/{pts.length}</Text>
            {pts[i]?.speed_mps !== null && pts[i]?.speed_mps !== undefined && <Text size="xs" c="dimmed">{Math.round(pts[i].speed_mps * 3.6)} km/h</Text>}
            <Badge size="xs" variant="light">{(d.distance_m / 1000).toFixed(2)} km recorded</Badge>
          </Group>
        </Stack>
      ) : (
        <Text size="sm" c="dimmed">No location breadcrumbs recorded for this ride{pts.length === 1 ? ' (one point)' : ''}. Pickup/drop-off shown.</Text>
      )}
    </Stack>
  );
}
