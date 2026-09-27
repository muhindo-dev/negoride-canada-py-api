// Socket.IO `/rt` namespace (backend/sockets/realtime_events.py). Admins are
// auto-joined to admin:ops (+ admin:sos for ops/safety). The same event may
// arrive through several rooms — consumers dedupe where it matters.
import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { io } from 'socket.io-client';
import { useQueryClient } from '@tanstack/react-query';

const Ctx = createContext(null);

const ADMIN_EVENTS = [
  'connected', 'ride.stage_changed', 'driver.location', 'safety.sos', 'safety.sos_updated', 'alert',
  'safety.check_created', 'safety.check_answered', 'safety.report_created', 'onboarding.submitted',
  'onboarding.document_uploaded', 'onboarding.bgc_clear', 'onboarding.bgc_review', 'notification',
];

export function RealtimeProvider({ token, children }) {
  const listeners = useRef(new Map());
  const [status, setStatus] = useState('connecting');
  const [lastEventAt, setLastEventAt] = useState(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (!token) return undefined;
    const socket = io('/rt', {
      path: '/socket.io',
      auth: { token },
      transports: ['polling', 'websocket'],
      reconnectionDelay: 1000,
      reconnectionDelayMax: 10000,
    });
    const dispatch = (event, payload) => {
      setLastEventAt(Date.now());
      (listeners.current.get(event) || []).forEach((fn) => {
        try { fn(payload); } catch (e) { console.warn('realtime handler failed', event, e); } // eslint-disable-line no-console
      });
      (listeners.current.get('*') || []).forEach((fn) => fn(event, payload));
      // Cheap cache coherence: stale the queries that the event affects.
      if (event === 'ride.stage_changed') {
        qc.invalidateQueries({ queryKey: ['command-center'] });
        qc.invalidateQueries({ queryKey: ['alerts'] });
        if (payload?.ride_type && payload?.ride_id) {
          qc.invalidateQueries({ queryKey: ['ride', payload.ride_type, String(payload.ride_id)] });
        }
      } else if (event.startsWith('safety.')) {
        qc.invalidateQueries({ queryKey: ['safety'] });
        qc.invalidateQueries({ queryKey: ['command-center'] });
        qc.invalidateQueries({ queryKey: ['alerts'] });
      } else if (event === 'alert') {
        qc.invalidateQueries({ queryKey: ['alerts'] });
      } else if (event.startsWith('onboarding.')) {
        qc.invalidateQueries({ queryKey: ['onboarding'] });
      }
    };
    socket.on('connect', () => setStatus('connected'));
    socket.on('disconnect', () => setStatus('disconnected'));
    socket.on('connect_error', () => setStatus('error'));
    ADMIN_EVENTS.forEach((ev) => socket.on(ev, (payload) => dispatch(ev, payload)));
    return () => {
      socket.removeAllListeners();
      socket.disconnect();
    };
  }, [token, qc]);

  const api = useRef({
    on(event, fn) {
      const m = listeners.current;
      if (!m.has(event)) m.set(event, new Set());
      m.get(event).add(fn);
      return () => m.get(event)?.delete(fn);
    },
  }).current;

  return <Ctx.Provider value={{ ...api, status, lastEventAt }}>{children}</Ctx.Provider>;
}

export function useRealtimeStatus() {
  const c = useContext(Ctx);
  return c ? { status: c.status, lastEventAt: c.lastEventAt } : { status: 'off', lastEventAt: null };
}

/** Subscribe to one realtime event for the lifetime of the component. */
export function useRealtime(event, handler) {
  const c = useContext(Ctx);
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!c) return undefined;
    return c.on(event, (...args) => ref.current?.(...args));
  }, [c, event]);
}
