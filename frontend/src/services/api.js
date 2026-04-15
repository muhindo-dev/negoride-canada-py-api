import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('admin_token');
      localStorage.removeItem('admin_user');
      window.location.href = '/login';
    }
    return Promise.reject(err);
  }
);

/* ── Auth ── */
export const authAPI = {
  login: (data) => api.post('/users/login', data),
  me: () => api.get('/me'),
};

/* ── Admin ── */
export const adminAPI = {
  dashboard:    () => api.get('/admin/dashboard'),
  analytics:    (params) => api.get('/admin/analytics', { params }),
  revenueChart: (params) => api.get('/admin/revenue-chart', { params }),
  userGrowth:   (params) => api.get('/admin/user-growth', { params }),
  systemHealth: () => api.get('/admin/system/health'),
  systemCounts: () => api.get('/admin/system/counts'),

  users:        (params) => api.get('/admin/users', { params }),
  userShow:     (id) => api.get(`/admin/users/${id}`),
  userUpdate:   (id, data) => api.post(`/admin/users/${id}/update`, data),
  userResetPwd: (id, data) => api.post(`/admin/users/${id}/reset-password`, data),
  approveDriver:(id, data) => api.post(`/admin/users/${id}/approve-driver`, data || {}),
  rejectDriver: (id) => api.post(`/admin/users/${id}/reject-driver`),
  toggleStatus: (id) => api.post(`/admin/users/${id}/toggle-status`),
  userDelete:   (id) => api.post(`/admin/users/${id}/delete`),
  userWallet:   (id) => api.get(`/admin/users/${id}/wallet`),
  userWalletAdj:(id, data) => api.post(`/admin/users/${id}/wallet/adjust`, data),

  negotiations: (params) => api.get('/admin/negotiations', { params }),
  negotiationShow:  (id) => api.get(`/admin/negotiations/${id}`),
  negotiationStatus:(id, data) => api.post(`/admin/negotiations/${id}/update-status`, data),
  negotiationCancel:(id) => api.post(`/admin/negotiations/${id}/cancel`),

  trips:        (params) => api.get('/admin/trips', { params }),
  tripShow:     (id) => api.get(`/admin/trips/${id}`),
  tripStatus:   (id, data) => api.post(`/admin/trips/${id}/update-status`, data),
  tripCancel:   (id) => api.post(`/admin/trips/${id}/cancel`),

  bookings:     (params) => api.get('/admin/bookings', { params }),
  bookingShow:  (id) => api.get(`/admin/bookings/${id}`),
  bookingStatus:(id, data) => api.post(`/admin/bookings/${id}/update-status`, data),
  bookingAssign:(id, data) => api.post(`/admin/bookings/${id}/assign-driver`, data),
  bookingCancel:(id, data) => api.post(`/admin/bookings/${id}/cancel`, data),
  bookingMarkPaid:(id) => api.post(`/admin/bookings/${id}/mark-paid`),
  tripBookings: (params) => api.get('/admin/trip-bookings', { params }),

  payments:     (params) => api.get('/admin/payments', { params }),
  paymentShow:  (id) => api.get(`/admin/payments/${id}`),

  wallets:      (params) => api.get('/admin/wallets', { params }),
  transactions: (params) => api.get('/admin/transactions', { params }),

  payoutRequests: (params) => api.get('/admin/payout-requests', { params }),
  payoutApprove:  (id, data) => api.post(`/admin/payout-requests/${id}/approve`, data),
  payoutComplete: (id) => api.post(`/admin/payout-requests/${id}/complete`),
  payoutReject:   (id, data) => api.post(`/admin/payout-requests/${id}/reject`, data),

  chats:        (params) => api.get('/admin/chats', { params }),
  chatMessages: (id) => api.get(`/admin/chats/${id}/messages`),

  companies:    () => api.get('/admin/companies'),
  companyCreate:(data) => api.post('/admin/companies', data),
  companyUpdate:(id, data) => api.post(`/admin/companies/${id}`, data),
  companyDelete:(id) => api.post(`/admin/companies/${id}/delete`),

  routeStages:  () => api.get('/admin/route-stages'),
  routeStageCreate:(data) => api.post('/admin/route-stages', data),
  routeStageUpdate:(id, data) => api.post(`/admin/route-stages/${id}`, data),
  routeStageDelete:(id) => api.post(`/admin/route-stages/${id}/delete`),
};

export default api;
