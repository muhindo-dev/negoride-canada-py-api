import React, { useEffect, useState } from 'react';
import { adminAPI } from '../services/api';
import { FiUsers, FiNavigation, FiDollarSign, FiClock } from 'react-icons/fi';

export default function DashboardHome() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = () => {
    setLoading(true);
    setError(null);
    adminAPI.dashboard()
      .then(({ data }) => {
        if (data.code === 1) setStats(data.data);
        else setError(data.message || 'Failed to load dashboard');
      })
      .catch((err) => {
        if (err.response?.status !== 401) setError('Unable to connect to server');
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="page-loader">Loading dashboard…</div>;
  if (error) return <div className="page-loader"><span>{error}</span> <button className="btn btn-sm" onClick={load} style={{marginLeft:8}}>Retry</button></div>;

  const cards = [
    { label: 'Total Users',       value: stats?.total_users ?? '—',       icon: FiUsers,      iconClass: 'stat-icon--accent' },
    { label: 'Active Trips',      value: stats?.active_trips ?? '—',      icon: FiNavigation,  iconClass: 'stat-icon--success' },
    { label: 'Total Revenue',     value: stats?.total_revenue != null ? `$${Number(stats.total_revenue).toFixed(2)}` : '—', icon: FiDollarSign, iconClass: 'stat-icon--warning' },
    { label: 'Pending Bookings',  value: stats?.pending_bookings ?? '—',  icon: FiClock,       iconClass: 'stat-icon--error' },
  ];

  return (
    <div className="dashboard-home">
      <div className="stat-cards">
        {cards.map((c) => (
          <div key={c.label} className="stat-card">
            <div className={`stat-icon ${c.iconClass}`}><c.icon /></div>
            <div className="stat-info">
              <span className="stat-value">{c.value}</span>
              <span className="stat-label">{c.label}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="dashboard-sections">
        <div className="section-card">
          <h3>Recent Activity</h3>
          {stats?.recent_trips?.length ? (
            <table className="data-table">
              <thead><tr><th>ID</th><th>From</th><th>To</th><th>Status</th><th>Date</th></tr></thead>
              <tbody>
                {stats.recent_trips.map((t) => (
                  <tr key={t.id}>
                    <td>#{t.id}</td>
                    <td>{t.start_name || '—'}</td>
                    <td>{t.end_name || '—'}</td>
                    <td><span className={`badge badge-${t.status}`}>{t.status}</span></td>
                    <td>{t.created_at?.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="empty-state">No recent trips</p>
          )}
        </div>

        <div className="section-card">
          <h3>Quick Stats</h3>
          <div className="quick-stats">
            <div className="qs-row"><span>Approved Drivers</span><span>{stats?.approved_drivers ?? '—'}</span></div>
            <div className="qs-row"><span>Pending Drivers</span><span>{stats?.pending_drivers ?? '—'}</span></div>
            <div className="qs-row"><span>Online Drivers</span><span>{stats?.online_drivers ?? '—'}</span></div>
            <div className="qs-row"><span>Completed Trips</span><span>{stats?.completed_trips ?? '—'}</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}
