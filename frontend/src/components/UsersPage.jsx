import React, { useEffect, useState, useCallback } from 'react';
import { adminAPI } from '../services/api';
import {
  FiCheck, FiX, FiToggleLeft, FiToggleRight, FiSearch, FiChevronLeft,
  FiChevronRight, FiEdit2, FiTrash2, FiUser, FiAlertTriangle,
  FiRefreshCw, FiFilter, FiKey, FiDollarSign, FiEye, FiEyeOff,
  FiChevronDown, FiSave, FiXCircle, FiFileText, FiCamera,
} from 'react-icons/fi';

/* ─── helpers ─────────────────────────────────────────────────────────── */
const BADGE = {
  active:   { bg: '#e8f5e9', color: '#388e3c', label: 'Active' },
  inactive: { bg: '#ffebee', color: '#d32f2f', label: 'Inactive' },
  Yes:      { bg: '#e8f5e9', color: '#388e3c', label: 'Yes' },
  No:       { bg: '#f5f5f5', color: '#999',    label: 'No'  },
  Driver:           { bg: '#e3f2fd', color: '#1565c0', label: 'Driver' },
  'Pending Driver': { bg: '#fff3e0', color: '#e65100', label: 'Pending' },
  Customer:         { bg: '#f3e5f5', color: '#6a1b9a', label: 'Customer' },
  Admin:            { bg: '#fce4ec', color: '#880e4f', label: 'Admin' },
  'Super Admin':    { bg: '#fce4ec', color: '#880e4f', label: 'Super Admin' },
};

function Badge({ val, label }) {
  const cfg = BADGE[val] || { bg: '#f5f5f5', color: '#666', label: val || '—' };
  return (
    <span style={{
      background: cfg.bg, color: cfg.color, padding: '2px 8px',
      borderRadius: 3, fontSize: 11, fontWeight: 700, display: 'inline-block',
      whiteSpace: 'nowrap',
    }}>
      {label || cfg.label}
    </span>
  );
}

function Avatar({ name, avatar }) {
  if (avatar) return <img src={avatar} alt="" style={{ width: 32, height: 32, borderRadius: '50%', objectFit: 'cover' }} />;
  const init = (name || '?')[0].toUpperCase();
  return (
    <div style={{
      width: 32, height: 32, borderRadius: '50%', background: '#EF9B11',
      color: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontWeight: 700, fontSize: 13, flexShrink: 0,
    }}>{init}</div>
  );
}

/* ─── Driver Application Drawer ───────────────────────────────────────── */
const SERVICES = [
  { key: 'car',        label: 'Special Hire / Private Rides', icon: '🚗' },
  { key: 'delivery',   label: 'Courier / Delivery',           icon: '📦' },
  { key: 'boda',       label: 'Boda Boda / Motorcycle',       icon: '🏍️' },
  { key: 'ambulance',  label: 'Ambulance',                    icon: '🚑' },
  { key: 'police',     label: 'Police',                       icon: '🚔' },
  { key: 'breakdown',  label: 'Breakdown Recovery',           icon: '🔧' },
  { key: 'firebrugade',label: 'Fire Brigade',                 icon: '🚒' },
];

function DriverApplicationDrawer({ user: initialUser, onClose, onApproved, onRejected }) {
  const [user, setUser] = useState(initialUser);
  const [services, setServices] = useState(() => {
    const s = {};
    SERVICES.forEach(({ key }) => {
      // Pre-check applied services; default car+delivery if none applied
      s[key] = initialUser[`is_${key}`] === 'Yes';
    });
    if (!Object.values(s).some(Boolean)) s['car'] = true; // sensible default
    return s;
  });
  const [loading, setLoading] = useState(false);
  const [photoOpen, setPhotoOpen] = useState(false);
  const [msg, setMsg] = useState(null);
  const [rejecting, setRejecting] = useState(false);

  // Resolve photo URL — handles both legacy (no path prefix) and new (images/xxx) paths
  const photoUrl = user.driving_license_photo
    ? (user.driving_license_photo.startsWith('http')
        ? user.driving_license_photo
        : `/uploads/${user.driving_license_photo}`)
    : null;

  const handleApprove = async () => {
    setLoading(true);
    setMsg(null);
    const selected = Object.keys(services).filter((k) => services[k]);
    try {
      const { data } = await adminAPI.approveDriver(user.id, { services: selected });
      if (data.code === 1) {
        setMsg({ type: 'success', text: `Driver approved! Services: ${selected.join(', ')}` });
        setUser(data.data);
        if (onApproved) onApproved(data.data);
      } else {
        setMsg({ type: 'error', text: data.message || 'Approval failed' });
      }
    } catch {
      setMsg({ type: 'error', text: 'Network error' });
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    setLoading(true);
    setMsg(null);
    try {
      const { data } = await adminAPI.rejectDriver(user.id);
      if (data.code === 1) {
        setMsg({ type: 'success', text: 'Driver application rejected.' });
        setUser(data.data);
        if (onRejected) onRejected(data.data);
      } else {
        setMsg({ type: 'error', text: data.message || 'Rejection failed' });
      }
    } catch {
      setMsg({ type: 'error', text: 'Network error' });
    } finally {
      setLoading(false);
      setRejecting(false);
    }
  };

  const dRow = (label, value) => (
    <div style={{ display: 'flex', padding: '9px 0', borderBottom: '1px solid #f5f5f5', gap: 8 }}>
      <span style={{ fontSize: 12, color: '#888', fontWeight: 600, minWidth: 160, flexShrink: 0 }}>{label}</span>
      <span style={{ fontSize: 13, color: '#111', fontWeight: 500, wordBreak: 'break-word' }}>{value || <span style={{ color: '#bbb' }}>—</span>}</span>
    </div>
  );

  const isApproved = user.user_type === 'Driver';

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1500, display: 'flex' }} onClick={onClose}>
      <div style={{ flex: 1, background: 'rgba(0,0,0,0.5)' }} />
      <div
        style={{
          width: 580, maxWidth: '95vw', background: '#fff', display: 'flex',
          flexDirection: 'column', height: '100%', boxShadow: '-4px 0 32px rgba(0,0,0,0.18)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div style={{ padding: '16px 20px', borderBottom: '3px solid #EF9B11', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0, background: '#040404' }}>
          <div style={{ width: 40, height: 40, borderRadius: '50%', background: '#EF9B11', color: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 18, flexShrink: 0 }}>
            {(user.name || user.first_name || '?')[0].toUpperCase()}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 16, color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user.name || `${user.first_name || ''} ${user.last_name || ''}`.trim()} — Driver Application
            </div>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.5)' }}>
              #{user.id} · {user.email || user.phone_number || user.username}
            </div>
          </div>
          {isApproved
            ? <span style={{ background: '#e8f5e9', color: '#388e3c', padding: '3px 10px', fontWeight: 700, fontSize: 12, borderRadius: 3 }}>✓ APPROVED</span>
            : <span style={{ background: '#fff3e0', color: '#e65100', padding: '3px 10px', fontWeight: 700, fontSize: 12, borderRadius: 3 }}>⏳ PENDING</span>
          }
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(255,255,255,0.6)', padding: 4 }}>
            <FiXCircle size={22} />
          </button>
        </div>

        {/* body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>

          {/* status message */}
          {msg && (
            <div style={{
              padding: '12px 16px', marginBottom: 20, fontSize: 13, borderRadius: 3,
              background: msg.type === 'success' ? '#e8f5e9' : '#ffebee',
              color: msg.type === 'success' ? '#388e3c' : '#d32f2f',
              border: `1px solid ${msg.type === 'success' ? '#c8e6c9' : '#ffcdd2'}`,
              display: 'flex', gap: 8, alignItems: 'center',
            }}>
              {msg.type === 'success' ? <FiCheck size={15} /> : <FiAlertTriangle size={15} />}
              <strong>{msg.text}</strong>
            </div>
          )}

          {/* Personal Info */}
          <section style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 1, color: '#EF9B11', marginBottom: 10, borderBottom: '2px solid #EF9B11', paddingBottom: 6 }}>
              👤 Personal Information
            </div>
            {dRow('Full Name', `${user.first_name || ''} ${user.last_name || ''}`.trim() || user.name)}
            {dRow('Email', user.email)}
            {dRow('Phone', user.phone_number)}
            {dRow('Date of Birth', user.date_of_birth)}
            {dRow('National ID / SIN', user.nin)}
            {dRow('Address', user.current_address)}
          </section>

          {/* License Info */}
          <section style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 1, color: '#EF9B11', marginBottom: 10, borderBottom: '2px solid #EF9B11', paddingBottom: 6 }}>
              🪪 Driving License
            </div>
            {dRow('License Number', user.driving_license_number)}
            {dRow('Issuing Authority', user.driving_license_issue_authority)}
            {dRow('Issue Date', user.driving_license_issue_date)}
            {dRow('Expiry Date', user.driving_license_validity)}
            {dRow('Vehicle / Automobile', user.automobile)}
          </section>

          {/* License Photo */}
          <section style={{ marginBottom: 24 }}>
            <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 1, color: '#EF9B11', marginBottom: 10, borderBottom: '2px solid #EF9B11', paddingBottom: 6 }}>
              📷 License Photo
            </div>
            {photoUrl ? (
              <div>
                <img
                  src={photoUrl}
                  alt="Driving License"
                  onClick={() => setPhotoOpen(true)}
                  style={{
                    width: '100%', maxHeight: 280, objectFit: 'contain', border: '2px solid #eee',
                    cursor: 'zoom-in', background: '#f7f7f7', display: 'block',
                  }}
                  onError={(e) => { e.target.style.display = 'none'; }}
                />
                <p style={{ fontSize: 11, color: '#999', marginTop: 6, textAlign: 'center' }}>
                  Click image to view full size · <a href={photoUrl} target="_blank" rel="noreferrer" style={{ color: '#EF9B11' }}>Open in new tab</a>
                </p>
                {/* Full-screen lightbox */}
                {photoOpen && (
                  <div
                    onClick={() => setPhotoOpen(false)}
                    style={{
                      position: 'fixed', inset: 0, zIndex: 3000, background: 'rgba(0,0,0,0.92)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'zoom-out',
                    }}
                  >
                    <img src={photoUrl} alt="License" style={{ maxWidth: '90vw', maxHeight: '90vh', objectFit: 'contain' }} />
                    <button onClick={() => setPhotoOpen(false)} style={{ position: 'absolute', top: 20, right: 20, background: 'none', border: 'none', color: '#fff', fontSize: 28, cursor: 'pointer' }}>✕</button>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ background: '#f7f7f7', border: '2px dashed #ddd', padding: 24, textAlign: 'center', color: '#bbb' }}>
                <FiCamera size={32} style={{ display: 'block', margin: '0 auto 8px' }} />
                No license photo uploaded yet
              </div>
            )}
          </section>

          {/* Services to Approve */}
          {!isApproved && (
            <section style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 1, color: '#EF9B11', marginBottom: 10, borderBottom: '2px solid #EF9B11', paddingBottom: 6 }}>
                ✓ Services to Approve
              </div>
              <p style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
                Check which services to grant this driver. Applied services are pre-selected.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {SERVICES.map(({ key, label, icon }) => {
                  const applied = initialUser[`is_${key}`] === 'Yes';
                  const checked = services[key];
                  return (
                    <label key={key} style={{
                      display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px',
                      border: `2px solid ${checked ? '#4caf50' : '#e0e0e0'}`,
                      background: checked ? '#f1f8e9' : '#fafafa',
                      cursor: 'pointer', borderRadius: 3,
                    }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => setServices((s) => ({ ...s, [key]: !s[key] }))}
                        style={{ width: 16, height: 16, accentColor: '#4caf50', cursor: 'pointer' }}
                      />
                      <span style={{ fontSize: 13, fontWeight: 600, color: checked ? '#388e3c' : '#444' }}>
                        {icon} {label}
                      </span>
                      {applied && (
                        <span style={{ fontSize: 10, background: '#e3f2fd', color: '#1565c0', padding: '1px 5px', borderRadius: 3, marginLeft: 'auto', whiteSpace: 'nowrap' }}>
                          Applied
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            </section>
          )}

          {/* Already approved services */}
          {isApproved && (
            <section style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 1, color: '#EF9B11', marginBottom: 10, borderBottom: '2px solid #EF9B11', paddingBottom: 6 }}>
                ✓ Approved Services
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {SERVICES.filter(({ key }) => user[`is_${key}_approved`] === 'Yes').map(({ key, label, icon }) => (
                  <span key={key} style={{ background: '#e8f5e9', color: '#388e3c', padding: '5px 12px', fontWeight: 700, fontSize: 12, borderRadius: 3 }}>
                    {icon} {label}
                  </span>
                ))}
              </div>
            </section>
          )}
        </div>

        {/* footer */}
        <div style={{ padding: '16px 20px', borderTop: '2px solid #eee', flexShrink: 0, background: '#fafafa' }}>
          {!isApproved && !rejecting && (
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={() => setRejecting(true)}
                disabled={loading}
                style={{
                  flex: 1, padding: '13px 20px', fontSize: 14, fontWeight: 700,
                  border: '2px solid #d32f2f', background: '#ffebee', color: '#d32f2f',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                }}
              >
                <FiX size={16} /> Reject Application
              </button>
              <button
                onClick={handleApprove}
                disabled={loading || !Object.values(services).some(Boolean)}
                style={{
                  flex: 2, padding: '13px 20px', fontSize: 15, fontWeight: 800,
                  background: loading ? '#ccc' : '#4caf50', color: '#fff', border: 'none',
                  cursor: loading ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                }}
              >
                <FiCheck size={18} /> {loading ? 'Approving…' : 'Approve Driver'}
              </button>
            </div>
          )}
          {rejecting && (
            <div>
              <p style={{ fontSize: 13, color: '#d32f2f', fontWeight: 600, marginBottom: 12 }}>
                ⚠️ Are you sure you want to REJECT this driver application? The user will be demoted back to Customer.
              </p>
              <div style={{ display: 'flex', gap: 10 }}>
                <button onClick={() => setRejecting(false)} style={{ flex: 1, padding: '11px 16px', border: '1.5px solid #ccc', background: '#fff', cursor: 'pointer', fontWeight: 600, fontSize: 13 }}>Cancel</button>
                <button onClick={handleReject} disabled={loading} style={{ flex: 1, padding: '11px 16px', border: 'none', background: '#d32f2f', color: '#fff', cursor: 'pointer', fontWeight: 700, fontSize: 14 }}>
                  {loading ? 'Rejecting…' : 'Confirm Reject'}
                </button>
              </div>
            </div>
          )}
          {isApproved && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ color: '#388e3c', fontWeight: 700, fontSize: 14 }}>✓ This driver is approved and active.</span>
              <button
                onClick={() => setRejecting(true)}
                style={{ marginLeft: 'auto', padding: '8px 14px', border: '1.5px solid #d32f2f', background: '#ffebee', color: '#d32f2f', cursor: 'pointer', fontSize: 12, fontWeight: 700 }}
              >
                Revoke
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Confirm({ message, onConfirm, onCancel }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', display: 'flex',
      alignItems: 'center', justifyContent: 'center', zIndex: 2000,
    }}>
      <div style={{ background: '#fff', border: '2px solid #040404', padding: 28, maxWidth: 380, width: '90%' }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', marginBottom: 20 }}>
          <FiAlertTriangle size={22} color="#f44336" style={{ flexShrink: 0, marginTop: 2 }} />
          <p style={{ fontSize: 15, lineHeight: 1.5 }}>{message}</p>
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn-sm btn-secondary" onClick={onCancel}>Cancel</button>
          <button className="btn btn-sm btn-danger" onClick={onConfirm}>Confirm</button>
        </div>
      </div>
    </div>
  );
}

/* ─── Edit Drawer ──────────────────────────────────────────────────────── */
const FIELD_GROUPS = [
  {
    title: 'Personal Info',
    fields: [
      { key: 'first_name',     label: 'First Name',    type: 'text' },
      { key: 'last_name',      label: 'Last Name',     type: 'text' },
      { key: 'name',           label: 'Display Name',  type: 'text' },
      { key: 'email',          label: 'Email',         type: 'email' },
      { key: 'phone_number',   label: 'Phone',         type: 'text' },
      { key: 'date_of_birth',  label: 'Date of Birth', type: 'date' },
      {
        key: 'sex', label: 'Gender', type: 'select',
        options: ['Male', 'Female', 'Other'],
      },
      { key: 'current_address', label: 'Address', type: 'textarea' },
    ],
  },
  {
    title: 'Account Settings',
    fields: [
      {
        key: 'user_type', label: 'User Type', type: 'select',
        options: ['Customer', 'Pending Driver', 'Driver', 'Admin', 'Super Admin'],
      },
      {
        key: 'status', label: 'Status', type: 'select',
        options: [{ value: '1', label: 'Active' }, { value: '0', label: 'Inactive' }],
      },
      { key: 'country_name',       label: 'Country',      type: 'text' },
      { key: 'country_code',       label: 'Country Code', type: 'text' },
      { key: 'country_short_name', label: 'Country ISO',  type: 'text' },
    ],
  },
  {
    title: 'Driver Details',
    fields: [
      { key: 'driving_license_number',     label: 'License Number',    type: 'text' },
      { key: 'nin',                        label: 'National ID / SIN', type: 'text' },
      { key: 'driving_license_issue_date', label: 'License Issued',    type: 'date' },
      { key: 'driving_license_validity',   label: 'License Expiry',    type: 'date' },
      { key: 'driving_license_issue_authority', label: 'Issuing Authority', type: 'text' },
      { key: 'automobile',                 label: 'Vehicle Type',      type: 'text' },
      {
        key: 'max_passengers', label: 'Max Passengers', type: 'number',
        attrs: { min: 1, max: 20 },
      },
    ],
  },
  {
    title: 'Service Permissions',
    cols: 2,
    fields: [
      { key: 'is_car',       label: 'Car',        type: 'yesno' },
      { key: 'is_car_approved',   label: 'Car Approved',  type: 'yesno' },
      { key: 'is_delivery',  label: 'Delivery',   type: 'yesno' },
      { key: 'is_delivery_approved', label: 'Del. Approved', type: 'yesno' },
      { key: 'is_boda',      label: 'Boda',       type: 'yesno' },
      { key: 'is_boda_approved',  label: 'Boda Approved', type: 'yesno' },
      { key: 'is_ambulance', label: 'Ambulance',  type: 'yesno' },
      { key: 'is_ambulance_approved', label: 'Amb. Approved', type: 'yesno' },
      { key: 'is_police',    label: 'Police',     type: 'yesno' },
      { key: 'is_police_approved', label: 'Police Approved', type: 'yesno' },
      { key: 'is_breakdown', label: 'Breakdown',  type: 'yesno' },
      { key: 'is_breakdown_approved', label: 'Bkd. Approved', type: 'yesno' },
      { key: 'is_firebrugade', label: 'Fire',     type: 'yesno' },
      { key: 'is_firebrugade_approved', label: 'Fire Approved', type: 'yesno' },
    ],
  },
];

function FieldInput({ field, value, onChange }) {
  if (field.type === 'yesno') {
    const active = value === 'Yes';
    return (
      <button
        type="button"
        onClick={() => onChange(active ? 'No' : 'Yes')}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 12px', border: `1.5px solid ${active ? '#4caf50' : '#ccc'}`,
          background: active ? '#e8f5e9' : '#fafafa',
          color: active ? '#388e3c' : '#999',
          cursor: 'pointer', fontWeight: 700, fontSize: 12, borderRadius: 3,
          width: '100%', justifyContent: 'center',
        }}
      >
        {active ? <FiCheck size={14} /> : <FiX size={14} />}
        {active ? 'Yes' : 'No'}
      </button>
    );
  }
  if (field.type === 'select') {
    return (
      <div style={{ position: 'relative' }}>
        <select
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value)}
          style={{
            width: '100%', padding: '9px 32px 9px 10px', fontSize: 13,
            border: '1.5px solid #ccc', background: '#fff', appearance: 'none',
            outline: 'none', cursor: 'pointer', fontFamily: 'inherit',
          }}
        >
          {field.options.map((opt) => {
            const v = typeof opt === 'string' ? opt : opt.value;
            const l = typeof opt === 'string' ? opt : opt.label;
            return <option key={v} value={v}>{l}</option>;
          })}
        </select>
        <FiChevronDown size={14} style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none', color: '#666' }} />
      </div>
    );
  }
  if (field.type === 'textarea') {
    return (
      <textarea
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        style={{
          width: '100%', padding: '9px 10px', fontSize: 13,
          border: '1.5px solid #ccc', resize: 'vertical', outline: 'none',
          fontFamily: 'inherit', lineHeight: 1.5,
        }}
      />
    );
  }
  return (
    <input
      type={field.type}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value)}
      {...(field.attrs || {})}
      style={{
        width: '100%', padding: '9px 10px', fontSize: 13,
        border: '1.5px solid #ccc', outline: 'none', fontFamily: 'inherit',
      }}
    />
  );
}

function EditDrawer({ user, onClose, onSave }) {
  const [form, setForm] = useState({});
  const [activeTab, setActiveTab] = useState(0);
  const [saving, setSaving] = useState(false);
  const [resetPwd, setResetPwd] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [walletAdj, setWalletAdj] = useState({ amount: '', reason: '' });
  const [walletData, setWalletData] = useState(null);
  const [msg, setMsg] = useState(null);
  const [resettingPwd, setResettingPwd] = useState(false);
  const [adjustingWallet, setAdjustingWallet] = useState(false);

  useEffect(() => {
    if (!user) return;
    const f = {};
    FIELD_GROUPS.forEach((g) => g.fields.forEach((fd) => {
      f[fd.key] = user[fd.key] != null ? String(user[fd.key]) : '';
    }));
    // status is 1/0 in DB but 'active'/'inactive' in to_dict
    f.status = user.status === 'active' ? '1' : '0';
    setForm(f);
    adminAPI.userWallet(user.id).then(({ data }) => {
      if (data.code === 1) setWalletData(data.data);
    }).catch(() => {});
  }, [user]);

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const payload = { ...form };
      // keep status as int
      if (payload.status !== undefined) payload.status = parseInt(payload.status, 10);
      const { data } = await adminAPI.userUpdate(user.id, payload);
      if (data.code === 1) {
        setMsg({ type: 'success', text: 'Saved successfully' });
        onSave(data.data);
      } else {
        setMsg({ type: 'error', text: data.message || 'Save failed' });
      }
    } catch {
      setMsg({ type: 'error', text: 'Network error' });
    } finally {
      setSaving(false);
    }
  };

  const handleResetPassword = async () => {
    if (!resetPwd.trim()) return;
    setResettingPwd(true);
    setMsg(null);
    try {
      const { data } = await adminAPI.userResetPwd(user.id, { new_password: resetPwd });
      setMsg({ type: data.code === 1 ? 'success' : 'error', text: data.message });
      if (data.code === 1) setResetPwd('');
    } catch {
      setMsg({ type: 'error', text: 'Network error' });
    } finally {
      setResettingPwd(false);
    }
  };

  const handleWalletAdjust = async () => {
    if (!walletAdj.amount) return;
    setAdjustingWallet(true);
    setMsg(null);
    try {
      const { data } = await adminAPI.userWalletAdj(user.id, walletAdj);
      setMsg({ type: data.code === 1 ? 'success' : 'error', text: data.message });
      if (data.code === 1) {
        setWalletAdj({ amount: '', reason: '' });
        const wd = await adminAPI.userWallet(user.id);
        if (wd.data.code === 1) setWalletData(wd.data.data);
      }
    } catch {
      setMsg({ type: 'error', text: 'Network error' });
    } finally {
      setAdjustingWallet(false);
    }
  };

  const tabs = ['Info', 'Driver', 'Services', 'Security', 'Wallet'];

  const renderInfo = () => (
    <>
      {FIELD_GROUPS.filter((_, i) => i < 2).map((group) => (
        <div key={group.title} style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#999', marginBottom: 12, paddingBottom: 6, borderBottom: '1px solid #eee' }}>
            {group.title}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 16px' }}>
            {group.fields.map((field) => (
              <div key={field.key} style={{ gridColumn: field.type === 'textarea' ? '1 / -1' : 'auto' }}>
                <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 }}>{field.label}</label>
                <FieldInput field={field} value={form[field.key]} onChange={(v) => set(field.key, v)} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  );

  const renderDriver = () => {
    const photoPath = user.driving_license_photo;
    const photoUrl = photoPath
      ? (photoPath.startsWith('http') ? photoPath : `/uploads/${photoPath}`)
      : null;
    return (
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#999', marginBottom: 12 }}>Driver Details</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 16px', marginBottom: 20 }}>
          {FIELD_GROUPS[2].fields.map((field) => (
            <div key={field.key} style={{ gridColumn: field.key === 'driving_license_issue_authority' ? '1 / -1' : 'auto' }}>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 }}>{field.label}</label>
              <FieldInput field={field} value={form[field.key]} onChange={(v) => set(field.key, v)} />
            </div>
          ))}
        </div>
        {photoUrl && (
          <div>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#999', marginBottom: 8 }}>License Photo</div>
            <img
              src={photoUrl}
              alt="Driving License"
              style={{ width: '100%', maxHeight: 240, objectFit: 'contain', border: '1.5px solid #eee', background: '#f7f7f7', display: 'block', cursor: 'pointer' }}
              onClick={() => window.open(photoUrl, '_blank')}
              onError={(e) => { e.target.style.display = 'none'; }}
            />
            <p style={{ fontSize: 11, color: '#999', marginTop: 4 }}>Click to open full size in new tab</p>
          </div>
        )}
      </div>
    );
  };

  const renderServices = () => (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#999', marginBottom: 12 }}>Service Permissions</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        {FIELD_GROUPS[3].fields.map((field) => (
          <div key={field.key}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 }}>{field.label}</label>
            <FieldInput field={field} value={form[field.key]} onChange={(v) => set(field.key, v)} />
          </div>
        ))}
      </div>
    </div>
  );

  const renderSecurity = () => (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#999', marginBottom: 12 }}>Reset Password</div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 }}>New Password</label>
          <div style={{ position: 'relative' }}>
            <input
              type={showPwd ? 'text' : 'password'}
              value={resetPwd}
              onChange={(e) => setResetPwd(e.target.value)}
              placeholder="Enter new password"
              style={{ width: '100%', padding: '9px 36px 9px 10px', fontSize: 13, border: '1.5px solid #ccc', outline: 'none', fontFamily: 'inherit' }}
            />
            <button type="button" onClick={() => setShowPwd(!showPwd)} style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#666' }}>
              {showPwd ? <FiEyeOff size={15} /> : <FiEye size={15} />}
            </button>
          </div>
        </div>
        <button
          className="btn btn-sm btn-primary"
          onClick={handleResetPassword}
          disabled={resettingPwd || !resetPwd.trim()}
          style={{ height: 38, flexShrink: 0 }}
        >
          <FiKey size={14} />
          {resettingPwd ? 'Saving…' : 'Set Password'}
        </button>
      </div>
      <p style={{ fontSize: 12, color: '#999', marginTop: 8 }}>Leave blank to keep the current password.</p>
    </div>
  );

  const renderWallet = () => (
    <div>
      {walletData && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
          {[
            { label: 'Balance',        val: `$${parseFloat(walletData.wallet?.wallet_balance || 0).toFixed(2)}` },
            { label: 'Total Earnings', val: `$${parseFloat(walletData.wallet?.total_earnings || 0).toFixed(2)}` },
          ].map(({ label, val }) => (
            <div key={label} style={{ background: '#f7f7f7', padding: 14, border: '1px solid #eee' }}>
              <div style={{ fontSize: 11, color: '#999', fontWeight: 600, marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 20, fontWeight: 800, color: '#040404' }}>{val}</div>
            </div>
          ))}
        </div>
      )}
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#999', marginBottom: 12 }}>Adjust Balance</div>
      <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr auto', gap: 8, alignItems: 'flex-end' }}>
        <div>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 }}>Amount (+/-)</label>
          <input
            type="number" step="0.01"
            value={walletAdj.amount}
            onChange={(e) => setWalletAdj((w) => ({ ...w, amount: e.target.value }))}
            placeholder="e.g. -5.00"
            style={{ width: '100%', padding: '9px 10px', fontSize: 13, border: '1.5px solid #ccc', outline: 'none', fontFamily: 'inherit' }}
          />
        </div>
        <div>
          <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#666', marginBottom: 4 }}>Reason</label>
          <input
            type="text"
            value={walletAdj.reason}
            onChange={(e) => setWalletAdj((w) => ({ ...w, reason: e.target.value }))}
            placeholder="Adjustment reason"
            style={{ width: '100%', padding: '9px 10px', fontSize: 13, border: '1.5px solid #ccc', outline: 'none', fontFamily: 'inherit' }}
          />
        </div>
        <button
          className="btn btn-sm btn-primary"
          onClick={handleWalletAdjust}
          disabled={adjustingWallet || !walletAdj.amount}
          style={{ height: 38, flexShrink: 0 }}
        >
          <FiDollarSign size={14} />
          {adjustingWallet ? '…' : 'Apply'}
        </button>
      </div>
      {walletData?.transactions?.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: '#999', marginBottom: 8 }}>Recent Transactions</div>
          <div style={{ maxHeight: 220, overflowY: 'auto', border: '1px solid #eee' }}>
            {walletData.transactions.slice(0, 20).map((tx, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid #f0f0f0', fontSize: 12 }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{tx.description || tx.transaction_type || 'Transaction'}</div>
                  <div style={{ color: '#999', fontSize: 11 }}>{tx.created_at?.slice(0, 10)}</div>
                </div>
                <div style={{ fontWeight: 700, color: parseFloat(tx.amount) >= 0 ? '#388e3c' : '#d32f2f' }}>
                  {parseFloat(tx.amount) >= 0 ? '+' : ''}{parseFloat(tx.amount || 0).toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  const tabContent = [renderInfo, renderDriver, renderServices, renderSecurity, renderWallet];

  if (!user) return null;

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1500, display: 'flex' }} onClick={onClose}>
      {/* backdrop */}
      <div style={{ flex: 1, background: 'rgba(0,0,0,0.4)' }} />
      {/* drawer */}
      <div
        style={{
          width: 560, maxWidth: '95vw', background: '#fff',
          display: 'flex', flexDirection: 'column', height: '100%',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.15)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div style={{ padding: '16px 20px', borderBottom: '2px solid #040404', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
          <Avatar name={user.name} avatar={user.avatar} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user.name || `${user.first_name || ''} ${user.last_name || ''}`.trim() || 'Unknown'}
            </div>
            <div style={{ fontSize: 12, color: '#666', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user.email || user.username} · #{user.id}
            </div>
          </div>
          <Badge val={user.user_type} />
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#666', padding: 4 }}>
            <FiXCircle size={20} />
          </button>
        </div>

        {/* tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid #eee', flexShrink: 0 }}>
          {tabs.map((tab, i) => (
            <button
              key={tab}
              onClick={() => { setActiveTab(i); setMsg(null); }}
              style={{
                padding: '10px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                border: 'none', background: 'none', color: activeTab === i ? '#040404' : '#999',
                borderBottom: activeTab === i ? '2px solid #EF9B11' : '2px solid transparent',
                marginBottom: -1, fontFamily: 'inherit',
              }}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {msg && (
            <div style={{
              padding: '10px 14px', marginBottom: 16, fontSize: 13, borderRadius: 3,
              background: msg.type === 'success' ? '#e8f5e9' : '#ffebee',
              color: msg.type === 'success' ? '#388e3c' : '#d32f2f',
              border: `1px solid ${msg.type === 'success' ? '#c8e6c9' : '#ffcdd2'}`,
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              {msg.type === 'success' ? <FiCheck size={14} /> : <FiAlertTriangle size={14} />}
              {msg.text}
            </div>
          )}
          {tabContent[activeTab]()}
        </div>

        {/* footer — save only for Info/Driver/Services tabs */}
        {activeTab < 3 && (
          <div style={{ padding: '14px 20px', borderTop: '1px solid #eee', display: 'flex', gap: 8, justifyContent: 'flex-end', flexShrink: 0 }}>
            <button className="btn btn-sm btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn btn-sm btn-primary" onClick={handleSave} disabled={saving}>
              <FiSave size={14} />
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Main UsersPage ───────────────────────────────────────────────────── */
export default function UsersPage() {
  const [users, setUsers]       = useState([]);
  const [page, setPage]         = useState(1);
  const [total, setTotal]       = useState(0);
  const [search, setSearch]     = useState('');
  const [filterType, setFilterType] = useState('');
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [editing, setEditing]   = useState(null);
  const [driverReview, setDriverReview] = useState(null); // NEW: driver application review
  const [confirm, setConfirm]   = useState(null); // { id, action, label }
  const [actionLoading, setActionLoading] = useState({});

  const perPage = 20;
  const totalPages = Math.ceil(total / perPage);

  const load = useCallback((p = page, q = search, type = filterType) => {
    setLoading(true);
    setError(null);
    const params = { page: p, per_page: perPage, search: q };
    if (type) params.user_type = type;
    adminAPI.users(params)
      .then(({ data }) => {
        if (data.code === 1) {
          setUsers(data.data?.data || []);
          setTotal(data.data?.total || 0);
        } else {
          setError(data.message || 'Failed to load users');
        }
      })
      .catch((err) => {
        if (err.response?.status !== 401) setError('Unable to connect to server');
      })
      .finally(() => setLoading(false));
  }, [page, search, filterType]);

  useEffect(() => { load(1, '', ''); }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    load(1, search, filterType);
  };

  const handleFilterType = (type) => {
    setFilterType(type);
    setPage(1);
    load(1, search, type);
  };

  const setActionBusy = (id, busy) => setActionLoading((s) => ({ ...s, [id]: busy }));

  const doAction = async (id, action) => {
    setActionBusy(id, true);
    try {
      if (action === 'approve') await adminAPI.approveDriver(id);
      else if (action === 'reject') await adminAPI.rejectDriver(id);
      else if (action === 'toggle') await adminAPI.toggleStatus(id);
      else if (action === 'delete') await adminAPI.userDelete(id);
      load(page, search, filterType);
    } catch {
      /* silent */
    } finally {
      setActionBusy(id, false);
      setConfirm(null);
    }
  };

  const tryAction = (id, action, label) => {
    if (['delete', 'reject'].includes(action)) {
      setConfirm({ id, action, label });
    } else {
      doAction(id, action);
    }
  };

  const onSaveUser = (updated) => {
    setUsers((prev) => prev.map((u) => (u.id === updated.id ? { ...u, ...updated } : u)));
  };

  const userTypeFilters = [
    { val: '',               label: 'All Users' },
    { val: 'Customer',       label: 'Customers' },
    { val: 'Pending Driver', label: 'Pending Drivers' },
    { val: 'Driver',         label: 'Drivers' },
    { val: 'Admin',          label: 'Admins' },
  ];

  return (
    <div className="page-users" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* toolbar */}
      <div className="page-toolbar" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', padding: '12px 0', marginBottom: 0 }}>
        <form onSubmit={handleSearch} className="search-form" style={{ display: 'flex', gap: 6, flex: 1, minWidth: 220 }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <FiSearch style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: '#999', pointerEvents: 'none' }} size={15} />
            <input
              placeholder="Search name, email, phone…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: '100%', paddingLeft: 34, paddingRight: 10, height: 36, border: '1.5px solid #ccc', fontSize: 13, outline: 'none', fontFamily: 'inherit' }}
            />
          </div>
          <button type="submit" className="btn btn-sm btn-primary">Search</button>
          <button type="button" className="btn btn-sm btn-secondary" onClick={() => { setSearch(''); setPage(1); load(1, '', filterType); }}>
            <FiRefreshCw size={13} />
          </button>
        </form>
        <div style={{ display: 'flex', gap: 4 }}>
          {userTypeFilters.map(({ val, label }) => (
            <button
              key={val}
              className="btn btn-xs"
              onClick={() => handleFilterType(val)}
              style={{
                borderColor: filterType === val ? '#EF9B11' : '#ccc',
                background: filterType === val ? '#EF9B11' : '#fff',
                color: filterType === val ? '#040404' : '#666',
                fontWeight: filterType === val ? 700 : 500,
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <span style={{ color: '#999', fontSize: 13, whiteSpace: 'nowrap' }}>{total.toLocaleString()} users</span>
      </div>

      {/* content */}
      {loading ? (
        <div className="page-loader">Loading…</div>
      ) : error ? (
        <div className="page-loader">
          <span>{error}</span>
          <button className="btn btn-sm" onClick={() => load()} style={{ marginLeft: 8 }}>Retry</button>
        </div>
      ) : (
        <div className="table-wrap" style={{ flex: 1, overflowY: 'auto' }}>
          <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead style={{ position: 'sticky', top: 0, background: '#fff', zIndex: 1 }}>
              <tr style={{ borderBottom: '2px solid #040404' }}>
                <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: .5, color: '#666', whiteSpace: 'nowrap' }}>User</th>
                <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: .5, color: '#666', whiteSpace: 'nowrap' }}>Contact</th>
                <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: .5, color: '#666', whiteSpace: 'nowrap' }}>Role</th>
                <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: .5, color: '#666', whiteSpace: 'nowrap' }}>Status</th>
                <th style={{ padding: '10px 12px', textAlign: 'left', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: .5, color: '#666', whiteSpace: 'nowrap' }}>Services</th>
                <th style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: .5, color: '#666', whiteSpace: 'nowrap' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const busy = actionLoading[u.id];
                return (
                  <tr key={u.id} style={{ borderBottom: '1px solid #f0f0f0', transition: 'background .1s' }}
                    onMouseEnter={(e) => e.currentTarget.style.background = '#fafafa'}
                    onMouseLeave={(e) => e.currentTarget.style.background = ''}
                  >
                    {/* user */}
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <Avatar name={u.name || u.first_name} avatar={u.avatar} />
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160 }}>
                            {u.name || `${u.first_name || ''} ${u.last_name || ''}`.trim() || <span style={{ color: '#bbb' }}>No name</span>}
                          </div>
                          <div style={{ fontSize: 11, color: '#999' }}>#{u.id}</div>
                        </div>
                      </div>
                    </td>
                    {/* contact */}
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ fontSize: 12, color: '#333', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 180 }}>
                        {u.email || <span style={{ color: '#bbb' }}>No email</span>}
                      </div>
                      <div style={{ fontSize: 11, color: '#999' }}>{u.phone_number || '—'}</div>
                    </td>
                    {/* role */}
                    <td style={{ padding: '10px 12px' }}>
                      <Badge val={u.user_type} />
                    </td>
                    {/* status */}
                    <td style={{ padding: '10px 12px' }}>
                      <Badge val={u.status} />
                    </td>
                    {/* services */}
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {u.is_car === 'Yes' && <Badge val={u.is_car_approved === 'Yes' ? 'Yes' : 'No'} label={u.is_car_approved === 'Yes' ? '🚗 Approved' : '🚗 Pending'} />}
                        {u.is_delivery === 'Yes' && <Badge val={u.is_delivery_approved === 'Yes' ? 'Yes' : 'No'} label={u.is_delivery_approved === 'Yes' ? '📦 Approved' : '📦 Pending'} />}
                        {u.is_car !== 'Yes' && u.is_delivery !== 'Yes' && u.user_type !== 'Driver' && u.user_type !== 'Pending Driver' && <span style={{ color: '#bbb', fontSize: 12 }}>—</span>}
                      </div>
                    </td>
                    {/* actions */}
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                        {/* edit */}
                        <button
                          className="btn btn-xs"
                          title="Edit user"
                          onClick={() => setEditing(u)}
                          style={{ borderColor: '#040404' }}
                        >
                          <FiEdit2 size={12} />
                        </button>

                        {/* review driver application — prominent button for Pending Drivers */}
                        {u.user_type === 'Pending Driver' && (
                          <button
                            className="btn btn-xs"
                            title="Review Driver Application"
                            disabled={busy}
                            onClick={() => setDriverReview(u)}
                            style={{
                              borderColor: '#EF9B11', background: '#EF9B11', color: '#000',
                              fontWeight: 700, fontSize: 11, padding: '4px 8px', display: 'flex', alignItems: 'center', gap: 4,
                            }}
                          >
                            <FiFileText size={12} /> Review
                          </button>
                        )}

                        {/* for already-approved drivers: quick revoke button */}
                        {u.user_type === 'Driver' && (
                          <button
                            className="btn btn-xs"
                            title="View Driver Application"
                            onClick={() => setDriverReview(u)}
                            style={{ borderColor: '#4caf50', color: '#388e3c' }}
                          >
                            <FiFileText size={12} />
                          </button>
                        )}

                        {/* toggle active */}
                        <button
                          className={`btn btn-xs ${u.status === 'active' ? 'btn-warning' : 'btn-success'}`}
                          title={u.status === 'active' ? 'Deactivate' : 'Activate'}
                          disabled={busy}
                          onClick={() => tryAction(u.id, 'toggle', `${u.status === 'active' ? 'Deactivate' : 'Activate'} ${u.name || 'this user'}?`)}
                        >
                          {u.status === 'active' ? <FiToggleRight size={14} /> : <FiToggleLeft size={14} />}
                        </button>

                        {/* delete */}
                        <button
                          className="btn btn-xs btn-danger"
                          title="Delete user"
                          disabled={busy}
                          onClick={() => tryAction(u.id, 'delete', `Permanently delete ${u.name || 'this user'}? This cannot be undone.`)}
                        >
                          <FiTrash2 size={12} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!users.length && (
                <tr>
                  <td colSpan="6" style={{ padding: 40, textAlign: 'center', color: '#bbb' }}>
                    <FiUser size={32} style={{ display: 'block', margin: '0 auto 8px' }} />
                    No users found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* pagination */}
      {totalPages > 1 && (
        <div className="pagination" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '12px 0', fontSize: 13 }}>
          <button
            className="btn btn-sm btn-secondary"
            disabled={page <= 1}
            onClick={() => { const p = page - 1; setPage(p); load(p, search, filterType); }}
          >
            <FiChevronLeft size={15} />
          </button>
          <span style={{ color: '#666' }}>Page <strong>{page}</strong> of {totalPages}</span>
          <button
            className="btn btn-sm btn-secondary"
            disabled={page >= totalPages}
            onClick={() => { const p = page + 1; setPage(p); load(p, search, filterType); }}
          >
            <FiChevronRight size={15} />
          </button>
        </div>
      )}

      {/* edit drawer */}
      {editing && (
        <EditDrawer
          user={editing}
          onClose={() => setEditing(null)}
          onSave={(updated) => { onSaveUser(updated); setEditing(null); }}
        />
      )}

      {/* driver application review drawer */}
      {driverReview && (
        <DriverApplicationDrawer
          user={driverReview}
          onClose={() => setDriverReview(null)}
          onApproved={(updated) => { onSaveUser(updated); setDriverReview(null); load(page, search, filterType); }}
          onRejected={(updated) => { onSaveUser(updated); setDriverReview(null); load(page, search, filterType); }}
        />
      )}

      {/* confirm dialog */}
      {confirm && (
        <Confirm
          message={confirm.label}
          onConfirm={() => doAction(confirm.id, confirm.action)}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  );
}
