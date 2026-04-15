import React, { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import Sidebar from '../components/Sidebar';
import { FiMenu, FiLogOut, FiUser } from 'react-icons/fi';

const TITLES = {
  '/': 'Dashboard',
  '/users': 'Users & Drivers',
  '/trips': 'Trips',
  '/negotiations': 'Negotiations',
  '/bookings': 'Scheduled Bookings',
  '/payments': 'Payments',
};

export default function Dashboard() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const title = TITLES[location.pathname] || 'Dashboard';
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="dashboard">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="dashboard-main">
        <header className="dashboard-header">
          <button className="menu-toggle" onClick={() => setSidebarOpen(true)}>
            <FiMenu />
          </button>
          <h1 className="header-title">{title}</h1>
          <div className="header-user">
            <FiUser className="header-avatar-icon" />
            <span className="header-username">{user?.name || 'Admin'}</span>
            <button className="btn-icon" onClick={logout} title="Sign out">
              <FiLogOut />
            </button>
          </div>
        </header>
        <div className="dashboard-content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
