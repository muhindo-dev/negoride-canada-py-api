import React, { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { RealtimeProvider } from './v4/lib/realtime';
import { SosProvider } from './v4/lib/sos';
import { useRoles } from './v4/lib/roles';
import Shell from './v4/Shell';
import Login from './v4/pages/Login';
import { Forbidden, Loading } from './v4/components/ui';

// v4 operations console — one lazy chunk per module (spec §19.1)
const CommandCenter = lazy(() => import('./v4/pages/CommandCenter'));
const LiveMap = lazy(() => import('./v4/pages/LiveMap'));
const SafetyCenter = lazy(() => import('./v4/pages/safety/SafetyCenter'));
const IncidentDetail = lazy(() => import('./v4/pages/safety/IncidentDetail'));
const RidesList = lazy(() => import('./v4/pages/rides/RidesList'));
const RideDetail = lazy(() => import('./v4/pages/rides/RideDetail'));
const UsersList = lazy(() => import('./v4/pages/users/UsersList'));
const UserDetail = lazy(() => import('./v4/pages/users/UserDetail'));
const OnboardingQueue = lazy(() => import('./v4/pages/onboarding/OnboardingQueue'));
const ApplicationDetail = lazy(() => import('./v4/pages/onboarding/ApplicationDetail'));
const Finance = lazy(() => import('./v4/pages/finance/Finance'));
const SupportQueue = lazy(() => import('./v4/pages/support/SupportQueue'));
const TicketDetail = lazy(() => import('./v4/pages/support/TicketDetail'));
const Ratings = lazy(() => import('./v4/pages/Ratings'));
const Notifications = lazy(() => import('./v4/pages/Notifications'));
const Legal = lazy(() => import('./v4/pages/legal/Legal'));
const LegalEditor = lazy(() => import('./v4/pages/legal/LegalEditor'));
const Settings = lazy(() => import('./v4/pages/Settings'));
const Reports = lazy(() => import('./v4/pages/Reports'));
const AdminUsers = lazy(() => import('./v4/pages/AdminUsers'));
const AuditLog = lazy(() => import('./v4/pages/AuditLog'));

// Legacy (v3) pages, unchanged, under /legacy/*
const LegacyOutlet = lazy(() => import('./legacy/LegacyOutlet'));
const DashboardHome = lazy(() => import('./components/DashboardHome'));
const UsersPage = lazy(() => import('./components/UsersPage'));
const TripsPage = lazy(() => import('./components/TripsPage'));
const NegotiationsPage = lazy(() => import('./components/NegotiationsPage'));
const BookingsPage = lazy(() => import('./components/BookingsPage'));
const PaymentsPage = lazy(() => import('./components/PaymentsPage'));
const WalletsPage = lazy(() => import('./components/WalletsPage'));
const PayoutsPage = lazy(() => import('./components/PayoutsPage'));
const ChatsPage = lazy(() => import('./components/ChatsPage'));
const CompaniesPage = lazy(() => import('./components/CompaniesPage'));
const RouteStagesPage = lazy(() => import('./components/RouteStagesPage'));

function ProtectedApp() {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return <Loading h={300} />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return (
    <RealtimeProvider token={localStorage.getItem('admin_token')}>
      <SosProvider>
        <Shell />
      </SosProvider>
    </RealtimeProvider>
  );
}

function PublicRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return <Loading h={300} />;
  return !isAuthenticated ? children : <Navigate to="/" replace />;
}

function Gate({ access, what, children }) {
  const { can } = useRoles();
  return can(access) ? children : <Forbidden what={what} />;
}

const g = (access, what, el) => <Gate access={access} what={what}>{el}</Gate>;
const S = ({ children }) => <Suspense fallback={<Loading />}>{children}</Suspense>;

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
      <Route path="/" element={<ProtectedApp />}>
        <Route index element={g('commandCenter', 'the Command Center', <CommandCenter />)} />
        <Route path="live" element={g('liveMap', 'the Live Operations Map', <LiveMap />)} />
        <Route path="safety" element={g('safety', 'the Safety Center', <SafetyCenter />)} />
        <Route path="safety/incidents/:id" element={g('safety', 'the Safety Center', <IncidentDetail />)} />
        <Route path="rides" element={g('rides', 'rides', <RidesList />)} />
        <Route path="rides/:type/:id" element={g('rides', 'rides', <RideDetail />)} />
        <Route path="users" element={g('users', 'user management', <UsersList />)} />
        <Route path="users/:id" element={g('users', 'user management', <UserDetail />)} />
        <Route path="onboarding" element={g('onboarding', 'driver onboarding', <OnboardingQueue />)} />
        <Route path="onboarding/:id" element={g('onboarding', 'driver onboarding', <ApplicationDetail />)} />
        <Route path="finance" element={g('finance', 'payments & finance', <Finance />)} />
        <Route path="support" element={g('support', 'support', <SupportQueue />)} />
        <Route path="support/:id" element={g('support', 'support', <TicketDetail />)} />
        <Route path="ratings" element={g('ratings', 'ratings', <Ratings />)} />
        <Route path="notifications" element={g('notifications', 'notifications', <Notifications />)} />
        <Route path="legal" element={g('legal', 'legal', <Legal />)} />
        <Route path="legal/:id" element={g('legal', 'legal', <LegalEditor />)} />
        <Route path="settings" element={g('settings', 'settings', <Settings />)} />
        <Route path="reports" element={g('reports', 'reports', <Reports />)} />
        <Route path="admin-users" element={g('adminUsers', 'admin user management (super admin only)', <AdminUsers />)} />
        <Route path="audit" element={g('audit', 'the audit log', <AuditLog />)} />
        <Route path="legacy" element={<S><LegacyOutlet /></S>}>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<S><DashboardHome /></S>} />
          <Route path="users" element={<S><UsersPage /></S>} />
          <Route path="trips" element={<S><TripsPage /></S>} />
          <Route path="negotiations" element={<S><NegotiationsPage /></S>} />
          <Route path="bookings" element={<S><BookingsPage /></S>} />
          <Route path="payments" element={<S><PaymentsPage /></S>} />
          <Route path="wallets" element={<S><WalletsPage /></S>} />
          <Route path="payouts" element={<S><PayoutsPage /></S>} />
          <Route path="chats" element={<S><ChatsPage /></S>} />
          <Route path="companies" element={<S><CompaniesPage /></S>} />
          <Route path="route-stages" element={<S><RouteStagesPage /></S>} />
        </Route>
        {/* old v3 URLs → legacy group */}
        {['trips', 'negotiations', 'bookings', 'payments', 'wallets', 'payouts', 'chats', 'companies', 'route-stages'].map((p) => (
          <Route key={p} path={p} element={<Navigate to={`/legacy/${p}`} replace />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
