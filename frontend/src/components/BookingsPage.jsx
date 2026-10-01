import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { isTerminal, LegacyActionModal, StageCell, StageSection } from './legacyActions';
import {
  FiSearch, FiChevronLeft, FiChevronRight, FiX, FiEye,
  FiCheck, FiXCircle, FiAlertTriangle,
} from 'react-icons/fi';

const B_STATUSES = ['', 'pending', 'driver_assigned', 'confirmed', 'in_progress', 'completed', 'cancelled'];
const B_LABELS = { '': 'All', pending: 'Pending', driver_assigned: 'Assigned', confirmed: 'Confirmed', in_progress: 'In Progress', completed: 'Completed', cancelled: 'Cancelled' };

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

function BookingDrawer({ booking, drivers, onClose, onAction }) {
  const [driverId, setDriverId] = useState('');
  const [newStatus, setNewStatus] = useState(booking.status || '');
  const [saving, setSaving] = useState(false);
  const act = async (action, p = {}) => { setSaving(true); try { await onAction(booking.id, action, p); } finally { setSaving(false); } };
  const fc = v => v != null ? `$${(Number(v) / 100).toFixed(2)}` : '—';
  const price = booking.agreed_price != null ? fc(booking.agreed_price) : fc(booking.customer_proposed_price);

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>Booking #{booking.id}</h2>
          <span className={`badge badge-${booking.status}`}>{booking.status}</span>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="d-section">
            <h4>Booking Details</h4>
            <div className="d-row"><span className="dk">Payment</span><span className="dv"><span className={`badge badge-${booking.payment_status === 'paid' ? 'success' : 'warning'}`}>{booking.payment_status || 'unpaid'}</span></span></div>
            <div className="d-row"><span className="dk">Price</span><span className="dv">{price}</span></div>
            <div className="d-row"><span className="dk">Service Type</span><span className="dv">{booking.service_type || '—'}</span></div>
            <div className="d-row"><span className="dk">Seats</span><span className="dv">{booking.number_of_seats || '—'}</span></div>
            <div className="d-row"><span className="dk">Scheduled At</span><span className="dv">{booking.scheduled_at?.slice(0, 16) || '—'}</span></div>
            <div className="d-row"><span className="dk">Notes</span><span className="dv">{booking.notes || '—'}</span></div>
            <div className="d-row"><span className="dk">Created</span><span className="dv">{booking.created_at?.slice(0, 16) || '—'}</span></div>
          </div>
          <div className="d-section">
            <h4>Route</h4>
            <div className="d-row"><span className="dk">Pickup</span><span className="dv">{booking.pickup_address || booking.pickup_place_name || '—'}</span></div>
            <div className="d-row"><span className="dk">Destination</span><span className="dv">{booking.destination_address || booking.destination_place_name || '—'}</span></div>
          </div>
          {booking.customer && (
            <div className="d-section">
              <h4>Customer</h4>
              <div className="d-row"><span className="dk">Name</span><span className="dv">{booking.customer.name}</span></div>
              <div className="d-row"><span className="dk">Phone</span><span className="dv">{booking.customer.phone_number || '—'}</span></div>
              <div className="d-row"><span className="dk">Email</span><span className="dv">{booking.customer.email || '—'}</span></div>
            </div>
          )}
          <div className="d-section">
            <h4>Driver</h4>
            {booking.driver ? (
              <>
                <div className="d-row"><span className="dk">Name</span><span className="dv">{booking.driver.name}</span></div>
                <div className="d-row"><span className="dk">Phone</span><span className="dv">{booking.driver.phone_number || '—'}</span></div>
                <div className="d-row"><span className="dk">Vehicle</span><span className="dv">{booking.driver.automobile || '—'}</span></div>
              </>
            ) : <p style={{ color: 'var(--warning)', fontSize: 13, margin: '4px 0 10px', fontWeight: 600 }}>⚠ No driver assigned yet</p>}
            {!isTerminal(booking.trip_stage, booking.status) && (
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <select className="d-select" value={driverId} onChange={e => setDriverId(e.target.value)}>
                  <option value="">Assign a driver…</option>
                  {drivers.map(d => <option key={d.id} value={d.id}>{d.name} (#{d.id}){d.automobile ? ` — ${d.automobile}` : ''}</option>)}
                </select>
                <button className="btn btn-sm btn-accent" disabled={!driverId || saving} onClick={() => act('assign', { driver_id: Number(driverId), replacing: !!booking.driver_id })}>{booking.driver_id ? 'Reassign…' : 'Assign'}</button>
              </div>
            )}
          </div>
          <StageSection type="scheduled" ride={booking} />
          {!isTerminal(booking.trip_stage, booking.status) && (
            <div className="d-section">
              <h4>Update Status</h4>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <select className="d-select" value={newStatus} onChange={e => setNewStatus(e.target.value)}>
                  {['pending', 'driver_assigned', 'confirmed', 'in_progress', 'completed', 'cancelled'].map(s => (
                    <option key={s} value={s}>{B_LABELS[s] || s}</option>
                  ))}
                </select>
                <button className="btn btn-sm btn-accent" disabled={saving || newStatus === booking.status} onClick={() => act('status', { status: newStatus })}>Save…</button>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {booking.payment_status !== 'paid' && (
                  <button className="btn btn-sm btn-success" disabled={saving} onClick={() => act('markPaid')}><FiCheck /> Mark Paid…</button>
                )}
                <button className="btn btn-sm btn-danger" disabled={saving} onClick={() => act('cancel')}><FiXCircle /> Cancel Booking…</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BookingsPage() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [drivers, setDrivers] = useState([]);
  const [confirm, setConfirm] = useState(null);
  const [action, setAction] = useState(null);
  const perPage = 20;
  const totalPages = Math.ceil(total / perPage);

  const load = (p = page, q = search, f = filter) => {
    setLoading(true); setError(null);
    const params = { page: p, per_page: perPage };
    if (q) params.search = q;
    if (f) params.status = f;
    adminAPI.bookings(params)
      .then(({ data }) => {
        if (data.code === 1) { setItems(data.data?.data || []); setTotal(data.data?.total || 0); }
        else setError(data.message || 'Failed to load bookings');
      })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { setPage(1); load(1, '', filter); }, [filter]);
  useEffect(() => {
    adminAPI.users({ user_type: 'Driver', per_page: 500 })
      .then(({ data }) => { if (data.code === 1) setDrivers(data.data?.data || []); }).catch(() => {});
  }, []);

  const openDetail = async item => {
    try { const { data } = await adminAPI.bookingShow(item.id); setSelected(data.code === 1 ? data.data : item); }
    catch { setSelected(item); }
  };

  const refreshAfter = async (id) => {
    try {
      const { data } = await adminAPI.bookingShow(id);
      if (data.code === 1) setSelected((cur) => (cur && cur.id === id ? data.data : cur));
    } catch { /* list reload below still runs */ }
    load(page, search, filter);
  };

  // Every action needs a reason and runs through the v4 state machine.
  const doAction = async (id, kind, params = {}) => {
    if (kind === 'assign') {
      setAction({
        id, title: `${params.replacing ? 'Reassign' : 'Assign'} driver #${params.driver_id} to booking #${id}`, url: `/admin/bookings/${id}/assign-driver`,
        body: { driver_id: params.driver_id }, reasonOptional: !params.replacing, confirmLabel: params.replacing ? 'Reassign' : 'Assign', color: 'blue',
        successMessage: `Driver #${params.driver_id} assigned`,
        description: 'Same rules as the v4 reassign: before pickup only, the driver must be approved and active; both drivers and the customer are notified.',
      });
    } else if (kind === 'markPaid') {
      setAction({
        id, title: `Mark booking #${id} paid (offline)`, url: `/admin/bookings/${id}/mark-paid`, amount: true, confirmLabel: 'Mark paid', color: 'green',
        successMessage: `Booking #${id} marked paid and confirmed`,
        description: 'Records an offline payment (cash, e-transfer, comp) and confirms the booking. Refunds of offline payments are recorded without calling Stripe.',
      });
    } else if (kind === 'status' && params.status !== 'cancelled') {
      setAction({
        id, title: `Set booking #${id} to “${params.status}”`, url: `/admin/bookings/${id}/update-status`, body: { status: params.status },
        confirmLabel: 'Apply', color: 'orange', successMessage: `Booking #${id} → ${params.status}`,
        description: 'The booking is walked through the state machine. Unpaid bookings cannot be confirmed (402) — use “Mark paid” first.',
      });
    } else if (kind === 'cancel' || kind === 'status') {
      setAction({
        id, title: `Cancel booking #${id}`, url: `/admin/bookings/${id}/cancel`, policy: true, confirmLabel: 'Cancel booking', color: 'red',
        successMessage: `Booking #${id} cancelled`, description: 'Applies the §7 cancellation policy, releases/refunds the payment and notifies the parties.',
      });
    }
  };

  const fc = v => v != null ? `$${(Number(v) / 100).toFixed(2)}` : '—';

  return (
    <div className="page-bookings">
      {selected && <BookingDrawer key={`${selected.id}-${selected.status}-${selected.trip_stage}-${selected.driver_id}`} booking={selected} drivers={drivers} onClose={() => setSelected(null)} onAction={doAction} />}
      {action && <LegacyActionModal action={action} onClose={() => setAction(null)} onDone={() => refreshAfter(action.id)} />}
      {confirm && <Confirm message={confirm.msg} onCancel={() => setConfirm(null)}
        onConfirm={() => { doAction(confirm.id, confirm.action); setConfirm(null); }} />}

      <div className="page-toolbar">
        <div className="tab-bar" style={{ flexWrap: 'wrap', gap: 4 }}>
          {B_STATUSES.map(s => (
            <button key={s} className={`tab-btn ${filter === s ? 'tab-btn--active' : ''}`}
              onClick={() => setFilter(s)}>{B_LABELS[s]}</button>
          ))}
        </div>
      </div>
      <div className="page-toolbar" style={{ paddingTop: 0 }}>
        <form onSubmit={e => { e.preventDefault(); setPage(1); load(1, search, filter); }} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Search pickup, destination, customer…" value={search} onChange={e => setSearch(e.target.value)} />
          <button type="submit" className="btn btn-sm">Search</button>
        </form>
        <span className="toolbar-info">{total} bookings</span>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={() => load()} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th><th>Customer</th><th>Driver</th><th>Route</th>
                <th>Price</th><th>Payment</th><th>Status</th><th>Stage</th><th>Date</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map(b => (
                <tr key={b.id}>
                  <td style={{ fontWeight: 700 }}>#{b.id}</td>
                  <td>{b.customer_name || `#${b.customer_id}`}</td>
                  <td>{b.driver_name || (b.driver_id ? `#${b.driver_id}` : <em className="unassigned">Unassigned</em>)}</td>
                  <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {b.pickup_place_name || b.pickup_address || '?'} → {b.destination_place_name || b.destination_address || '?'}
                  </td>
                  <td>{fc(b.agreed_price || b.customer_proposed_price)}</td>
                  <td><span className={`badge badge-${b.payment_status === 'paid' ? 'success' : 'warning'}`}>{b.payment_status || 'unpaid'}</span></td>
                  <td><span className={`badge badge-${b.status}`}>{b.status}</span></td>
                  <td><StageCell stage={b.trip_stage} /></td>
                  <td>{(b.scheduled_at || b.created_at)?.slice(0, 10)}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="View / Manage" onClick={() => openDetail(b)}><FiEye /></button>
                    {b.payment_status !== 'paid' && !isTerminal(b.trip_stage, b.status) && (
                      <button className="btn btn-xs btn-success" title="Mark Paid (reason required)"
                        onClick={() => doAction(b.id, 'markPaid')}><FiCheck /></button>
                    )}
                    {!isTerminal(b.trip_stage, b.status) && (
                      <button className="btn btn-xs btn-danger" title="Cancel Booking (reason required)"
                        onClick={() => doAction(b.id, 'cancel')}><FiXCircle /></button>
                    )}
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="10" className="empty-state">No bookings found</td></tr>}
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
