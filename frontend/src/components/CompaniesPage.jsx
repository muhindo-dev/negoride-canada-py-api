import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiPlus, FiEdit2, FiTrash2, FiX, FiAlertTriangle, FiSave } from 'react-icons/fi';

const EMPTY_COMPANY = { name: '', short_name: '', email: '', phone_number: '', phone_number_2: '', address: '', website: '', subdomain: '', type: '', color: '', welcome_message: '', p_o_box: '', details: '' };

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

function CompanyDrawer({ company, onClose, onSave }) {
  const [form, setForm] = useState(company || EMPTY_COMPANY);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const set = (key, val) => setForm(prev => ({ ...prev, [key]: val }));

  const save = async () => {
    if (!form.name?.trim()) { setErr('Company name is required'); return; }
    setSaving(true); setErr('');
    try {
      if (company) await adminAPI.companyUpdate(company.id, form);
      else await adminAPI.companyCreate(form);
      onSave();
    } catch (e) {
      setErr(e?.response?.data?.message || 'Failed to save');
    } finally { setSaving(false); }
  };

  const isNew = !company;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-panel" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <h2>{isNew ? 'New Company' : `Edit: ${company.name}`}</h2>
          <button className="drawer-close" onClick={onClose}><FiX /></button>
        </div>
        <div className="drawer-body">
          <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {[
              { key: 'name', label: 'Company Name *', full: true },
              { key: 'short_name', label: 'Short Name' },
              { key: 'type', label: 'Type' },
              { key: 'email', label: 'Email' },
              { key: 'phone_number', label: 'Phone' },
              { key: 'phone_number_2', label: 'Phone 2' },
              { key: 'address', label: 'Address', full: true },
              { key: 'website', label: 'Website' },
              { key: 'subdomain', label: 'Subdomain' },
              { key: 'color', label: 'Brand Color', hint: 'e.g. #EF9B11' },
              { key: 'p_o_box', label: 'P.O. Box' },
            ].map(f => (
              <div key={f.key} className="form-group" style={{ gridColumn: f.full ? '1 / -1' : undefined }}>
                <label>{f.label}</label>
                <input className="d-input" value={form[f.key] || ''} onChange={e => set(f.key, e.target.value)} placeholder={f.hint || ''} />
              </div>
            ))}
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label>Welcome Message</label>
              <textarea className="d-textarea" value={form.welcome_message || ''} onChange={e => set('welcome_message', e.target.value)} rows={2} />
            </div>
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label>Details / Description</label>
              <textarea className="d-textarea" value={form.details || ''} onChange={e => set('details', e.target.value)} rows={3} />
            </div>
          </div>
          {err && <p style={{ color: 'var(--error)', fontSize: 13, marginTop: 12 }}>{err}</p>}
        </div>
        <div className="drawer-footer">
          <button className="btn btn-sm btn-accent" disabled={saving} onClick={save} style={{ flex: 1 }}>
            <FiSave /> {saving ? 'Saving…' : isNew ? 'Create Company' : 'Save Changes'}
          </button>
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

export default function CompaniesPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null); /* null=closed, false=new, object=edit */
  const [confirm, setConfirm] = useState(null);

  const load = () => {
    setLoading(true); setError(null);
    adminAPI.companies()
      .then(({ data }) => { if (data.code === 1) setItems(data.data || []); else setError(data.message || 'Failed to load'); })
      .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const doDelete = async id => {
    try {
      await adminAPI.companyDelete(id);
      setItems(prev => prev.filter(c => c.id !== id));
    } catch {}
  };

  return (
    <div className="page-companies">
      {editing !== null && (
        <CompanyDrawer
          company={editing || null}
          onClose={() => setEditing(null)}
          onSave={() => { setEditing(null); load(); }}
        />
      )}
      {confirm && (
        <Confirm
          message={`Delete company "${confirm.name}"? This cannot be undone.`}
          onCancel={() => setConfirm(null)}
          onConfirm={() => { doDelete(confirm.id); setConfirm(null); }}
        />
      )}

      <div className="page-toolbar">
        <span className="toolbar-info">{items.length} companies</span>
        <button className="btn btn-sm btn-accent" onClick={() => setEditing(false)}><FiPlus /> Add Company</button>
      </div>

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={load} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>Name</th><th>Short Name</th><th>Email</th><th>Phone</th><th>Type</th><th>Website</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {items.map(c => (
                <tr key={c.id}>
                  <td style={{ fontWeight: 700 }}>#{c.id}</td>
                  <td style={{ fontWeight: 600 }}>{c.name || '—'}</td>
                  <td>{c.short_name || '—'}</td>
                  <td>{c.email || '—'}</td>
                  <td>{c.phone_number || '—'}</td>
                  <td>{c.type || '—'}</td>
                  <td style={{ fontSize: 12 }}>{c.website || '—'}</td>
                  <td className="actions">
                    <button className="btn btn-xs" title="Edit" onClick={() => setEditing(c)}><FiEdit2 /></button>
                    <button className="btn btn-xs btn-danger" title="Delete" onClick={() => setConfirm(c)}><FiTrash2 /></button>
                  </td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan="8" className="empty-state">No companies found</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
