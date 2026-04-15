import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiPlus, FiEdit2, FiTrash2, FiX, FiAlertTriangle, FiSave, FiSearch, FiChevronLeft, FiChevronRight } from 'react-icons/fi';

const EMPTY_STAGE = { name: '', latitute: '', longitude: '', details: '' };

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
          <button className="btn btn-sm btn-danger" onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </div>
  );
}

function StageDrawer({ stage, onClose, onSave }) {
  const [form, setForm] = useState(stage ? { ...stage } : { ...EMPTY_STAGE });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const set = (key, val) => setForm(prev => ({ ...prev, [key]: val }));
  const isNew = !stage;

  const save = async () => {
    if (!form.name?.trim()) { setErr('Stage name is required'); return; }
    setSaving(true); setErr('');
    try {
      if (isNew) await adminAPI.routeStageCreate(form);
      else await adminAPI.routeStageUpdate(stage.id, form);
      onSave();
    } catch (e) {
      setErr(e?.response?.data?.message || 'Failed to save');
    } finally { setSaving(false); }
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 400 }}>
        <div className="drawer-head">
          <h2>{isNew ? 'New Route Stage' : `Edit: ${stage.name}`}</h2>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="form-grid" style={{ gridTemplateColumns: '1fr', gap: 12 }}>
            <div className="form-group">
              <label>Stage Name *</label>
              <input className="d-input" value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Downtown Terminal" />
            </div>
            <div className="form-group">
              <label>Latitude</label>
              <input className="d-input" type="number" step="any" value={form.latitute} onChange={e => set('latitute', e.target.value)} placeholder="e.g. 43.6532" />
            </div>
            <div className="form-group">
              <label>Longitude</label>
              <input className="d-input" type="number" step="any" value={form.longitude} onChange={e => set('longitude', e.target.value)} placeholder="e.g. -79.3832" />
            </div>
            <div className="form-group">
              <label>Details / Description</label>
              <textarea className="d-textarea" value={form.details || ''} onChange={e => set('details', e.target.value)} rows={3} placeholder="Optional notes about this stage…" />
            </div>
          </div>
          {err && <p style={{ color: 'var(--error)', fontSize: 13, marginTop: 10 }}>{err}</p>}
        </div>
        <div className="drawer-footer">
          <button className="btn btn-sm btn-accent" disabled={saving} onClick={save} style={{ flex: 1 }}>
            <FiSave /> {saving ? 'Saving…' : isNew ? 'Create Stage' : 'Save Changes'}
          </button>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

export default function RouteStagesPage() {
  const [items, setItems] = useState([]);
  const [allItems, setAllItems] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null); /* null=closed, false=new, obj=edit */
  const [confirm, setConfirm] = useState(null);

  const load = () => {
    setLoading(true); setError(null);
    adminAPI.routeStages()
      .then(({ data }) => {
        if (data.code === 1) { setAllItems(data.data || []); setItems(data.data || []); }
        else setError(data.message || 'Failed to load');
      })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!search.trim()) { setItems(allItems); return; }
    const q = search.toLowerCase();
    setItems(allItems.filter(s => (s.name || '').toLowerCase().includes(q) || (s.details || '').toLowerCase().includes(q)));
  }, [search, allItems]);

  const doDelete = async id => {
    try {
      await adminAPI.routeStageDelete(id);
      const updated = allItems.filter(s => s.id !== id);
      setAllItems(updated);
      setItems(search.trim() ? updated.filter(s => s.name?.toLowerCase().includes(search.toLowerCase())) : updated);
    } catch {}
  };

  return (
    <div className="page-route-stages">
      {editing !== null && (
        <StageDrawer
          stage={editing || null}
          onClose={() => setEditing(null)}
          onSave={() => { setEditing(null); load(); }}
        />
      )}
      {confirm && (
        <Confirm
          message={`Delete route stage "${confirm.name}"? This cannot be undone.`}
          onCancel={() => setConfirm(null)}
          onConfirm={() => { doDelete(confirm.id); setConfirm(null); }}
        />
      )}

      <div className="page-toolbar">
        <form onSubmit={e => e.preventDefault()} className="search-form">
          <FiSearch className="search-icon" />
          <input placeholder="Search stages by name or details…" value={search} onChange={e => setSearch(e.target.value)} />
        </form>
        <span className="toolbar-info">{items.length} of {allItems.length} stages</span>
        <button className="btn btn-sm btn-accent" onClick={() => setEditing(false)}><FiPlus /> Add Stage</button>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={load} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>Name</th><th>Latitude</th><th>Longitude</th><th>Details</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {items.map(s => (
                <tr key={s.id}>
                  <td style={{ fontWeight: 700 }}>#{s.id}</td>
                  <td style={{ fontWeight: 600 }}>{s.name || '—'}</td>
                  <td style={{ fontSize: 12, fontFamily: 'monospace' }}>{s.latitute || '—'}</td>
                  <td style={{ fontSize: 12, fontFamily: 'monospace' }}>{s.longitude || '—'}</td>
                  <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>
                    {s.details || '—'}
                  </td>
                  <td className="actions">
                    <button className="btn btn-xs" title="Edit" onClick={() => setEditing(s)}><FiEdit2 /></button>
                    <button className="btn btn-xs btn-danger" title="Delete" onClick={() => setConfirm(s)}><FiTrash2 /></button>
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="6" className="empty-state">No route stages found</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
