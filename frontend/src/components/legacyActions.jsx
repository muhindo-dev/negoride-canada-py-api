// Shared helpers for the legacy (v3) Negotiations / Trips / Bookings pages.
// The backend now routes every legacy admin status change, cancel, mark-paid
// and driver assignment through the v4 trip state machine: a reason (≥ 5 chars)
// is mandatory and the errors carry codes — reason_required (400),
// payment_required (402), invalid_transition / terminal / bad_stage (409, with
// data.stage). These helpers collect the reason and surface those errors, and
// link every ride to the v4 ride detail (the preferred place for actions).
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert, Anchor, Button, Group, Modal, NumberInput, Select, Stack, Text, Textarea,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { FiExternalLink } from 'react-icons/fi';
import { describeError, http } from '../v4/lib/api';
import { StageBadge } from '../v4/components/ui';

export const TERMINAL_STAGES = [
  'COMPLETED', 'CLOSED', 'EXPIRED', 'DECLINED', 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_DRIVER',
  'CUSTOMER_NO_SHOW', 'DRIVER_NO_SHOW', 'NO_SHOW', 'DROPPED_OFF',
];

export const POLICY_REASONS = [
  { value: 'customer_cancel', label: 'Customer cancelled (fee per §7 applies)' },
  { value: 'driver_cancel', label: 'Driver cancelled (full refund + driver strike)' },
  { value: 'safety', label: 'Safety ending (pro-rated / $0 after review)' },
  { value: 'driver_no_show', label: 'Driver no-show (full refund, strike)' },
  { value: 'expired', label: 'Expired (no fee)' },
];

export function isTerminal(stage, legacyStatus) {
  if (stage) return TERMINAL_STAGES.includes(stage);
  return ['completed', 'cancelled', 'canceled'].includes(String(legacyStatus || '').toLowerCase());
}

export function StageCell({ stage }) {
  return stage ? <StageBadge stage={stage} size="xs" /> : <span style={{ color: '#999', fontSize: 12 }}>legacy</span>;
}

export function V4RideLink({ type, id, label = 'Open in v4 ride detail' }) {
  return (
    <Anchor component={Link} to={`/rides/${type}/${id}`} size="sm" data-testid="v4-ride-link">
      <Group gap={4} wrap="nowrap" component="span">{label} <FiExternalLink size={12} /></Group>
    </Anchor>
  );
}

/** Stage row + v4 link for the legacy drawers. */
export function StageSection({ type, ride }) {
  return (
    <div className="d-section">
      <h4>Workflow (v4 state machine)</h4>
      <div className="d-row"><span className="dk">Stage</span><span className="dv"><StageCell stage={ride.trip_stage} /></span></div>
      <div className="d-row"><span className="dk">Legacy status</span><span className="dv">{ride.status || '—'}</span></div>
      <div style={{ marginTop: 8 }}><V4RideLink type={type} id={ride.id} /></div>
      <p style={{ fontSize: 12, color: '#888', marginTop: 6 }}>
        Status changes here walk the ride through the v4 state machine as “admin” (notifications, payments, refunds and
        the timeline fire as usual). Every change needs a reason and is audited.
      </p>
    </div>
  );
}

/**
 * Reason dialog for one legacy action.
 * action = {title, url, body, confirmLabel, color, description, policy?: bool, amount?: bool, reasonOptional?: bool, successMessage}
 */
export function LegacyActionModal({ action, onClose, onDone }) {
  const [reason, setReason] = useState('');
  const [policy, setPolicy] = useState('customer_cancel');
  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (!action) return null;
  const minLen = action.reasonOptional ? 0 : 5;
  const ok = action.reasonOptional ? (reason.trim().length === 0 || reason.trim().length >= 5) : reason.trim().length >= minLen;
  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const body = { ...(action.body || {}) };
      if (reason.trim()) body.reason = reason.trim();
      if (action.policy) body.policy_reason = policy;
      if (action.amount && amount !== '' && amount !== null) body.amount_cents = Math.round(Number(amount) * 100);
      const data = await http.post(action.url, body);
      notifications.show({ color: 'green', title: 'Done', message: action.successMessage || 'Updated' });
      onDone?.(data);
      onClose();
    } catch (e) {
      setErr(describeError(e));
    } finally { setBusy(false); }
  };
  return (
    <Modal opened onClose={onClose} title={action.title} centered size="lg">
      <Stack>
        {action.description && <Text size="sm">{action.description}</Text>}
        {action.policy && <Select label="Which cancellation-policy rule applies" data={POLICY_REASONS} value={policy} onChange={(v) => setPolicy(v)} allowDeselect={false} />}
        {action.amount && (
          <NumberInput label="Amount received (CAD, optional)" description="Leave empty to use the agreed price." value={amount} onChange={setAmount} min={0} decimalScale={2} fixedDecimalScale prefix="$" />
        )}
        <Textarea
          label={action.reasonOptional ? 'Reason (required when replacing a driver)' : 'Reason'} required={!action.reasonOptional} autosize minRows={3}
          value={reason} onChange={(e) => setReason(e.currentTarget.value)} data-autofocus data-testid="legacy-reason"
          description={action.reasonOptional ? 'At least 5 characters when given. Stored in the audit log.' : 'Mandatory, at least 5 characters. Stored in the audit log and the ride timeline.'}
        />
        {err && <Alert color="red" data-testid="legacy-error">{err}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Close</Button>
          <Button color={action.color || 'blue'} loading={busy} disabled={!ok} onClick={submit} data-testid="legacy-confirm">{action.confirmLabel || 'Confirm'}</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

// ── Account status (legacy Users page) ─────────────────────────────────────
// POST /api/admin/users/{id}/toggle-status and the legacy editor's `status`
// now require `reason_code` (GET /api/admin/account-status/reasons) and a
// free-text `reason_text`; otherwise reason_required / reason_text_required.

let reasonsCache = null;
export function useAccountReasons() {
  const [state, setState] = useState(() => reasonsCache || { loading: true, reasons: [], error: null });
  React.useEffect(() => {
    if (reasonsCache) return undefined;
    let alive = true;
    http.get('/admin/account-status/reasons')
      .then((d) => { reasonsCache = { loading: false, reasons: d.reasons || [], error: null }; if (alive) setState(reasonsCache); })
      .catch((e) => alive && setState({ loading: false, reasons: [], error: e.message }));
    return () => { alive = false; };
  }, []);
  return state;
}

export function reasonOptions(reasons) {
  const groups = {};
  reasons.forEach((r) => { (groups[r.category || 'other'] ||= []).push({ value: r.code, label: r.label }); });
  return Object.entries(groups).map(([group, items]) => ({ group: group.replace(/_/g, ' '), items }));
}

export function AccountToggleModal({ user, onClose, onDone }) {
  const { reasons, loading, error } = useAccountReasons();
  const [code, setCode] = useState(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (!user) return null;
  const activating = user.status !== 'active';
  return (
    <Modal opened onClose={onClose} centered size="lg" title={`${activating ? 'Activate' : 'Deactivate'} ${user.name || `user #${user.id}`}`}>
      <Stack>
        <Text size="sm">
          {activating
            ? 'Reactivates the account. The user is notified and can sign in again.'
            : 'Deactivates the account: every session is revoked, the user is notified and sees the suspended screen with the option to appeal. An active ride is finished first.'}
          {' '}For suspensions with an end date, bans or a message preview use the <Anchor component={Link} to={`/users/${user.id}`} size="sm">v4 user page</Anchor>.
        </Text>
        {error && <Alert color="red" py={6}>Could not load the reasons list: {error}</Alert>}
        <Select label="Reason" required searchable placeholder={loading ? 'Loading…' : 'Choose a reason'} data={reasonOptions(reasons)} value={code} onChange={setCode} data-testid="toggle-reason-code" />
        <Textarea label="Explanation" required autosize minRows={2} value={text} onChange={(e) => setText(e.currentTarget.value)} description="Mandatory. Stored with the status change and in the audit log." data-testid="toggle-reason-text" />
        {err && <Alert color="red" data-testid="toggle-error">{err}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Close</Button>
          <Button color={activating ? 'green' : 'orange'} loading={busy} disabled={!code || !text.trim()} data-testid="toggle-confirm"
            onClick={async () => {
              setBusy(true); setErr(null);
              try {
                const d = await http.post(`/admin/users/${user.id}/toggle-status`, { reason_code: code, reason_text: text.trim() });
                const deferred = !activating && d?.status === 'active';
                notifications.show(deferred ? {
                  color: 'yellow', autoClose: 12000, title: 'Deactivation deferred',
                  message: `${user.name || `#${user.id}`} is on an active ride — the change is applied automatically when the ride ends (see the v4 user page).`,
                } : { color: 'green', title: 'Status updated', message: `${user.name || `#${user.id}`} is now ${d?.status || (activating ? 'active' : 'inactive')}` });
                onDone?.(d);
                onClose();
              } catch (e) { setErr(describeError(e)); } finally { setBusy(false); }
            }}>
            {activating ? 'Activate' : 'Deactivate'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
