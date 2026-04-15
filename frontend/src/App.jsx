import React, { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';

const DashboardHome    = lazy(() => import('./components/DashboardHome'));
const UsersPage        = lazy(() => import('./components/UsersPage'));
const TripsPage        = lazy(() => import('./components/TripsPage'));
const NegotiationsPage = lazy(() => import('./components/NegotiationsPage'));
const BookingsPage     = lazy(() => import('./components/BookingsPage'));
const PaymentsPage     = lazy(() => import('./components/PaymentsPage'));
const WalletsPage      = lazy(() => import('./components/WalletsPage'));
const PayoutsPage      = lazy(() => import('./components/PayoutsPage'));
const ChatsPage        = lazy(() => import('./components/ChatsPage'));
const CompaniesPage    = lazy(() => import('./components/CompaniesPage'));
const RouteStagesPage  = lazy(() => import('./components/RouteStagesPage'));

const Loader = () => <div className="page-loader">Loading…</div>;

function ProtectedRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return <Loader />;
  return isAuthenticated ? children : <Navigate to="/login" />;
}

function PublicRoute({ children }) {
  const { isAuthenticated, loading } = useAuth();
  if (loading) return <Loader />;
  return !isAuthenticated ? children : <Navigate to="/" />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
      <Route path="/" element={<ProtectedRoute><Dashboard /></ProtectedRoute>}>
        <Route index element={<Suspense fallback={<Loader />}><DashboardHome /></Suspense>} />
        <Route path="users" element={<Suspense fallback={<Loader />}><UsersPage /></Suspense>} />
        <Route path="trips" element={<Suspense fallback={<Loader />}><TripsPage /></Suspense>} />
        <Route path="negotiations" element={<Suspense fallback={<Loader />}><NegotiationsPage /></Suspense>} />
        <Route path="bookings" element={<Suspense fallback={<Loader />}><BookingsPage /></Suspense>} />
        <Route path="payments" element={<Suspense fallback={<Loader />}><PaymentsPage /></Suspense>} />
        <Route path="wallets" element={<Suspense fallback={<Loader />}><WalletsPage /></Suspense>} />
        <Route path="payouts" element={<Suspense fallback={<Loader />}><PayoutsPage /></Suspense>} />
        <Route path="chats" element={<Suspense fallback={<Loader />}><ChatsPage /></Suspense>} />
        <Route path="companies" element={<Suspense fallback={<Loader />}><CompaniesPage /></Suspense>} />
        <Route path="route-stages" element={<Suspense fallback={<Loader />}><RouteStagesPage /></Suspense>} />
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
