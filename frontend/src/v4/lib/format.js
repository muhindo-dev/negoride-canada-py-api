// Money is integer cents (CAD). Timestamps are ISO UTC; legacy
// "YYYY-MM-DD HH:MM:SS" strings are naive UTC too. Everything renders in the
// admin's local time zone.

const CAD = new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' });

export function money(cents, { dash = '—' } = {}) {
  if (cents === null || cents === undefined || cents === '') return dash;
  const n = Number(cents);
  if (!Number.isFinite(n)) return dash;
  return CAD.format(n / 100);
}

export function parseTs(v) {
  if (!v) return null;
  if (v instanceof Date) return v;
  let s = String(v).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return new Date(`${s}T00:00:00Z`);
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s)) s = `${s.replace(' ', 'T')}Z`;
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

const DT = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const DTS = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' });
const T = new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' });
const D = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

export const fmt = {
  dateTime: (v) => { const d = parseTs(v); return d ? DT.format(d) : '—'; },
  dateTimeSec: (v) => { const d = parseTs(v); return d ? DTS.format(d) : '—'; },
  time: (v) => { const d = parseTs(v); return d ? T.format(d) : '—'; },
  date: (v) => { const d = parseTs(v); return d ? D.format(d) : '—'; },
};

export const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function ago(v) {
  const d = parseTs(v);
  if (!d) return '—';
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  const abs = Math.abs(s);
  const suffix = s >= 0 ? 'ago' : 'from now';
  if (abs < 45) return s >= 0 ? 'just now' : 'in a moment';
  if (abs < 3600) return `${Math.round(abs / 60)} min ${suffix}`;
  if (abs < 86400) return `${Math.round(abs / 3600)} h ${suffix}`;
  return `${Math.round(abs / 86400)} d ${suffix}`;
}

export function duration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Math.round(Number(seconds)));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${r}s`;
  return `${r}s`;
}

export function pct(v, digits = 1) {
  if (v === null || v === undefined) return '—';
  return `${Number(v).toFixed(digits)}%`;
}

export function humanize(s) {
  if (!s) return '—';
  return String(s).replace(/[_.]/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export const RIDE_TYPES = {
  carhire: 'Car Hire',
  scheduled: 'Scheduled',
  rideshare_trip: 'Rideshare trip',
  rideshare_booking: 'Rideshare seat',
};

const STAGE_COLOR = {
  REQUESTED: 'gray', NEGOTIATING: 'grape', PRICE_AGREED: 'violet', AWAITING_PAYMENT: 'yellow',
  PENDING_PAYMENT: 'yellow', CONFIRMED: 'blue', DRAFT: 'gray', PUBLISHED: 'blue', BOARDING: 'cyan',
  DRIVER_EN_ROUTE: 'cyan', DRIVER_ARRIVING: 'cyan', DRIVER_ARRIVED: 'teal', CHECKED_IN: 'teal',
  IN_PROGRESS: 'orange', RIDING: 'orange', COMPLETED: 'green', DROPPED_OFF: 'green', CLOSED: 'dark',
  EXPIRED: 'gray', DECLINED: 'gray', CANCELLED_BY_CUSTOMER: 'red', CANCELLED_BY_DRIVER: 'red',
  CUSTOMER_NO_SHOW: 'pink', DRIVER_NO_SHOW: 'pink', NO_SHOW: 'pink',
};
export const stageColor = (s) => STAGE_COLOR[s] || 'gray';

const STATUS_COLOR = {
  active: 'green', open: 'red', acknowledged: 'orange', resolved: 'green', false_alarm: 'gray',
  suspended: 'orange', deactivated: 'gray', banned: 'red', pending_review: 'yellow',
  pending: 'yellow', approved: 'green', rejected: 'red', needs_changes: 'orange', submitted: 'blue',
  under_review: 'blue', in_progress: 'cyan', expired: 'gray', superseded: 'gray',
  clear: 'green', consider: 'orange', failed: 'red', paid: 'blue', initiated: 'cyan', awaiting_payment: 'yellow',
  captured: 'green', authorized: 'blue', partially_captured: 'teal', canceled: 'gray', released: 'gray',
  refunded: 'grape', partially_refunded: 'grape', succeeded: 'green', processed: 'green', received: 'blue',
  sent: 'blue', delivered: 'green', opened: 'teal', queued: 'gray', skipped: 'gray', closed: 'dark',
  reviewing: 'blue', dismissed: 'gray', answered: 'green', timed_out: 'red', escalated: 'red',
  published: 'green', draft: 'yellow', archived: 'gray', completed: 'green', ok: 'green', mismatch: 'orange',
  error: 'red', recording: 'red', stopped: 'blue', deleted: 'gray', urgent: 'red', high: 'orange',
  normal: 'blue', low: 'gray', critical: 'red', warning: 'orange', info: 'blue',
};
export const statusColor = (s) => STATUS_COLOR[String(s || '').toLowerCase()] || 'gray';

export function initials(name) {
  return (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('');
}
