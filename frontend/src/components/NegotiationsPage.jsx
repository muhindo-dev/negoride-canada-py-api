import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import {
  FiSearch, FiChevronLeft, FiChevronRight, FiX, FiEye, FiXCircle, FiAlertTriangle,
} from 'react-icons/fi';

const N_STATUSES = ['', 'Pending', 'Accepted', 'Started', 'Completed', 'Cancelled'];
const PAY_FILTERS = ['', 'paid', 'unpaid'];

function Confirm({ message, onConfirm, onCancel }) {
  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-box" onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 16 }}>
          <FiAlertTriangle size={22} color="#f44336" style={{ flexShrink: 0, marginTop: 2 }} />
          <p>{message}</p>
        </div>
        <div className="modal-actions">
          <button className="btn btn-sm" onClick={onCancel}>Cancel</button>
          <button className="btn btn-sm btn-danger" onClick={onConfirm}>Confirm</button>
        </div>
      </div>
    </div>
  );
}

function NegDrawer({ neg, onClose, onAction }) {
  const [newStatus, setNewStatus] = useState(neg.status || '');
  const [saving, setSaving] = useState(false);
  const act = async (action, p = {}) => { setSaving(true); try { await onAction(neg.id, action, p); } finally { setSaving(false); } };
  const fd = v => v != null ? `$${Number(v).toFixed(2)}` : '—';
  const fc = v => v != null ? `$${(Number(v) / 100).toFixed(2)}` : '—';
  const price = neg.agreed_price != null ? fd(neg.agreed_price) : fc(neg.initial_price);

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>Negotiation #{neg.id}</h2>
          <span className={`badge badge-${neg.status?.toLowerCase()}`}>{neg.status}</span>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="d-section">
            <h4>Details</h4>
            <div className="d-row"><span className="dk">Agreed Price</span><span className="dv">{price}</span></div>
            <div className="d-row"><span className="dk">Payment Status</span><span className="dv"><span className={`badge badge-${neg.payment_status === 'paid' ? 'success' : 'warning'}`}>{neg.payment_status || 'unpaid'}</span></span></div>
            <div className="d-row"><span className="dk">Service Type</span><span className="dv">{neg.service_type || neg.category || '—'}</span></div>
            <div className="d-row"><span className="dk">Distance</span><span className="dv">{neg.distance ? `${Number(neg.distance).toFixed(1)} km` : '—'}</span></div>
            <div className="d-row"><span className="dk">Created</span><span className="dv">{neg.created_at?.slice(0, 16)}</span></div>
          </div>
          <div className="d-section">
            <h4>Route</h4>
            <div className="d-row"><span className="dk">Pickup</span><span className="dv">{neg.pickup_address || '—'}</span></div>
            <div className="d-row"><span className="dk">Dropoff</span><span className="dv">{neg.dropoff_address || '—'}</span></div>
          </div>
          {neg.customer && (
            <div className="d-section">
              <h4>Customer</h4>
              <div className="d-row"><span className="dk">Name</span><span className="dv">{neg.customer.name}</span></div>
              <div className="d-row"><span className="dk">Phone</span><span className="dv">{neg.customer.phone_number || '—'}</span></div>
              <div className="d-row"><span className="dk">Email</span><span className="dv">{neg.customer.email || '—'}</span></div>
            </div>
          )}
          {neg.driver && (
            <div className="d-section">
              <h4>Driver</h4>
              <div className="d-row"><span className="dk">Name</span><span className="dv">{neg.driver.name}</span></div>
              <div className="d-row"><span className="dk">Phone</span><span className="dv">{neg.driver.phone_number || '—'}</span></div>
              <div className="d-row"><span className="dk">Vehicle</span><span className="dv">{neg.driver.automobile || '—'}</span></div>
            </div>
          )}
          {neg.records_list?.length > 0 && (
            <div className="d-section">
              <h4>Price History ({neg.records_list.length} offers)</h4>
              {neg.records_list.map((r, i) => (
                <div key={r.id || i} style={{ padding: '7px 0', borderBottom: '1px solid var(--grey-5)', fontSize: 12, display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ color: 'var(--text-secondary)' }}>{r.proposed_by === 'customer' ? 'Customer' : 'Driver'}</span>
                  <span style={{ fontWeight: 700 }}>{fd(r.proposed_price)}</span>
                  <span className={`badge badge-${r.status?.toLowerCase()}`}>{r.status}</span>
                  <span style={{ color: 'var(--text-tertiary)' }}>{r.created_at?.slice(0, 10)}</span>
                </div>
              ))}
            </div>
          )}
          {neg.payment && (
            <div className="d-section">
              <h4>Payment</h4>
              <div className="d-row"><span className="dk">Amount</span><span className="dv">{fd(neg.payment.amount)}</span></div>
              <div className="d-row"><span className="dk">Method</span><span className="dv">{neg.payment.stripe_payment_method || '—'}</span></div>
              <div className="d-row"><span className="dk">Status</span><span className="dv"><span className={`badge badge-${neg.payment.status}`}>{neg.payment.status}</span></span></div>
            </div>
          )}
          {!['Completed', 'Cancelled'].includes(neg.status) && (
            <div className="d-section">
              <h4>Update Status</h4>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <select className="d-select" value={newStatus} onChange={e => setNewStatus(e.target.value)}>
                  {['Pending', 'Accepted', 'Started', 'Completed', 'Cancelled'].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
                <button className="btn btn-sm btn-accent" disabled={saving || newStatus === neg.status} onClick={() => act('status', { status: newStatus })}>Save</button>
              </div>
              <button className="btn btn-sm btn-danger" disabled={saving} onClick={() => act('cancel')}><FiXCircle /> Cancel Negotiation</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function NegotiationsPage() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [payFilter, setPayFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const perPage = 20;
  const totalPages = Math.ceil(total / perPage);

  const load = (p = page, q = search, f = filter, pf = payFilter) => {
    setLoading(true); setError(null);
    const params = { page: p, per_page: perPage };
    if (q) params.search = q;
    if (f) params.status = f;
    if (pf) params.payment_status = pf;
    adminAPI.negotiations(params)
      .then(({ data }) => {
        if (data.code === 1) { setItems(data.data?.data || []); setTotal(data.data?.total || 0); }
        else setError(data.message || 'Failed to load');
      })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { setPage(1); load(1, '', filter, payFilter); }, [filter, payFilter]);

  const openDetail = async item => {
    try { const { data } = await adminAPI.negotiationShow(item.id); setSelected(data.code === 1 ? data.data : item); }
    catch { setSelected(item); }
  };

  const doAction = async (id, action, params = {}) => {
    try {
      if (action === 'status') await adminAPI.negotiationStatus(id, params);
      else if (action === 'cancel') await adminAPI.negotiationCancel(id);
      const { data } = await adminAPI.negotiationShow(id);
      if (data.code === 1) setSelected(data.data);
      load(page, search, filter, payFilter);
    } catch {}
  };

  const fd = v => v != null ? `$${Number(v).toFixed(2)}` : '—';
  const fc = v => v != null ? `$${(Number(v) / 100).toFixed(2)}` : '—';

  return (
    <div className="page-negotiations">
      {selected && <NegDrawer neg={selected} onClose={() => setSelected(null)} onAction={doAction} />}
      {confirm && <Confirm message={confirm.msg} onCancel={() => setConfirm(null)}
        onConfirm={() => { doAction(confirm.id, confirm.action); setConfirm(null); }} />}

      <div className="page-toolbar">
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <div className="tab-bar" style={{ gap: 4 }}>
            {N_STATUSES.map(s => (
              <button key={s} className={`tab-btn ${filter === s ? 'tab-btn--active' : ''}`}
                onClick={() => setFilter(s)}>{s || 'All'}</button>
            ))}
          </div>
          <div className="tab-bar" style={{ gap: 4 }}>
            {PAY_FILTERS.map(pf => (
              <button key={pf} className={`tab-btn ${payFilter === pf ? 'tab-btn--active' : ''}`}
                onClick={() => setPayFilter(pf)} style={{ fontSize: '0.78rem' }}>{pf || 'Any Payment'}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="page-toolbar" style={{ paddingTop: 0 }}>
        <form onSubmit={e => { e.preventDefault(); setPage(1); load(1, search, filter, payFilter); }} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Search customer, driver, pickup, dropoff…" value={search} onChange={e => setSearch(e.target.value)} />
          <button type="submit" className="btn btn-sm">Search</button>
        </form>
        <span className="toolbar-info">{total} negotiations</span>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={() => load()} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th><th>Customer</th><th>Driver</th><th>Route</th>
                <th>Price</th><th>Status</th><th>Payment</th><th>Date</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map(n => (
                <tr key={n.id}>
                  <td style={{ fontWeight: 700 }}>#{n.id}</td>
                  <td>{n.customer_name || `#${n.customer_id}`}</td>
                  <td>{n.driver_name || `#${n.driver_id}`}</td>
                  <td style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {n.pickup_address || '?'} → {n.dropoff_address || '?'}
                  </td>
                  <td>{n.agreed_price != null ? fd(n.agreed_price) : fc(n.initial_price)}</td>
                  <td><span className={`badge badge-${n.status?.toLowerCase()}`}>{n.status}</span></td>
                  <td><span className={`badge badge-${n.payment_status === 'paid' ? 'success' : 'warning'}`}>{n.payment_status || 'unpaid'}</span></td>
                  <td>{n.created_at?.slice(0, 10)}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="View / Manage" onClick={() => openDetail(n)}><FiEye /></button>
                    {!['Completed', 'Cancelled'].includes(n.status) && (
                      <button className="btn btn-xs btn-danger" title="Cancel"
                        onClick={() => setConfirm({ id: n.id, action: 'cancel', msg: `Cancel negotiation #${n.id}?` })}><FiXCircle /></button>
                    )}
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="9" className="empty-state">No negotiations found</td></tr>}
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
