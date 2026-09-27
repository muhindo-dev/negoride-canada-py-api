// Live driver positions: GET /api/admin/live/drivers (polled) merged with
// `driver.location` socket events for smooth movement between polls.
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { http } from './api';
import { useRealtime } from './realtime';

export const DRIVER_STATE_COLOR = { idle: '#868e96', en_route: '#1c7ed6', on_trip: '#f08c00', sos: '#e03131' };
export const DRIVER_STATE_LABEL = { idle: 'Idle', en_route: 'En route', on_trip: 'On trip', sos: 'SOS' };

export function useLiveDrivers({ enabled = true, includeOfflineActive = true, interval = 15000 } = {}) {
  const q = useQuery({
    queryKey: ['live-drivers', includeOfflineActive],
    queryFn: () => http.get('/admin/live/drivers', includeOfflineActive ? { include_offline_active: 1 } : {}),
    enabled,
    refetchInterval: interval,
  });
  const [live, setLive] = useState({}); // driver_id → latest socket point
  useRealtime('driver.location', (p) => {
    if (!p?.user_id || !Number.isFinite(Number(p.lat))) return;
    setLive((m) => ({ ...m, [p.user_id]: { lat: Number(p.lat), lng: Number(p.lng), heading: p.heading, speed: p.speed, at: p.at, stage: p.stage, ride_type: p.ride_type, ride_id: p.ride_id } }));
  });
  const drivers = useMemo(() => {
    const list = (q.data?.drivers || []).map((d) => {
      const s = live[d.driver_id];
      const polledAt = d.position?.at ? Date.parse(d.position.at) : 0;
      const liveAt = s?.at ? Date.parse(s.at) : 0;
      const pos = s && liveAt >= polledAt ? { ...d.position, ...s } : d.position;
      return { ...d, position: pos, live: !!(s && liveAt >= polledAt) };
    });
    return list;
  }, [q.data, live]);
  return { ...q, drivers, counts: q.data?.counts, generatedAt: q.data?.generated_at };
}
