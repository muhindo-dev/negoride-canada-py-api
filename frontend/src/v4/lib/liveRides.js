// Live map layers besides drivers: GET /api/admin/live/rides →
// {requests[], rideshare_trips[], sos[], counts, generated_at, refresh_s}.
// Polled every `refresh_s` (server hint, default 10 s) and refreshed early on
// `ride.stage_changed` / `safety.sos*` socket events; SOS pins move live with
// `live.sos_location` between polls.
import { useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { http } from './api';
import { useRealtime } from './realtime';

export function useLiveRides({ enabled = true } = {}) {
  const [refreshS, setRefreshS] = useState(10);
  const q = useQuery({
    queryKey: ['live-rides'],
    queryFn: async () => {
      const d = await http.get('/admin/live/rides');
      if (d?.refresh_s && Number(d.refresh_s) !== refreshS) setRefreshS(Math.max(3, Number(d.refresh_s)));
      return d;
    },
    enabled,
    refetchInterval: refreshS * 1000,
  });

  // Early refresh on events, throttled to one refetch per 2 s.
  const last = useRef(0);
  const timer = useRef(null);
  const poke = () => {
    if (!enabled) return;
    const wait = Math.max(0, 2000 - (Date.now() - last.current));
    if (timer.current) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      last.current = Date.now();
      q.refetch();
    }, wait);
  };
  useRealtime('ride.stage_changed', poke);
  useRealtime('safety.sos', poke);
  useRealtime('safety.sos_updated', poke);

  const [sosLive, setSosLive] = useState({}); // incident_id → latest point
  useRealtime('live.sos_location', (p) => {
    if (!p?.incident_id || !Number.isFinite(Number(p.lat))) return;
    setSosLive((m) => ({ ...m, [p.incident_id]: p }));
    if (!(q.data?.sos || []).some((s) => s.incident_id === p.incident_id)) poke();
  });

  const sos = useMemo(() => (q.data?.sos || []).map((s) => {
    const l = sosLive[s.incident_id];
    if (!l) return s;
    const polled = s.position?.at ? Date.parse(s.position.at) : 0;
    const liveAt = l.at ? Date.parse(l.at) : Date.now();
    if (liveAt < polled) return s;
    return {
      ...s,
      status: l.status || s.status,
      battery_pct: l.battery_pct ?? s.battery_pct,
      position: { lat: Number(l.lat), lng: Number(l.lng), at: l.at, accuracy_m: l.accuracy_m, heading: l.heading, speed_mps: l.speed_mps, source: 'live' },
      live: true,
    };
  }), [q.data, sosLive]);

  return {
    ...q,
    requests: q.data?.requests || [],
    trips: q.data?.rideshare_trips || [],
    sos,
    counts: q.data?.counts,
    generatedAt: q.data?.generated_at,
    refreshS,
  };
}
