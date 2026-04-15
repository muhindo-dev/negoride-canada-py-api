import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  FiHome, FiUsers, FiNavigation, FiMessageSquare,
  FiCalendar, FiCreditCard, FiX, FiDollarSign,
  FiSend, FiMessageCircle, FiBriefcase, FiMapPin
} from 'react-icons/fi';

const NAV = [
  { to: '/',              icon: FiHome,          label: 'Dashboard',     end: true },
  { to: '/users',         icon: FiUsers,         label: 'Users & Drivers' },
  { to: '/trips',         icon: FiNavigation,    label: 'Trips' },
  { to: '/negotiations',  icon: FiMessageSquare, label: 'Negotiations' },
  { to: '/bookings',      icon: FiCalendar,      label: 'Bookings' },
  { to: '/payments',      icon: FiCreditCard,    label: 'Payments' },
  { to: '/wallets',       icon: FiDollarSign,    label: 'Wallets' },
  { to: '/payouts',       icon: FiSend,          label: 'Payouts' },
  { to: '/chats',         icon: FiMessageCircle, label: 'Chats' },
  { to: '/companies',     icon: FiBriefcase,     label: 'Companies' },
  { to: '/route-stages',  icon: FiMapPin,        label: 'Route Stages' },
];

export default function Sidebar({ open, onClose }) {
  return (
    <>
      <div className="sidebar-overlay" onClick={onClose} />
      <nav className={`sidebar ${open ? 'sidebar--open' : ''}`}>
        <div className="sidebar-brand">
          <div className="brand-mark">N</div>
          <div className="brand-info">
            <span className="brand-text">NegoRide</span>
            <span className="brand-tag">Admin Panel</span>
          </div>
          <button className="sidebar-close" onClick={onClose}><FiX /></button>
        </div>
        <ul className="sidebar-nav">
          {NAV.map(({ to, icon: Icon, label, end }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={end}
                className={({ isActive }) => `nav-link ${isActive ? 'nav-link--active' : ''}`}
                onClick={onClose}
              >
                <Icon className="nav-icon" />
                <span>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="sidebar-footer">NegoRide Canada © 2025</div>
      </nav>
    </>
  );
}
