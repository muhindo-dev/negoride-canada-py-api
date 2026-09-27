// Role gates mirror the backend decorators (spec §19.1.14). super_admin passes
// every check. Keep in sync with backend/routes/admin_*.py.
import { useAuth } from '../../contexts/AuthContext';

export const ROLES = ['super_admin', 'ops', 'safety_reviewer', 'finance', 'support'];
export const ROLE_LABELS = {
  super_admin: 'Super admin', ops: 'Operations', safety_reviewer: 'Safety reviewer',
  finance: 'Finance', support: 'Support',
};

export const ACCESS = {
  commandCenter: [],                        // any admin
  liveMap: ['ops', 'safety_reviewer'],
  safety: ['ops', 'safety_reviewer'],
  recordings: ['safety_reviewer'],
  rides: [],
  rideOverride: ['ops'],
  rideCancel: ['ops'],
  rideRefund: ['finance'],
  receiptResend: ['finance', 'support', 'ops'],
  rideRoute: ['ops', 'safety_reviewer', 'support'],
  ridePayments: ['finance', 'ops'],
  users: ['ops', 'safety_reviewer', 'support'],
  onboarding: ['ops', 'safety_reviewer'],
  finance: ['finance'],
  support: ['ops', 'support', 'safety_reviewer', 'finance'],
  ratings: ['ops', 'support'],
  notifications: ['ops', 'support', 'safety_reviewer'],
  broadcast: ['ops'],
  legal: [],
  legalEdit: ['ops'],
  settings: [],
  settingsEdit: ['ops', 'finance'],
  helpContacts: ['ops', 'safety_reviewer'],
  reports: ['ops', 'support'],
  earningsReport: ['ops', 'support', 'finance'],
  adminUsers: ['super_admin'],
  audit: [],
  legacy: [],
  webhooks: ['finance'],
};

export function hasRole(roles, need) {
  const mine = roles || [];
  if (!mine.length) return false;
  if (mine.includes('super_admin')) return true;
  if (!need || need.length === 0) return true;
  return need.some((r) => mine.includes(r));
}

export function useRoles() {
  const { user } = useAuth();
  const roles = user?.admin_roles || [];
  return {
    roles,
    can: (key) => hasRole(roles, ACCESS[key] ?? [key]),
    isAdmin: roles.length > 0,
  };
}
