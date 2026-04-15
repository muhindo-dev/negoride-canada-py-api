import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiSearch, FiChevronLeft, FiChevronRight, FiX, FiDollarSign } from 'react-icons/fi';

/* ── Wallet Adjust Modal ── */
function AdjustModal({ wallet, onClose, onSave }) {
  const [amount, setAmount] = useState('');
  const [type, setType] = useState('credit');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const save = async () => {
    if (!amount || Number(amount) <= 0) { setErr('Amount must be positive'); return; }
    setSaving(true); setErr('');
    try {
      await onSave(wallet.user_id, { amount: Number(amount), type, reason });
      onClose();
    } catch (e) {
      setErr(e?.response?.data?.message || 'Failed to adjust');
    } finally { setSaving(false); }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={e => e.stopPropagation()} style={{ maxWidth: 380 }}>
        <h3><FiDollarSign style={{ marginRight: 6 }} />Adjust Wallet</h3>
        <p style={{ marginBottom: 16 }}>User: <strong>{wallet.user_name || `#${wallet.user_id}`}</strong> &nbsp; Balance: <strong>${Number(wallet.wallet_balance || 0).toFixed(2)}</strong></p>
        <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 12 }}>
          <div className="form-group">
            <label>Type</label>
            <select className="d-select" value={type} onChange={e => setType(e.target.value)}>
              <option value="credit">Credit (+)</option>
              <option value="debit">Debit (−)</option>
            </select>
          </div>
          <div className="form-group">
            <label>Amount ($)</label>
            <input className="d-input" type="number" min="0.01" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" />
          </div>
        </div>
        <div className="form-group" style={{ marginBottom: 4 }}>
          <label>Reason</label>
          <input className="d-input" value={reason} onChange={e => setReason(e.target.value)} placeholder="Reason for adjustment…" />
        </div>
        {err && <p style={{ color: 'var(--error)', fontSize: 12, marginTop: 6 }}>{err}</p>}
        <div className="modal-actions">
          <button className="btn btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn btn-sm btn-accent" disabled={saving} onClick={save}>
            {saving ? 'Saving…' : `${type === 'credit' ? 'Add' : 'Deduct'} $${amount || '0'}`}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function WalletsPage() {
  const [tab, setTab] = useState('wallets');
  const [wallets, setWallets] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [txType, setTxType] = useState('');
  const [txCat, setTxCat] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [adjusting, setAdjusting] = useState(null);
  const perPage = 20;
  const totalPages = Math.ceil(total / perPage);

  const load = (p = page, q = search, tt = txType, tc = txCat) => {
    setLoading(true); setError(null);
    const req = tab === 'wallets'
      ? adminAPI.wallets({ page: p, per_page: perPage })
      : adminAPI.transactions({ page: p, per_page: perPage, ...(tt ? { type: tt } : {}), ...(tc ? { category: tc } : {}) });
    req.then(({ data }) => {
      if (data.code === 1) {
        if (tab === 'wallets') setWallets(data.data?.data || []);
        else setTransactions(data.data?.data || []);
        setTotal(data.data?.total || 0);
      } else setError(data.message || 'Failed to load');
    })
    .catch(err => { if (err.response?.status !== 401) setError('Unable to connect'); })
    .finally(() => setLoading(false));
  };

  useEffect(() => { setPage(1); load(1, search, txType, txCat); }, [tab, txType, txCat]);

  const handleWalletAdjust = async (userId, data) => {
    await adminAPI.userWalletAdj(userId, data);
    load();
  };

  const searchWallets = () => { setPage(1); load(1, search, txType, txCat); };

  return (
    <div className="page-wallets">
      {adjusting && <AdjustModal wallet={adjusting} onClose={() => setAdjusting(null)} onSave={handleWalletAdjust} />}

      <div className="page-toolbar">
        <div className="tab-bar">
          <button className={`tab-btn ${tab === 'wallets' ? 'tab-btn--active' : ''}`} onClick={() => setTab('wallets')}>Wallets</button>
          <button className={`tab-btn ${tab === 'transactions' ? 'tab-btn--active' : ''}`} onClick={() => setTab('transactions')}>Transactions</button>
        </div>
        {tab === 'transactions' && (
          <div style={{ display: 'flex', gap: 6 }}>
            <select className="d-select" style={{ padding: '5px 10px', fontSize: 12 }} value={txType} onChange={e => setTxType(e.target.value)}>
              <option value="">All Types</option>
              <option value="credit">Credit</option>
              <option value="debit">Debit</option>
            </select>
            <select className="d-select" style={{ padding: '5px 10px', fontSize: 12 }} value={txCat} onChange={e => setTxCat(e.target.value)}>
              <option value="">All Categories</option>
              <option value="ride_payment">Ride Payment</option>
              <option value="ride_earnings">Ride Earnings</option>
              <option value="bonus">Bonus</option>
              <option value="penalty">Penalty</option>
              <option value="payout">Payout</option>
              <option value="topup">Top-up</option>
            </select>
          </div>
        )}
        <span className="toolbar-info">{total} {tab}</span>
      </div>

      {tab === 'wallets' && (
        <div className="page-toolbar" style={{ paddingTop: 0 }}>
          <form onSubmit={e => { e.preventDefault(); searchWallets(); }} className="search-form">
            <FiSearch className="search-icon" />
            <input placeholder="Search by user name (type to filter server-side)…" value={search} onChange={e => setSearch(e.target.value)} />
            <button type="submit" className="btn btn-sm">Search</button>
          </form>
        </div>
      )}

      {loading ? <div className="page-loader">Loading…</div> : error ? (
        <div className="page-loader"><span>{error}</span><button className="btn btn-sm" onClick={() => load()} style={{ marginLeft: 8 }}>Retry</button></div>
      ) : tab === 'wallets' ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>User</th><th>Type</th><th>Balance</th><th>Total Earnings</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {wallets.map(w => (
                <tr key={w.id}>
                  <td style={{ fontWeight: 700 }}>#{w.id}</td>
                  <td>{w.user_name || `#${w.user_id}`}</td>
                  <td><span className="badge">{w.user_type || '—'}</span></td>
                  <td style={{ fontWeight: 700 }}>${Number(w.wallet_balance || 0).toFixed(2)}</td>
                  <td>${Number(w.total_earnings || 0).toFixed(2)}</td>
                  <td className="actions">
                    <button className="btn btn-xs btn-accent" title="Adjust Wallet" onClick={() => setAdjusting(w)}><FiDollarSign /> Adjust</button>
                  </td>
                </tr>
              ))}
              {!wallets.length && <tr><td colSpan="6" className="empty-state">No wallets found</td></tr>}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>ID</th><th>User</th><th>Type</th><th>Category</th><th>Amount</th><th>Before</th><th>After</th><th>Status</th><th>Date</th></tr>
            </thead>
            <tbody>
              {transactions.map(t => (
                <tr key={t.id}>
                  <td style={{ fontWeight: 700 }}>#{t.id}</td>
                  <td>#{t.user_id}</td>
                  <td><span className={`badge badge-${t.type === 'credit' ? 'success' : 'error'}`}>{t.type}</span></td>
                  <td>{t.category || '—'}</td>
                  <td style={{ fontWeight: 700, color: t.type === 'credit' ? 'var(--success)' : 'var(--error)' }}>
                    {t.type === 'credit' ? '+' : '−'}${Number(t.amount || 0).toFixed(2)}
                  </td>
                  <td>${Number(t.balance_before || 0).toFixed(2)}</td>
                  <td>${Number(t.balance_after || 0).toFixed(2)}</td>
                  <td><span className={`badge badge-${t.status}`}>{t.status}</span></td>
                  <td>{t.created_at?.slice(0, 10)}</td>
                </tr>
              ))}
              {!transactions.length && <tr><td colSpan="9" className="empty-state">No transactions found</td></tr>}
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
