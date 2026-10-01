// Thin helpers over the shared axios instance (JWT + 401 handling live in
// services/api.js). Every v4 endpoint answers {code, message, data}; code 0 or
// a non-2xx status becomes an ApiError carrying the server's message.
import api from '../../services/api';

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message || 'Request failed');
    this.status = status;
    this.data = data;
    this.code = data?.error_code;
  }
}

function toError(err) {
  if (err instanceof ApiError) return err;
  const r = err?.response;
  if (r) {
    const body = r.data && typeof r.data === 'object' ? r.data : {};
    const msg = body.message || (r.status === 403 ? 'Your admin role does not allow this.' : `HTTP ${r.status}`);
    return new ApiError(msg, r.status, body.data);
  }
  return new ApiError(err?.message || 'Network error', 0);
}

function unwrap(res) {
  const body = res.data;
  if (body && typeof body === 'object' && 'code' in body) {
    if (Number(body.code) !== 1) throw new ApiError(body.message, res.status, body.data);
    return body.data;
  }
  return body;
}

async function call(fn) {
  try {
    return unwrap(await fn());
  } catch (e) {
    throw toError(e);
  }
}

export const http = {
  get: (url, params) => call(() => api.get(url, { params: clean(params) })),
  post: (url, body, headers) => call(() => api.post(url, body ?? {}, headers ? { headers } : undefined)),
  put: (url, body) => call(() => api.put(url, body ?? {})),
  patch: (url, body) => call(() => api.patch(url, body ?? {})),
  del: (url) => call(() => api.delete(url)),
  /** Full envelope (message too) — for actions whose message matters. */
  postFull: async (url, body, headers) => {
    try {
      const res = await api.post(url, body ?? {}, headers ? { headers } : undefined);
      if (Number(res.data?.code) !== 1) throw new ApiError(res.data?.message, res.status, res.data?.data);
      return res.data;
    } catch (e) {
      throw toError(e);
    }
  },
};

export function clean(params) {
  if (!params) return params;
  const out = {};
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') out[k] = v;
  });
  return out;
}

/** Normalises the three paging shapes the backend uses. */
export function page(data) {
  if (!data) return { items: [], total: 0, page: 1, perPage: 25, lastPage: 1 };
  if (Array.isArray(data)) return { items: data, total: data.length, page: 1, perPage: data.length, lastPage: 1 };
  const items = data.data ?? data.items ?? [];
  const perPage = data.per_page ?? items.length;
  const total = data.total ?? items.length;
  return {
    items,
    total,
    page: data.current_page ?? data.page ?? 1,
    perPage,
    lastPage: data.last_page ?? Math.max(1, Math.ceil(total / (perPage || 1))),
    raw: data,
  };
}

/** Fetch a binary (PDF/CSV/image) with the admin JWT. */
export async function fetchBlob(url, params) {
  try {
    const res = await api.get(url, { params: clean(params), responseType: 'blob' });
    const ct = res.headers['content-type'] || '';
    if (ct.includes('application/json')) {
      const body = JSON.parse(await res.data.text());
      throw new ApiError(body.message, res.status, body.data);
    }
    return { blob: res.data, contentType: ct, disposition: res.headers['content-disposition'] || '' };
  } catch (e) {
    if (e?.response?.data instanceof Blob) {
      try {
        const body = JSON.parse(await e.response.data.text());
        throw new ApiError(body.message, e.response.status, body.data);
      } catch (inner) {
        if (inner instanceof ApiError) throw inner;
      }
    }
    throw toError(e);
  }
}

export async function download(url, params, fallbackName = 'export') {
  const { blob, disposition } = await fetchBlob(url, params);
  const m = /filename="?([^";]+)"?/.exec(disposition);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 30000);
}

export async function openBlob(url, params) {
  const { blob } = await fetchBlob(url, params);
  const href = URL.createObjectURL(blob);
  window.open(href, '_blank', 'noopener');
  setTimeout(() => URL.revokeObjectURL(href), 120000);
}

export function idemKey(prefix = 'admin') {
  const rnd = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`);
  return `${prefix}-${rnd}`;
}

// Human text for the state-machine / payment error codes the admin actions
// return (reason_required 400, payment_required 402, invalid_transition /
// terminal / bad_stage 409 with data.stage, …). Falls back to the server message.
const ERROR_HINTS = {
  reason_required: 'A reason of at least 5 characters is required.',
  reason_text_required: 'Add a short explanation (reason text).',
  payment_required: 'The ride is not paid yet — mark it paid (offline payment) or let the customer pay first.',
  invalid_transition: 'The state machine does not allow this change from the current stage.',
  terminal: 'The ride has already ended and cannot change.',
  bad_stage: 'Not possible at the ride’s current stage.',
  already_paid: 'This booking is already paid.',
  already_assigned: 'That driver is already assigned.',
  driver_unavailable: 'That driver cannot take rides right now (not approved, inactive or offline).',
  no_price: 'The booking has no agreed price — pass an amount.',
  not_in_review: 'This ride has no payment waiting for a safety decision.',
  bad_amount: 'The amount is out of range.',
  gateway_error: 'Stripe refused the operation.',
  not_completed: 'The ride is not completed yet.',
};

export function describeError(e) {
  if (!e) return '';
  const code = e.code || e.data?.error_code;
  const stage = e.data?.stage;
  const msg = e.message || String(e);
  const hint = code && ERROR_HINTS[code];
  const parts = [msg];
  // Server messages are usually explicit already; add the hint only to terse ones.
  if (hint && msg.length < 40) parts.push(hint);
  if (stage && !msg.includes(stage)) parts.push(`Current stage: ${stage}.`);
  return parts.join(' ');
}
