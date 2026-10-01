// Recording player: plays the 1-minute m4a chunks back to back and aligns the
// playhead (wall-clock) with trip events and the driver's map position
// (spec §10.2). Audio comes from the audited streaming proxy (`stream_url`,
// GET /api/admin/safety/recordings/{id}/chunks/{seq}, Range-capable, audited
// `recording.chunk_streamed` on every fetch) fetched with the admin JWT and
// played from a blob: URL (a media element cannot send the Authorization
// header). The short-lived signed `url` is only a fallback.
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Badge, Box, Button, Card, Group, Slider, Stack, Switch, Text, Tooltip } from '@mantine/core';
import { FiLock, FiRefreshCw } from 'react-icons/fi';
import { fetchBlob, http } from '../../lib/api';
import { duration, fmt, humanize, parseTs } from '../../lib/format';
import { useRoles } from '../../lib/roles';
import MapView from '../../components/map/MapView';
import { ErrorBox, KV, Loading, notifyErr, notifyOk, RideLink, StatusBadge, UserLink } from '../../components/ui';

function useRoute(rec, enabled) {
  return useQuery({
    queryKey: ['ride-route', rec?.ride_type, String(rec?.ride_id)],
    queryFn: () => http.get(`/admin/rides/${rec.ride_type}/${rec.ride_id}/route`),
    enabled: !!(enabled && rec?.ride_type && rec?.ride_id),
  });
}

const apiPath = (u) => (u && u.startsWith('/api/') ? u.slice(4) : u);

/** blob: URLs per chunk seq, fetched through the audited proxy with the JWT. */
function useChunkSources(chunks) {
  const cache = useRef(new Map()); // seq → {url, via}
  const pending = useRef(new Map());
  const [, bump] = useState(0);
  useEffect(() => () => {
    cache.current.forEach((v) => v.via === 'stream' && URL.revokeObjectURL(v.url));
    cache.current.clear();
  }, []);
  const load = (c) => {
    if (!c) return Promise.resolve(null);
    if (cache.current.has(c.seq)) return Promise.resolve(cache.current.get(c.seq));
    if (pending.current.has(c.seq)) return pending.current.get(c.seq);
    const p = (c.stream_url
      ? fetchBlob(apiPath(c.stream_url)).then(({ blob }) => ({ url: URL.createObjectURL(blob), via: 'stream' }))
        .catch((e) => (c.url ? { url: c.url, via: 'signed', error: e.message } : Promise.reject(e)))
      : Promise.resolve({ url: c.url, via: 'signed' }))
      .then((v) => { cache.current.set(c.seq, v); pending.current.delete(c.seq); bump((n) => n + 1); return v; })
      .catch((e) => { pending.current.delete(c.seq); throw e; });
    pending.current.set(c.seq, p);
    return p;
  };
  return { load, get: (c) => (c ? cache.current.get(c.seq) : null) };
}

export default function RecordingPlayer({ id }) {
  const qc = useQueryClient();
  const { can } = useRoles();
  const q = useQuery({ queryKey: ['safety', 'recording', String(id)], queryFn: () => http.get(`/admin/safety/recordings/${id}`), staleTime: 60000 });
  const rec = q.data;
  const route = useRoute(rec, can('rideRoute'));
  const audio = useRef(null);
  const [chunkIdx, setChunkIdx] = useState(0);
  const [pos, setPos] = useState(0); // seconds within the whole recording
  const [holdBusy, setHoldBusy] = useState(false);

  const chunks = rec?.chunks || [];
  const src = useChunkSources(chunks);
  const [srcErr, setSrcErr] = useState(null);
  const cur = src.get(chunks[chunkIdx]);
  const offsets = useMemo(() => {
    let acc = 0;
    return chunks.map((c) => { const o = acc; acc += (c.duration_ms || 60000) / 1000; return o; });
  }, [chunks]);
  const total = chunks.reduce((s, c) => s + (c.duration_ms || 60000) / 1000, 0);
  const startMs = parseTs(chunks[0]?.started_at || rec?.started_at)?.getTime() || 0;
  const wallAt = (sec) => {
    // prefer the chunk's own start time (gaps between chunks are real)
    let k = 0;
    while (k + 1 < offsets.length && offsets[k + 1] <= sec) k += 1;
    const c = chunks[k];
    const base = parseTs(c?.started_at)?.getTime() || startMs + offsets[k] * 1000;
    return base + (sec - (offsets[k] || 0)) * 1000;
  };
  const wallNow = chunks.length ? wallAt(pos) : null;

  useEffect(() => {
    const c = chunks[chunkIdx];
    if (!c) return undefined;
    let alive = true;
    setSrcErr(null);
    src.load(c).then((v) => {
      const a = audio.current;
      if (!alive || !a || !v) return;
      if (a.dataset.src !== v.url) {
        const wasPlaying = a.dataset.autoplay === '1';
        a.src = v.url;
        a.dataset.src = v.url;
        if (wasPlaying) { a.dataset.autoplay = ''; a.play().catch(() => {}); }
      }
      if (v.error) setSrcErr(`Streaming proxy failed (${v.error}) — using the signed URL.`);
      src.load(chunks[chunkIdx + 1]).catch(() => {}); // prefetch the next minute
    }).catch((e) => alive && setSrcErr(e.message));
    return () => { alive = false; };
  }, [chunkIdx, chunks]); // eslint-disable-line react-hooks/exhaustive-deps

  const seek = (sec) => {
    let k = 0;
    while (k + 1 < offsets.length && offsets[k + 1] <= sec) k += 1;
    const wasPlaying = audio.current && !audio.current.paused;
    setChunkIdx(k);
    setPos(sec);
    requestAnimationFrame(() => {
      const a = audio.current;
      if (!a) return;
      const go = () => { a.currentTime = Math.max(0, sec - offsets[k]); if (wasPlaying) a.play().catch(() => {}); };
      if (a.readyState >= 1 && a.dataset.src === src.get(chunks[k])?.url) go(); else a.addEventListener('loadedmetadata', go, { once: true });
    });
  };

  const events = (rec?.trip_events || []).map((e) => ({ ...e, t: parseTs(e.created_at)?.getTime() }));
  const eventMarks = events.filter((e) => e.t && startMs && e.t >= startMs && e.t <= startMs + total * 1000 + 60000)
    .map((e) => ({ value: Math.min(total, (e.t - startMs) / 1000), label: '' }));
  const pts = route.data?.points || [];
  let here = null;
  if (wallNow && pts.length) {
    here = pts.reduce((best, p) => {
      const dt = Math.abs((parseTs(p.at)?.getTime() || 0) - wallNow);
      return !best || dt < best.dt ? { p, dt } : best;
    }, null)?.p;
  }
  const currentStage = events.filter((e) => e.t && wallNow && e.t <= wallNow).pop()?.to_stage;

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  return (
    <Stack gap="sm">
      <Card withBorder padding="sm" radius="md">
        <Group justify="space-between" mb="xs" wrap="wrap">
          <Group gap="xs">
            <Text fw={600}>Recording #{rec.id}</Text>
            <StatusBadge value={rec.status} />
            {rec.legal_hold && <Badge color="grape" leftSection={<FiLock size={10} />}>Legal hold</Badge>}
          </Group>
          <Group gap="xs">
            <Switch
              label="Legal hold" checked={!!rec.legal_hold} disabled={holdBusy}
              onChange={async (e) => {
                setHoldBusy(true);
                try {
                  await http.post(`/admin/safety/recordings/${rec.id}/hold`, { legal_hold: e.currentTarget.checked });
                  notifyOk('Legal hold updated');
                  qc.invalidateQueries({ queryKey: ['safety', 'recording', String(id)] });
                } catch (err) { notifyErr(err); } finally { setHoldBusy(false); }
              }}
            />
            <Tooltip label={`Signed URLs expire after ${rec.url_ttl_s}s — reload to renew`}>
              <Button size="xs" variant="default" leftSection={<FiRefreshCw />} onClick={() => q.refetch()}>Renew links</Button>
            </Tooltip>
          </Group>
        </Group>
        <KV cols={2} items={[
          ['Recorded by', <UserLink id={rec.user_id} name={`#${rec.user_id} (${rec.role})`} />],
          ['Ride', rec.ride_type ? <RideLink type={rec.ride_type} id={rec.ride_id} /> : '—'],
          ['Started', fmt.dateTimeSec(rec.started_at)],
          ['Stopped', fmt.dateTimeSec(rec.stopped_at)],
          ['Chunks', `${chunks.length} · ${duration(total)}`],
          ['Trigger', humanize(rec.trigger_source)],
          ['Retain until', fmt.dateTime(rec.retain_until)],
          ['Incident', rec.incident_id ? `#${rec.incident_id}` : '—'],
        ]} />
        <Text size="xs" c="dimmed" mt="xs">Opening writes recording.access; every chunk fetched through the streaming proxy writes recording.chunk_streamed.</Text>
      </Card>

      {chunks.length ? (
        <Card withBorder padding="sm" radius="md">
          <audio
            ref={audio} controls preload="metadata" style={{ width: '100%' }} data-testid="recording-audio"
            onTimeUpdate={(e) => setPos((offsets[chunkIdx] || 0) + e.currentTarget.currentTime)}
            onEnded={() => { if (chunkIdx + 1 < chunks.length) { if (audio.current) audio.current.dataset.autoplay = '1'; setChunkIdx(chunkIdx + 1); } }}
          />
          <Group gap="xs" mt={4}>
            {cur ? (
              <Badge size="xs" variant="light" color={cur.via === 'stream' ? 'green' : 'yellow'} data-testid="recording-source">
                {cur.via === 'stream' ? 'Audited stream (JWT)' : 'Signed URL (fallback)'}
              </Badge>
            ) : <Badge size="xs" variant="light" color="gray">Loading chunk…</Badge>}
            {srcErr && <Text size="xs" c="red">{srcErr}</Text>}
          </Group>
          <Box px={4} mt="sm">
            <Slider min={0} max={Math.max(1, total)} step={1} value={pos} onChange={seek} marks={eventMarks} label={(v) => fmt.time(wallAt(v))} />
          </Box>
          <Group gap="xs" mt="md" wrap="wrap">
            <Badge variant="light">Chunk {chunkIdx + 1}/{chunks.length}</Badge>
            <Text size="sm">{wallNow ? fmt.dateTimeSec(new Date(wallNow)) : '—'}</Text>
            {currentStage && <Badge color="violet" variant="light">{humanize(currentStage)}</Badge>}
          </Group>
          <Stack gap={2} mt="xs">
            {events.map((e) => (
              <Group key={e.id} gap="xs" style={{ cursor: e.t >= startMs ? 'pointer' : 'default' }}
                onClick={() => e.t >= startMs && seek(Math.min(total, (e.t - startMs) / 1000))}>
                <Text size="xs" c="dimmed" w={90}>{fmt.time(e.created_at)}</Text>
                <Text size="xs">{humanize(e.from_stage)} → {humanize(e.to_stage)}</Text>
                <Text size="xs" c="dimmed">({e.actor_type})</Text>
              </Group>
            ))}
          </Stack>
        </Card>
      ) : <Alert color="gray">No audio chunks (deleted or never uploaded).</Alert>}

      {rec.ride_type && can('rideRoute') && (
        <Card withBorder padding="sm" radius="md">
          <Text fw={600} mb="xs">Position at playhead</Text>
          {route.error ? <ErrorBox error={route.error} /> : (
            <MapView
              height={300}
              polylines={pts.length ? [{ id: 'r', points: pts.map((p) => [p.lat, p.lng]), color: '#f08c00' }] : []}
              markers={[here && { id: 'here', lat: here.lat, lng: here.lng, color: '#e03131', radius: 9, label: fmt.time(here.at) }].filter(Boolean)}
              fitKey={pts.length ? `rec-${rec.id}` : undefined}
              follow={here ? [here.lat, here.lng] : null}
            />
          )}
        </Card>
      )}
    </Stack>
  );
}
