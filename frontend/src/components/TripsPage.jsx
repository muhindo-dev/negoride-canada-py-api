import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import {
  FiSearch, FiChevronLeft, FiChevronRight, FiX, FiEye, FiXCircle, FiAlertTriangle,
} from 'react-icons/fi';

const T_STATUSES = ['', 'Pending', 'Active', 'Ongoing', 'Completed', 'Cancelled'];

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

function TripDrawer({ trip, onClose, onAction }) {
  const [newStatus, setNewStatus] = useState(trip.status || '');
  const [saving, setSaving] = useState(false);
  const act = async (action, p = {}) => { setSaving(true); try { await onAction(trip.id, action, p); } finally { setSaving(false); } };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>Trip #{trip.id}</h2>
          <span className={`badge badge-${trip.status?.toLowerCase()}`}>{trip.status}</span>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="d-section">
            <h4>Trip Info</h4>
            <div className="d-row"><span className="dk">From</span><span className="dv">{trip.start_name || '—'}</span></div>
            <div className="d-row"><span className="dk">To</span><span className="dv">{trip.end_name || '—'}</span></div>
            <div className="d-row"><span className="dk">Car Model</span><span className="dv">{trip.car_model || '—'}</span></div>
            <div className="d-row"><span className="dk">Reg Number</span><span className="dv">{trip.vehicel_reg_number || '—'}</span></div>
            <div className="d-row"><span className="dk">Seats Total</span><span className="dv">{trip.total_seats ?? '—'}</span></div>
            <div className="d-row"><span className="dk">Slots Available</span><span className="dv">{trip.slots ?? '—'}</span></div>
            <div className="d-row"><span className="dk">Price/Seat</span><span className="dv">{trip.amount_per_seat != null ? `$${Number(trip.amount_per_seat).toFixed(2)}` : '—'}</span></div>
            <div className="d-row"><span className="dk">Trip Note</span><span className="dv">{trip.trip_note || '—'}</span></div>
            <div className="d-row"><span className="dk">Created</span><span className="dv">{trip.created_at?.slice(0, 16)}</span></div>
          </div>
          {trip.driver && (
            <div className="d-section">
              <h4>Driver</h4>
              <div className="d-row"><span className="dk">Name</span><span className="dv">{trip.driver.name}</span></div>
              <div className="d-row"><span className="dk">Phone</span><span className="dv">{trip.driver.phone_number || '—'}</span></div>
              <div className="d-row"><span className="dk">Vehicle</span><span className="dv">{trip.driver.automobile || '—'}</span></div>
              <div className="d-row"><span className="dk">License</span><span className="dv">{trip.driver.driving_license_number || '—'}</span></div>
            </div>
          )}
          {trip.bookings?.length > 0 && (
            <div className="d-section">
              <h4>Passengers ({trip.bookings.length})</h4>
              {trip.bookings.map(b => (
                <div key={b.id} style={{ padding: '7px 0', borderBottom: '1px solid var(--grey-5)', fontSize: 13, display: 'flex', justifyContent: 'space-between' }}>
                  <span>{b.customer_name || `User #${b.customer_id}`}</span>
                  <span className={`badge badge-${b.status}`}>{b.status}</span>
                </div>
              ))}
            </div>
          )}
          {!['Completed', 'Cancelled'].includes(trip.status) && (
            <div className="d-section">
              <h4>Update Status</h4>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <select className="d-select" value={newStatus} onChange={e => setNewStatus(e.target.value)}>
                  {['Pending', 'Active', 'Ongoing', 'Completed', 'Cancelled'].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
                <button className="btn btn-sm btn-accent" disabled={saving || newStatus === trip.status} onClick={() => act('status', { status: newStatus })}>Save</button>
              </div>
              <button className="btn btn-sm btn-danger" disabled={saving} onClick={() => act('cancel')}><FiXCircle /> Cancel Trip</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function TripsPage() {
  const [trips, setTrips] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const perPage = 20;
  const totalPages = Math.ceil(total / perPage);

  const load = (p = page, q = search, f = filter) => {
    setLoading(true); setError(null);
    const params = { page: p, per_page: perPage };
    if (q) params.search = q;
    if (f) params.status = f;
    adminAPI.trips(params)
      .then(({ data }) => {
        if (data.code === 1) { setTrips(data.data?.data || []); setTotal(data.data?.total || 0); }
        else setError(data.message || 'Failed to load trips');
      })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { setPage(1); load(1, '', filter); }, [filter]);

  const openDetail = async item => {
    try { const { data } = await adminAPI.tripShow(item.id); setSelected(data.code === 1 ? data.data : item); }
    catch { setSelected(item); }
  };

  const doAction = async (id, action, params = {}) => {
    try {
      if (action === 'status') await adminAPI.tripStatus(id, params);
      else if (action === 'cancel') await adminAPI.tripCancel(id);
      const { data } = await adminAPI.tripShow(id);
      if (data.code === 1) setSelected(data.data);
      load(page, search, filter);
    } catch {}
  };

  return (
    <div className="page-trips">
      {selected && <TripDrawer trip={selected} onClose={() => setSelected(null)} onAction={doAction} />}
      {confirm && <Confirm message={confirm.msg} onCancel={() => setConfirm(null)}
        onConfirm={() => { doAction(confirm.id, confirm.action); setConfirm(null); }} />}

      <div className="page-toolbar">
        <div className="tab-bar" style={{ flexWrap: 'wrap', gap: 4 }}>
          {T_STATUSES.map(s => (
            <button key={s} className={`tab-btn ${filter === s ? 'tab-btn--active' : ''}`}
              onClick={() => setFilter(s)}>{s || 'All'}</button>
          ))}
        </div>
      </div>
      <div className="page-toolbar" style={{ paddingTop: 0 }}>
        <form onSubmit={e => { e.preventDefault(); setPage(1); load(1, search, filter); }} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Search route, car model, reg number…" value={search} onChange={e => setSearch(e.target.value)} />
          <button type="submit" className="btn btn-sm">Search</button>
        </form>
        <span className="toolbar-info">{total} trips</span>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={() => load()} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th><th>Driver</th><th>From</th><th>To</th>
                <th>Car</th><th>Reg#</th><th>Slots</th><th>$/Seat</th><th>Status</th><th>Date</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {trips.map(t => (
                <tr key={t.id}>
                  <td style={{ fontWeight: 700 }}>#{t.id}</td>
                  <td>{t.driver_name || `#${t.driver_id}`}</td>
                  <td>{t.start_name || '—'}</td>
                  <td>{t.end_name || '—'}</td>
                  <td>{t.car_model || '—'}</td>
                  <td>{t.vehicel_reg_number || '—'}</td>
                  <td>{t.slots ?? '—'}</td>
                  <td>{t.amount_per_seat != null ? `$${Number(t.amount_per_seat).toFixed(2)}` : '—'}</td>
                  <td><span className={`badge badge-${t.status?.toLowerCase()}`}>{t.status}</span></td>
                  <td>{t.created_at?.slice(0, 10)}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="View / Manage" onClick={() => openDetail(t)}><FiEye /></button>
                    {!['Completed', 'Cancelled'].includes(t.status) && (
                      <button className="btn btn-xs btn-danger" title="Cancel Trip"
                        onClick={() => setConfirm({ id: t.id, action: 'cancel', msg: `Cancel trip #${t.id}? All passengers will be notified.` })}><FiXCircle /></button>
                    )}
                  </td>
                </tr>
              ))}
              {!trips.length && <tr><td colSpan="11" className="empty-state">No trips found</td></tr>}
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
