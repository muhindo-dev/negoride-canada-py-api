// Global SOS state: a full-width red banner + alarm that persist until every
// open SOS is acknowledged (spec §8.2.4). Sources: the `safety.sos` /
// `safety.sos_updated` socket events, plus a poll of open incidents so the
// alarm survives a reload or a missed socket event.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { http, page } from './api';
import { useRealtime } from './realtime';
import { startAlarm, stopAlarm } from './alarm';
import { useRoles } from './roles';

const Ctx = createContext({ alarming: [], acknowledge: async () => {}, enabled: false });

function fromEvent(p) {
  return {
    id: p.incident_id, status: p.status, kind: p.kind, severity: p.severity, role: p.role,
    user: p.user, ride_type: p.ride_type, ride_id: p.ride_id, lat: p.lat, lng: p.lng,
    created_at: p.created_at, battery_pct: p.battery_pct, silent: p.silent,
  };
}

export function SosProvider({ children }) {
  const { can } = useRoles();
  const enabled = can('safety');
  const qc = useQueryClient();
  const [live, setLive] = useState({}); // id → incident (from socket)

  const open = useQuery({
    queryKey: ['safety', 'open-incidents'],
    queryFn: () => http.get('/admin/safety/incidents', { status: 'open', per_page: 50 }),
    enabled,
    refetchInterval: 15000,
  });

  useRealtime('safety.sos', (p) => {
    if (!enabled || !p?.incident_id) return;
    setLive((m) => ({ ...m, [p.incident_id]: fromEvent(p) }));
    notifications.show({
      id: `sos-${p.incident_id}`, color: 'red', autoClose: false,
      title: `SOS #${p.incident_id}`, message: `${p.user?.name || 'A user'} (${p.role}) needs help`,
    });
  });
  useRealtime('alert', (p) => {
    if (!enabled || p?.kind !== 'oncall_not_configured') return;
    notifications.show({
      id: `oncall-${p.incident_id}`, color: 'red', autoClose: false,
      title: 'SOS escalation failed', message: p.message || 'No on-call phones are configured (Settings → safety.oncall_phones).',
    });
  });
  useRealtime('safety.sos_updated', (p) => {
    if (!enabled || !p?.incident_id) return;
    setLive((m) => ({ ...m, [p.incident_id]: { ...(m[p.incident_id] || {}), ...fromEvent(p) } }));
  });

  const alarming = useMemo(() => {
    const byId = {};
    page(open.data).items.forEach((i) => { byId[i.id] = { ...i }; });
    Object.values(live).forEach((i) => { byId[i.id] = { ...(byId[i.id] || {}), ...i }; });
    return Object.values(byId)
      .filter((i) => i.status === 'open')
      .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  }, [open.data, live]);

  useEffect(() => {
    if (enabled && alarming.length) startAlarm();
    else stopAlarm();
  }, [enabled, alarming.length]);
  useEffect(() => () => stopAlarm(), []);

  const acknowledge = useCallback(async (id, note) => {
    const inc = await http.post(`/admin/safety/incidents/${id}/acknowledge`, note ? { note } : {});
    setLive((m) => ({ ...m, [id]: { ...(m[id] || {}), id, status: inc?.status || 'acknowledged' } }));
    notifications.hide(`sos-${id}`);
    qc.invalidateQueries({ queryKey: ['safety'] });
    qc.invalidateQueries({ queryKey: ['command-center'] });
    return inc;
  }, [qc]);

  return <Ctx.Provider value={{ alarming, acknowledge, enabled }}>{children}</Ctx.Provider>;
}

export const useSos = () => useContext(Ctx);
