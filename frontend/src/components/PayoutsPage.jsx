import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import {
  FiCheck, FiX, FiChevronLeft, FiChevronRight, FiEye, FiAlertTriangle,
} from 'react-icons/fi';

const PO_STATUSES = ['', 'pending', 'processing', 'completed', 'failed'];

/* ── Payout Detail Drawer ── */
function PayoutDrawer({ payout, onClose, onAction }) {
  const [notes, setNotes] = useState('');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const act = async (action, p = {}) => { setSaving(true); try { await onAction(payout.id, action, p); } finally { setSaving(false); } };
  const fd = v => v != null ? `$${(Number(v) / 100).toFixed(2)}` : '—';

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>Payout #{payout.id}</h2>
          <span className={`badge badge-${payout.status}`}>{payout.status}</span>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="d-section">
            <h4>Request Info</h4>
            <div className="d-row"><span className="dk">User</span><span className="dv">{payout.user_name || `#${payout.user_id}`}</span></div>
            <div className="d-row"><span className="dk">Amount</span><span className="dv" style={{ fontSize: 18, fontWeight: 800 }}>{fd(payout.amount)}</span></div>
            <div className="d-row"><span className="dk">Method</span><span className="dv">{payout.payout_method || '—'}</span></div>
            <div className="d-row"><span className="dk">Account</span><span className="dv">{payout.account_number || '—'}</span></div>
            <div className="d-row"><span className="dk">Account Name</span><span className="dv">{payout.account_name || '—'}</span></div>
            <div className="d-row"><span className="dk">Bank</span><span className="dv">{payout.bank_name || '—'}</span></div>
            <div className="d-row"><span className="dk">Notes (user)</span><span className="dv">{payout.notes || '—'}</span></div>
            <div className="d-row"><span className="dk">Admin Notes</span><span className="dv">{payout.admin_notes || '—'}</span></div>
            <div className="d-row"><span className="dk">Failure Reason</span><span className="dv">{payout.failure_reason || '—'}</span></div>
            <div className="d-row"><span className="dk">Requested</span><span className="dv">{payout.created_at?.slice(0, 16)}</span></div>
            {payout.processing_at && <div className="d-row"><span className="dk">Processing At</span><span className="dv">{payout.processing_at?.slice(0, 16)}</span></div>}
            {payout.processed_at && <div className="d-row"><span className="dk">Completed At</span><span className="dv">{payout.processed_at?.slice(0, 16)}</span></div>}
          </div>

          {payout.status === 'pending' && (
            <div className="d-section">
              <h4>Approve Request</h4>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>Add optional admin notes before approving:</p>
              <textarea className="d-textarea" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Admin notes (optional)…" />
              <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                <button className="btn btn-sm btn-success" disabled={saving} style={{ flex: 1 }}
                  onClick={() => act('approve', { notes })}><FiCheck /> Approve for Processing</button>
              </div>
            </div>
          )}

          {payout.status === 'processing' && (
            <div className="d-section">
              <h4>Mark as Completed</h4>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 10 }}>Confirm that the payout has been sent to the user's account:</p>
              <button className="btn btn-sm btn-success" disabled={saving} style={{ width: '100%' }}
                onClick={() => act('complete')}><FiCheck /> Mark as Completed</button>
            </div>
          )}

          {['pending', 'processing'].includes(payout.status) && (
            <div className="d-section">
              <h4>Reject Request</h4>
              <textarea className="d-textarea" value={reason} onChange={e => setReason(e.target.value)} placeholder="Rejection reason (required)…" />
              <button className="btn btn-sm btn-danger" disabled={saving || !reason.trim()} style={{ width: '100%', marginTop: 10 }}
                onClick={() => act('reject', { reason })}><FiX /> Reject Payout</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function PayoutsPage() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const perPage = 20;
  const totalPages = Math.ceil(total / perPage);

  const load = (p = page, f = filter) => {
    setLoading(true); setError(null);
    const params = { page: p, per_page: perPage };
    if (f) params.status = f;
    adminAPI.payoutRequests(params)
      .then(({ data }) => {
        if (data.code === 1) { setItems(data.data?.data || []); setTotal(data.data?.total || 0); }
        else setError(data.message || 'Failed to load');
      })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { setPage(1); load(1, filter); }, [filter]);

  const doAction = async (id, action, params = {}) => {
    try {
      if (action === 'approve') await adminAPI.payoutApprove(id, params);
      else if (action === 'complete') await adminAPI.payoutComplete(id);
      else if (action === 'reject') await adminAPI.payoutReject(id, params);
      /* refresh the selected item inline */
      setItems(prev => prev.map(item => {
        if (item.id !== id) return item;
        const updated = { ...item };
        if (action === 'approve') { updated.status = 'processing'; updated.admin_notes = params.notes || ''; }
        else if (action === 'complete') updated.status = 'completed';
        else if (action === 'reject') { updated.status = 'failed'; updated.failure_reason = params.reason; }
        if (selected?.id === id) setSelected(updated);
        return updated;
      }));
    } catch {}
  };

  const fd = v => v != null ? `$${(Number(v) / 100).toFixed(2)}` : '—';

  return (
    <div className="page-payouts">
      {selected && <PayoutDrawer payout={selected} onClose={() => setSelected(null)} onAction={doAction} />}

      <div className="page-toolbar">
        <div className="tab-bar" style={{ gap: 4 }}>
          {PO_STATUSES.map(s => (
            <button key={s} className={`tab-btn ${filter === s ? 'tab-btn--active' : ''}`}
              onClick={() => setFilter(s)}>{s || 'All'}</button>
          ))}
        </div>
        <span className="toolbar-info">{total} payouts</span>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={() => load()} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>User</th><th>Amount</th><th>Method</th><th>Account</th><th>Status</th><th>Date</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {items.map(p => (
                <tr key={p.id}>
                  <td style={{ fontWeight: 700 }}>#{p.id}</td>
                  <td>{p.user_name || `#${p.user_id}`}</td>
                  <td style={{ fontWeight: 700 }}>{fd(p.amount)}</td>
                  <td>{p.payout_method || '—'}</td>
                  <td style={{ fontSize: 12 }}>{p.account_number ? `${p.account_number.slice(0, 6)}…` : '—'}</td>
                  <td><span className={`badge badge-${p.status}`}>{p.status}</span></td>
                  <td>{p.created_at?.slice(0, 10)}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="View / Manage" onClick={() => setSelected(p)}><FiEye /></button>
                    {p.status === 'pending' && (
                      <button className="btn btn-xs btn-success" title="Quick Approve" onClick={() => doAction(p.id, 'approve', {})}><FiCheck /></button>
                    )}
                    {p.status === 'processing' && (
                      <button className="btn btn-xs btn-success" title="Mark Complete" onClick={() => doAction(p.id, 'complete')}><FiCheck /></button>
                    )}
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="8" className="empty-state">No payout requests</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {totalPages > 1 && (
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => { const p = page - 1; setPage(p); load(p); }}><FiChevronLeft /></button>
          <span>Page {page} of {totalPages}</span>
          <button disabled={page >= totalPages} onClick={() => { const p = page + 1; setPage(p); load(p); }}><FiChevronRight /></button>
        </div>
      )}
    </div>
  );
}
