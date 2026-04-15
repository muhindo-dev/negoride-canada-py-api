import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import {
  FiSearch, FiChevronLeft, FiChevronRight, FiX, FiEye,
} from 'react-icons/fi';

const P_STATUSES = ['', 'succeeded', 'pending', 'failed', 'refunded', 'cancelled'];
const P_TYPES = ['', 'negotiation', 'booking', 'wallet_topup', 'payout'];

function PayDrawer({ payment, onClose }) {
  const fd = v => v != null ? `$${Number(v).toFixed(2)}` : '—';
  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>Payment #{payment.id}</h2>
          <span className={`badge badge-${payment.status}`}>{payment.status}</span>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="d-section">
            <h4>Payment Info</h4>
            <div className="d-row"><span className="dk">Amount</span><span className="dv" style={{ fontSize: 18, fontWeight: 800 }}>{fd(payment.amount)}</span></div>
            <div className="d-row"><span className="dk">Type</span><span className="dv">{payment.payment_type || '—'}</span></div>
            <div className="d-row"><span className="dk">Method</span><span className="dv">{payment.stripe_payment_method || '—'}</span></div>
            <div className="d-row"><span className="dk">Status</span><span className="dv"><span className={`badge badge-${payment.status}`}>{payment.status}</span></span></div>
            <div className="d-row"><span className="dk">Intent ID</span><span className="dv" style={{ fontSize: 11, wordBreak: 'break-all' }}>{payment.stripe_payment_intent_id || '—'}</span></div>
            <div className="d-row"><span className="dk">Platform Fee</span><span className="dv">{fd(payment.platform_fee)}</span></div>
            <div className="d-row"><span className="dk">Description</span><span className="dv">{payment.description || '—'}</span></div>
            <div className="d-row"><span className="dk">Date</span><span className="dv">{payment.created_at?.slice(0, 16)}</span></div>
          </div>
          {payment.customer && (
            <div className="d-section">
              <h4>Customer</h4>
              <div className="d-row"><span className="dk">Name</span><span className="dv">{payment.customer.name}</span></div>
              <div className="d-row"><span className="dk">Phone</span><span className="dv">{payment.customer.phone_number || '—'}</span></div>
              <div className="d-row"><span className="dk">Email</span><span className="dv">{payment.customer.email || '—'}</span></div>
            </div>
          )}
          {payment.driver && (
            <div className="d-section">
              <h4>Driver</h4>
              <div className="d-row"><span className="dk">Name</span><span className="dv">{payment.driver.name}</span></div>
              <div className="d-row"><span className="dk">Phone</span><span className="dv">{payment.driver.phone_number || '—'}</span></div>
            </div>
          )}
          {payment.negotiation && (
            <div className="d-section">
              <h4>Linked Negotiation</h4>
              <div className="d-row"><span className="dk">Neg #</span><span className="dv">#{payment.negotiation.id}</span></div>
              <div className="d-row"><span className="dk">Route</span><span className="dv">{payment.negotiation.pickup_address || '—'} → {payment.negotiation.dropoff_address || '—'}</span></div>
              <div className="d-row"><span className="dk">Status</span><span className="dv"><span className={`badge badge-${payment.negotiation.status?.toLowerCase()}`}>{payment.negotiation.status}</span></span></div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function PaymentsPage() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const perPage = 20;
  const totalPages = Math.ceil(total / perPage);

  const load = (p = page, q = search, f = filter, tf = typeFilter) => {
    setLoading(true); setError(null);
    const params = { page: p, per_page: perPage };
    if (q) params.search = q;
    if (f) params.status = f;
    if (tf) params.payment_type = tf;
    adminAPI.payments(params)
      .then(({ data }) => {
        if (data.code === 1) { setItems(data.data?.data || []); setTotal(data.data?.total || 0); }
        else setError(data.message || 'Failed to load');
      })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { setPage(1); load(1, '', filter, typeFilter); }, [filter, typeFilter]);

  const openDetail = async item => {
    try { const { data } = await adminAPI.paymentShow(item.id); setSelected(data.code === 1 ? data.data : item); }
    catch { setSelected(item); }
  };

  const fd = v => v != null ? `$${Number(v).toFixed(2)}` : '—';

  return (
    <div className="page-payments">
      {selected && <PayDrawer payment={selected} onClose={() => setSelected(null)} />}

      <div className="page-toolbar">
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <div className="tab-bar" style={{ gap: 4 }}>
            {P_STATUSES.map(s => (
              <button key={s} className={`tab-btn ${filter === s ? 'tab-btn--active' : ''}`}
                onClick={() => setFilter(s)}>{s || 'All Status'}</button>
            ))}
          </div>
          <div className="tab-bar" style={{ gap: 4 }}>
            {P_TYPES.map(t => (
              <button key={t} className={`tab-btn ${typeFilter === t ? 'tab-btn--active' : ''}`}
                onClick={() => setTypeFilter(t)} style={{ fontSize: '0.78rem' }}>{t || 'All Types'}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="page-toolbar" style={{ paddingTop: 0 }}>
        <form onSubmit={e => { e.preventDefault(); setPage(1); load(1, search, filter, typeFilter); }} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Search intent ID, description…" value={search} onChange={e => setSearch(e.target.value)} />
          <button type="submit" className="btn btn-sm">Search</button>
        </form>
        <span className="toolbar-info">{total} payments</span>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={() => load()} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th><th>Type</th><th>Amount</th><th>Method</th>
                <th>Reference</th><th>Status</th><th>Date</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map(p => (
                <tr key={p.id}>
                  <td style={{ fontWeight: 700 }}>#{p.id}</td>
                  <td>{p.payment_type || '—'}</td>
                  <td style={{ fontWeight: 700 }}>{fd(p.amount)}</td>
                  <td>{p.stripe_payment_method || '—'}</td>
                  <td style={{ fontSize: 11, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.stripe_payment_intent_id || '—'}</td>
                  <td><span className={`badge badge-${p.status}`}>{p.status}</span></td>
                  <td>{p.created_at?.slice(0, 10)}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="View Detail" onClick={() => openDetail(p)}><FiEye /></button>
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="8" className="empty-state">No payments found</td></tr>}
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
