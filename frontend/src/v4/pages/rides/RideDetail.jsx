import React, { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Anchor, Badge, Button, Card, Checkbox, Grid, Group, Image, Modal, NumberInput, ScrollArea, Select, SegmentedControl, Stack, Tabs, Text, Textarea, Timeline,
} from '@mantine/core';
import { FiCamera, FiDollarSign, FiFilePlus, FiFileText, FiMail, FiRepeat, FiShield, FiSkipForward, FiXCircle } from 'react-icons/fi';
import { describeError, http, idemKey, openBlob } from '../../lib/api';
import { ago, fmt, humanize, money, RIDE_TYPES } from '../../lib/format';
import { DocZoomModal } from '../../components/DocViewer';
import { useRealtime } from '../../lib/realtime';
import { useRoles } from '../../lib/roles';
import RouteReplay from '../../components/RouteReplay';
import {
  DataTable, Empty, ErrorBox, KV, Loading, Money, notifyErr, notifyOk, PageHeader, ReasonModal, StageBadge, StatusBadge, Time, UserLink,
} from '../../components/ui';

const REASSIGNABLE = ['REQUESTED', 'NEGOTIATING', 'PRICE_AGREED', 'AWAITING_PAYMENT', 'CONFIRMED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVING'];

const POLICY_REASONS = [
  { value: 'customer_cancel', label: 'Customer cancelled (fee per §7 applies)' },
  { value: 'driver_cancel', label: 'Driver cancelled (full refund + driver strike)' },
  { value: 'safety', label: 'Safety ending (pro-rated / $0 after review)' },
  { value: 'driver_no_show', label: 'Driver no-show (full refund, strike)' },
  { value: 'expired', label: 'Expired (no fee)' },
];

function RefundModal({ payment, opened, onClose, onDone }) {
  const refundable = payment ? (payment.amount_captured_cents || 0) - (payment.amount_refunded_cents || 0) : 0;
  const [amount, setAmount] = useState(refundable / 100);
  const [reason, setReason] = useState('');
  const [clawback, setClawback] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [key] = useState(() => idemKey('refund'));
  if (!payment) return null;
  const cents = Math.round(Number(amount || 0) * 100);
  return (
    <Modal opened={opened} onClose={onClose} title={`Refund payment #${payment.id}`} centered>
      <Stack>
        <KV items={[['Captured', money(payment.amount_captured_cents)], ['Already refunded', money(payment.amount_refunded_cents)], ['Refundable', money(refundable)]]} />
        {payment.capture_status === 'authorized' && <Alert color="yellow">This is still an authorization hold — cancel the ride to release it instead.</Alert>}
        <NumberInput label="Amount (CAD)" value={amount} onChange={setAmount} min={0.01} max={refundable / 100} decimalScale={2} fixedDecimalScale prefix="$" />
        <Textarea label="Reason" required value={reason} onChange={(e) => setReason(e.currentTarget.value)} description="Mandatory (≥ 5 chars). Audited; the customer gets a credit note." autosize minRows={2} />
        <Checkbox label="Claw back the driver’s share from their wallet" checked={clawback} onChange={(e) => setClawback(e.currentTarget.checked)} />
        {err && <Alert color="red">{err}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color="grape" loading={busy} disabled={reason.trim().length < 5 || cents <= 0 || cents > refundable}
            onClick={async () => {
              setBusy(true); setErr(null);
              try {
                const r = await http.postFull(`/admin/ride-payments/${payment.id}/refund`, { amount_cents: cents, reason: reason.trim(), clawback }, { 'Idempotency-Key': key });
                notifyOk(`${r.message} · ${money(r.data?.refunded_cents)}`);
                onDone(); onClose();
              } catch (e) { setErr(e.message); } finally { setBusy(false); }
            }}>
            Refund {money(cents)}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/** Safety-ended ride (§7.1): charge a pro-rated amount (0 = nothing) and release/refund the rest. */
function SettleSafetyModal({ ride, settlement, opened, onClose, onDone }) {
  const held = Number(settlement?.held_cents || 0);
  const [mode, setMode] = useState('none');
  const [amount, setAmount] = useState(0);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const cents = mode === 'none' ? 0 : mode === 'full' ? held : Math.round(Number(amount || 0) * 100);
  return (
    <Modal opened={opened} onClose={onClose} title={`Settle safety ride — ${RIDE_TYPES[ride.ride_type]} #${ride.id}`} centered size="lg">
      <Stack>
        <Alert color="orange" icon={<FiShield />} py={6}>
          The ride ended for safety. {money(held)} is held{settlement?.due_at ? <> — auto-release <b>{fmt.dateTime(settlement.due_at)}</b> ({ago(settlement.due_at)})</> : ''}.
          Charge only what is fair for the distance travelled; the rest is released or refunded to the customer.
        </Alert>
        <SegmentedControl value={mode} onChange={setMode} data={[{ value: 'none', label: 'Charge nothing' }, { value: 'partial', label: 'Pro-rated amount' }, { value: 'full', label: `Full ${money(held)}` }]} data-testid="settle-mode" />
        {mode === 'partial' && (
          <NumberInput label="Amount to charge (CAD)" value={amount} onChange={setAmount} min={0} max={held / 100} decimalScale={2} fixedDecimalScale prefix="$" description={`Between $0.00 and ${money(held)}`} />
        )}
        <Textarea label="Reason" required value={reason} onChange={(e) => setReason(e.currentTarget.value)} autosize minRows={2} description="Mandatory (≥ 5 chars). Audited as payment.safety_settlement." data-testid="settle-reason" />
        <Text size="sm">Charge <b>{money(cents)}</b> · release/refund <b>{money(Math.max(0, held - cents))}</b></Text>
        {err && <Alert color="red" py={6}>{err}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color="orange" loading={busy} disabled={reason.trim().length < 5 || cents < 0 || cents > held} data-testid="settle-submit"
            onClick={async () => {
              setBusy(true); setErr(null);
              try {
                const res = await http.postFull(`/admin/rides/${ride.ride_type}/${ride.id}/settle-safety`, { amount_cents: cents, reason: reason.trim() });
                const d = res.data || {};
                notifyOk(`Charged ${money(d.charged_cents)} · released ${money(d.released_cents)} · refunded ${money(d.refunded_cents)}`, 'Safety settlement applied');
                onDone(); onClose();
              } catch (e) { setErr(describeError(e)); } finally { setBusy(false); }
            }}>
            Settle {money(cents)}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

/**
 * Vehicle photo: the ride payload's `photo_url` is only issued to ride parties
 * (customer/driver), so admins load the driver's approved `vehicle_front`
 * onboarding document through the audited document endpoint.
 */
function VehiclePhoto({ vehicle, driverId, canDocs }) {
  const [doc, setDoc] = useState(null);
  const [busy, setBusy] = useState(false);
  if (vehicle?.photo_url) {
    return <Image src={vehicle.photo_url} h={120} w="auto" fit="contain" radius="sm" alt="Vehicle" data-testid="vehicle-photo" />;
  }
  if (!canDocs || !driverId) return <Text size="xs" c="dimmed">No photo</Text>;
  return (
    <>
      <Button size="compact-xs" variant="light" leftSection={<FiCamera />} loading={busy} data-testid="vehicle-photo-btn"
        onClick={async () => {
          setBusy(true);
          try {
            const p = await http.get(`/admin/users/${driverId}/profile`);
            const docs = (p.documents || []).filter((d) => d.type === 'vehicle_front');
            const best = docs.find((d) => d.status === 'approved') || docs[0];
            if (!best) throw new Error('The driver has no vehicle photo on file.');
            setDoc(best);
          } catch (e) { notifyErr(e, 'Vehicle photo'); } finally { setBusy(false); }
        }}>
        Show vehicle photo
      </Button>
      <DocZoomModal doc={doc} opened={!!doc} onClose={() => setDoc(null)} />
    </>
  );
}

export default function RideDetail() {
  const { type, id } = useParams();
  const qc = useQueryClient();
  const { can } = useRoles();
  const q = useQuery({ queryKey: ['ride', type, String(id)], queryFn: () => http.get(`/admin/rides/${type}/${id}`) });
  // The chat log is only served for disputed rides or rides with a safety
  // incident (403 not_disputed otherwise) — fetch it automatically only for
  // disputed rides; otherwise on demand from the Chat tab.
  const [chatWanted, setChatWanted] = useState(false);
  const chat = useQuery({
    queryKey: ['ride-chat', type, String(id)],
    queryFn: () => http.get(`/admin/rides/${type}/${id}/chat`),
    enabled: can('rideChat') && (!!q.data?.disputed || chatWanted),
    retry: false,
  });
  const ratings = useQuery({ queryKey: ['ratings', 'ride', type, id], queryFn: () => http.get('/admin/ratings', { ride_id: id, ride_type: type }), enabled: can('ratings') });
  const [modal, setModal] = useState(null);
  const [toStage, setToStage] = useState(null);
  const [policy, setPolicy] = useState('customer_cancel');
  const [refundFor, setRefundFor] = useState(null);
  const [driverId, setDriverId] = useState('');
  const [busy, setBusy] = useState(null);
  const [cancelResult, setCancelResult] = useState(null);
  useRealtime('ride.driver_reassigned', (p) => {
    if (p?.ride_type === type && String(p?.ride_id) === String(id)) q.refetch();
  });
  useRealtime('ride.stage_changed', (p) => {
    if (p?.ride_type === type && String(p?.ride_id) === String(id)) q.refetch();
  });
  const refresh = () => { qc.invalidateQueries({ queryKey: ['ride-chat', type, String(id)] }); qc.invalidateQueries({ queryKey: ['ride', type, String(id)] }); qc.invalidateQueries({ queryKey: ['ride-route', type, String(id)] }); };

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const r = q.data;
  const sum = r.summary || {};
  const rc = r.receipt;
  const settle = r.safety_settlement;
  const tips = r.tip_receipts?.items || [];
  const receiptable = ['carhire', 'scheduled', 'rideshare_booking'].includes(r.ride_type)
    && (['COMPLETED', 'DROPPED_OFF', 'CLOSED'].includes(r.stage) || (r.payments || []).some((p) => ['captured', 'partially_captured', 'refunded', 'partially_refunded'].includes(p.capture_status)));
  const refundStatus = r.payment?.refund_status;

  return (
    <>
      <PageHeader
        title={<Group gap="xs">{RIDE_TYPES[r.ride_type]} #{r.id} <StageBadge stage={r.stage} size="lg" />{r.disputed && <Badge color="red">Disputed</Badge>}</Group>}
        subtitle={`Legacy status ${r.legacy_status || '—'} · stage changed ${ago(r.stage_changed_at)} · created ${fmt.dateTime(sum.created_at)}`}
        actions={<>
          {can('rideOverride') && !r.is_terminal && <Button size="xs" variant="light" leftSection={<FiSkipForward />} onClick={() => { setToStage(r.allowed_next?.[0] || null); setModal('override'); }}>Override stage</Button>}
          {can('rideCancel') && !r.is_terminal && <Button size="xs" color="red" variant="light" leftSection={<FiXCircle />} onClick={() => setModal('cancel')}>Cancel ride</Button>}
          {can('rideReassign') && ['carhire', 'scheduled'].includes(r.ride_type) && REASSIGNABLE.includes(r.stage) && <Button size="xs" variant="default" leftSection={<FiRepeat />} onClick={() => setModal('reassign')}>Reassign</Button>}
          {can('settleSafety') && settle?.status === 'safety_review' && <Button size="xs" color="orange" leftSection={<FiShield />} onClick={() => setModal('settle')} data-testid="settle-btn">Settle safety ride</Button>}
          {!rc && receiptable && can('receiptIssue') && <Button size="xs" variant="default" leftSection={<FiFilePlus />} loading={busy === 'issue'} data-testid="issue-receipt" onClick={async () => {
            setBusy('issue');
            try {
              const res = await http.postFull(`/admin/rides/${type}/${id}/receipt/issue`);
              if (res.data?.queued) {
                notifyOk('Receipt queued — it is issued and emailed by a background job; this page refreshes shortly.', 'Queued');
                setTimeout(refresh, 3000);
              } else {
                notifyOk(`Receipt ${res.data?.receipt?.number || ''} issued`);
                refresh();
              }
            } catch (e) { notifyErr({ message: describeError(e) }, 'Issue failed'); } finally { setBusy(null); }
          }}>Issue receipt</Button>}
          {rc && can('receiptResend') && <Button size="xs" variant="default" leftSection={<FiMail />} loading={busy === 'resend'} data-testid="resend-receipt" onClick={async () => {
            setBusy('resend');
            try {
              const res = await http.postFull(`/admin/receipts/${rc.id}/resend`);
              notifyOk(`${res.message}${res.data?.queued ? ' — queued; the email count updates once the job has sent it.' : ''}`, res.data?.queued ? 'Queued' : 'Done');
              setTimeout(refresh, 4000);
            } catch (e) { notifyErr(e, 'Resend failed'); } finally { setBusy(null); }
          }}>Resend receipt</Button>}
          {rc && can('finance') && <Button size="xs" variant="default" leftSection={<FiFileText />} onClick={() => openBlob(`/admin/finance/receipts/${rc.id}/pdf`).catch((e) => notifyErr(e))}>Receipt PDF</Button>}
        </>}
      />
      {settle?.status === 'safety_review' && (
        <Alert color="orange" mb="sm" icon={<FiShield />} title="Payment on hold — safety review" data-testid="settle-alert">
          This ride ended for safety. {money(settle.held_cents)} is held until a decision
          {settle.due_at ? <> — it is released automatically <b>{fmt.dateTime(settle.due_at)}</b> ({ago(settle.due_at)})</> : ''}.
          {can('settleSafety') ? ' Use “Settle safety ride” to charge a pro-rated amount (or nothing).' : ' A safety reviewer, ops or finance admin must settle it.'}
        </Alert>
      )}
      {settle && settle.status !== 'safety_review' && (
        <Alert color="gray" mb="sm" icon={<FiShield />} py={6}>
          Safety settlement: <b>{humanize(settle.status)}</b>
          {settle.decision ? ` — charged ${money(settle.decision.charged_cents ?? settle.decision.amount_cents)}${settle.decision.reason ? ` · “${settle.decision.reason}”` : ''}` : ''}
        </Alert>
      )}
      {cancelResult && (
        <Alert color="blue" mb="sm" withCloseButton onClose={() => setCancelResult(null)} title="Cancellation applied">
          {cancelResult.policy ? `${cancelResult.policy.explanation || ''} Fee ${cancelResult.policy.fee}, refund ${cancelResult.policy.refund} (rule ${cancelResult.policy.rule_id}).` : 'No policy decision returned.'}
        </Alert>
      )}
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack gap="sm">
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Trip</Text>
              <KV items={[
                ['Pickup', r.pickup?.address], ['Drop-off', r.dropoff?.address],
                ['Fare', <Money cents={r.price?.fare_cents} />],
                r.price?.initial_cents !== null && r.price?.initial_cents !== undefined && ['Customer offer', <Money cents={r.price.initial_cents} />],
                ['Customer', r.customer ? <UserLink id={r.customer.id} name={r.customer.name} /> : (sum.customer_ids?.length ? sum.customer_ids.map((c) => <UserLink key={c} id={c} />) : '—')],
                ['Driver', r.driver ? <UserLink id={r.driver.id} name={`${r.driver.name}${r.driver.rating ? ` · ★ ${r.driver.rating.toFixed(2)}` : ''}`} /> : '—'],
                r.vehicle && ['Vehicle', [r.vehicle.color, r.vehicle.year, r.vehicle.make, r.vehicle.model, r.vehicle.plate && `(${r.vehicle.plate})`].filter(Boolean).join(' ')],
                r.driver && ['Vehicle photo', <VehiclePhoto vehicle={r.vehicle} driverId={r.driver.id} canDocs={can('onboarding')} />],
                r.pin && ['Ride PIN', <Text span ff="monospace" fw={700}>{r.pin}</Text>],
                r.eta && ['ETA', `${r.eta.minutes} min · ${(r.eta.distance_m / 1000).toFixed(1)} km (${r.eta.target})`],
                r.wait && ['Wait timer', `${r.wait.seconds_left}s left of ${r.wait.window_s}s`],
                r.departure_at && ['Departure', fmt.dateTime(r.departure_at)],
                ['Allowed next', (r.allowed_next || []).map((s) => <StageBadge key={s} stage={s} size="xs" />)],
              ]} />
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Payment</Text>
              <KV items={[
                ['Status', <Group gap={4}><StatusBadge value={r.payment?.status} />{r.payment?.provider === 'offline' && <Badge size="xs" variant="outline" color="gray">offline</Badge>}</Group>],
                refundStatus && refundStatus !== 'none' && ['Refund status', <StatusBadge value={refundStatus} />],
                r.payment?.settlement_status && ['Settlement', <StatusBadge value={r.payment.settlement_status} />],
                ['Authorized', money(r.payment?.amount_authorized_cents)], ['Captured', money(r.payment?.amount_captured_cents)],
                ['Refunded', money(r.payment?.amount_refunded_cents)], ['Card', r.payment?.card],
                ['Receipt', rc ? `${rc.number} · ${money(rc.total_cents)} · emailed ${rc.email_count || 0}×` : (receiptable ? 'not issued yet' : '—')],
                tips.length > 0 && ['Tips after ride', (
                  <Stack gap={2}>
                    {tips.map((t) => (
                      <Group key={t.id} gap={6} wrap="nowrap">
                        <Text size="sm" ff="monospace">{t.number}</Text>
                        <Text size="sm">{money(t.amount_cents)}</Text>
                        {can('tipReceipts') && <Anchor size="xs" data-testid="tip-pdf" onClick={() => openBlob(`/admin/finance/tip-receipts/${t.id}/pdf`).catch((e) => notifyErr(e))}>PDF</Anchor>}
                      </Group>
                    ))}
                    <Text size="xs" c="dimmed">Total tips {money(r.tip_receipts.total_cents)}</Text>
                  </Stack>
                )],
              ]} />
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Timestamps</Text>
              <KV items={Object.entries(r.timestamps || {}).filter(([, v]) => v).map(([k, v]) => [humanize(k), fmt.dateTimeSec(v)])} />
            </Card>
            {r.passengers && (
              <Card withBorder radius="md" padding="sm">
                <Text fw={600} mb="xs">Passengers</Text>
                {r.passengers.map((p) => (
                  <Group key={p.booking_id} justify="space-between">
                    <UserLink id={p.customer?.id} name={`${p.customer?.name} · ${p.seats} seat(s)`} />
                    <StageBadge stage={p.stage} size="xs" />
                  </Group>
                ))}
              </Card>
            )}
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Tabs defaultValue={can('rideRoute') ? 'map' : 'timeline'} keepMounted={false}>
            <Tabs.List mb="sm">
              {can('rideRoute') && <Tabs.Tab value="map">Map route</Tabs.Tab>}
              <Tabs.Tab value="timeline">Timeline ({r.timeline?.length || 0})</Tabs.Tab>
              {r.negotiation_history && <Tabs.Tab value="nego">Negotiation & chat ({r.negotiation_history.length})</Tabs.Tab>}
              <Tabs.Tab value="payments">Payments ({r.payments?.length || 0})</Tabs.Tab>
              <Tabs.Tab value="refunds">Refunds ({r.refunds?.length || 0})</Tabs.Tab>
              {can('ratings') && <Tabs.Tab value="ratings">Ratings</Tabs.Tab>}
              {can('rideChat') && <Tabs.Tab value="chat" c={chat.data ? 'red' : undefined}>Chat log{chat.data ? ` (${chat.data.messages?.length || 0})` : ''}</Tabs.Tab>}
            </Tabs.List>
            {can('rideRoute') && <Tabs.Panel value="map"><RouteReplay rideType={r.ride_type} rideId={r.id} live={r.is_active} /></Tabs.Panel>}
            <Tabs.Panel value="timeline">
              <Card withBorder radius="md" padding="sm">
                {r.timeline?.length ? (
                  <Timeline bulletSize={16} lineWidth={2} active={r.timeline.length}>
                    {r.timeline.map((e) => (
                      <Timeline.Item key={e.id} title={<Group gap={6}><StageBadge stage={e.to_stage} size="xs" /><Text size="xs" c="dimmed">from {humanize(e.from_stage)}</Text></Group>}>
                        <Text size="xs" c="dimmed">{fmt.dateTimeSec(e.created_at)} · {e.actor_type}{e.actor_id ? ` #${e.actor_id}` : ''}{e.lat ? ` · ${Number(e.lat).toFixed(4)}, ${Number(e.lng).toFixed(4)}` : ''}</Text>
                        {e.meta && Object.keys(e.meta).length > 0 && <Text size="xs">{Object.entries(e.meta).map(([k, v]) => `${humanize(k)}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')}</Text>}
                      </Timeline.Item>
                    ))}
                  </Timeline>
                ) : <Empty>No trip events recorded (legacy ride).</Empty>}
              </Card>
            </Tabs.Panel>
            {r.negotiation_history && (
              <Tabs.Panel value="nego">
                <Card withBorder radius="md" padding="sm">
                  <ScrollArea.Autosize mah={480}>
                    <Stack gap={6}>
                      {r.negotiation_history.map((n) => {
                        const byDriver = n.last_negotiator_id && n.last_negotiator_id === n.driver_id;
                        return (
                          <Group key={n.id} justify={byDriver ? 'flex-end' : 'flex-start'}>
                            <Card padding={8} radius="md" bg={byDriver ? 'var(--mantine-color-blue-light)' : 'var(--mantine-color-default-hover)'} maw="80%">
                              <Text size="xs" c="dimmed">{byDriver ? 'Driver' : 'Customer'} · {fmt.dateTime(n.created_at)}</Text>
                              {Number(n.price) > 0 && <Text fw={700}>{money(n.price)} {n.price_accepted === 'Yes' && <Badge size="xs" color="green">accepted</Badge>}</Text>}
                              {n.message_body && <Text size="sm">{n.message_body}</Text>}
                            </Card>
                          </Group>
                        );
                      })}
                      {!r.negotiation_history.length && <Empty>No negotiation messages.</Empty>}
                    </Stack>
                  </ScrollArea.Autosize>
                </Card>
              </Tabs.Panel>
            )}
            <Tabs.Panel value="payments">
              <DataTable rows={r.payments || []} minWidth={760} empty="No v4 payment records (legacy/unpaid)."
                columns={[
                  { key: 'id', label: '#' }, { key: 'purpose', label: 'Purpose', render: (p) => humanize(p.purpose) },
                  { key: 'capture_status', label: 'Status', render: (p) => <Group gap={4} wrap="nowrap"><StatusBadge value={p.capture_status} />{p.provider === 'offline' && <Badge size="xs" variant="outline" color="gray">offline</Badge>}</Group> },
                  { key: 'a', label: 'Authorized', align: 'right', render: (p) => <Money cents={p.amount_authorized_cents} size="sm" /> },
                  { key: 'c', label: 'Captured', align: 'right', render: (p) => <Money cents={p.amount_captured_cents} size="sm" /> },
                  { key: 'r', label: 'Refunded', align: 'right', render: (p) => <Money cents={p.amount_refunded_cents} size="sm" /> },
                  { key: 'card', label: 'Card', render: (p) => (p.payment_method_last4 ? `${p.payment_method_brand || ''} •••• ${p.payment_method_last4}` : '—') },
                  { key: 'created_at', label: 'Created', render: (p) => <Time value={p.created_at} /> },
                  { key: 'x', label: '', render: (p) => (can('rideRefund') && (p.amount_captured_cents || 0) > (p.amount_refunded_cents || 0)
                    ? <Button size="compact-xs" color="grape" variant="light" leftSection={<FiDollarSign />} onClick={() => setRefundFor(p)}>Refund</Button> : null) },
                ]} />
            </Tabs.Panel>
            <Tabs.Panel value="refunds">
              <DataTable rows={r.refunds || []} minWidth={700} empty="No refunds or releases."
                columns={[
                  { key: 'id', label: '#' }, { key: 'kind', label: 'Kind', render: (x) => humanize(x.kind) },
                  { key: 'status', label: 'Status', render: (x) => <StatusBadge value={x.status} /> },
                  { key: 'amount', label: 'Amount', align: 'right', render: (x) => <Money cents={x.amount_cents} size="sm" /> },
                  { key: 'rule_id', label: 'Rule' }, { key: 'reason', label: 'Reason', render: (x) => <Text size="xs" lineClamp={2}>{x.reason}</Text> },
                  { key: 'by', label: 'By', render: (x) => `${x.initiated_by_type || ''} ${x.initiated_by ? `#${x.initiated_by}` : ''}` },
                  { key: 'created_at', label: 'When', render: (x) => <Time value={x.created_at} /> },
                ]} />
            </Tabs.Panel>
            {can('rideChat') && !chat.data && (
              <Tabs.Panel value="chat">
                <Card withBorder radius="md" padding="sm">
                  <Text size="sm" mb="xs">
                    For privacy the in-app chat between the parties is only available when the ride is disputed or has a safety incident. Opening it is audited.
                  </Text>
                  {chat.error ? <Alert color="gray" py={6}>{chat.error.message}</Alert> : (
                    <Button size="xs" variant="light" loading={chat.isFetching} onClick={() => setChatWanted(true)} data-testid="load-chat">Load chat log</Button>
                  )}
                </Card>
              </Tabs.Panel>
            )}
            {chat.data && (
              <Tabs.Panel value="chat">
                <Card withBorder radius="md" padding="sm">
                  <Alert color="red" variant="light" mb="sm" py={6}>
                    Shown only because this ride is disputed or has a safety incident. This view is written to the audit log.
                    {chat.data.window && <> Window: {fmt.dateTime(chat.data.window.from)} → {fmt.dateTime(chat.data.window.to)}.</>}
                  </Alert>
                  <ScrollArea.Autosize mah={480}>
                    <Stack gap={6} data-testid="chat-log">
                      {(chat.data.messages || []).map((m) => {
                        const fromDriver = r.driver && m.sender_id === r.driver.id;
                        return (
                          <Group key={m.id} justify={fromDriver ? 'flex-end' : 'flex-start'}>
                            <Card padding={8} radius="md" bg={fromDriver ? 'var(--mantine-color-blue-light)' : 'var(--mantine-color-default-hover)'} maw="80%">
                              <Text size="xs" c="dimmed">{fromDriver ? 'Driver' : 'Customer'} #{m.sender_id} · {fmt.dateTimeSec(m.at)}{m.type && m.type !== 'text' ? ` · ${m.type}` : ''}</Text>
                              {m.body && <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{m.body}</Text>}
                              {m.photo && <Anchor href={m.photo} target="_blank" rel="noopener" size="xs">photo</Anchor>}
                              {m.audio && <audio controls src={m.audio} style={{ maxWidth: 240 }} />}
                            </Card>
                          </Group>
                        );
                      })}
                      {!chat.data.messages?.length && <Empty>No in-app chat messages between the parties in the ride window.</Empty>}
                    </Stack>
                  </ScrollArea.Autosize>
                  {chat.data.negotiation?.length > 0 && <Text size="xs" c="dimmed" mt="xs">{chat.data.negotiation.length} negotiation message(s) — see the Negotiation tab.</Text>}
                </Card>
              </Tabs.Panel>
            )}
            {can('ratings') && (
              <Tabs.Panel value="ratings">
                {ratings.error ? <ErrorBox error={ratings.error} /> : (
                  <DataTable rows={ratings.data?.items || []} loading={ratings.isLoading} empty="No ratings for this ride."
                    columns={[
                      { key: 'stars', label: 'Stars', render: (x) => '★'.repeat(x.stars) },
                      { key: 'role', label: 'Rated by', render: (x) => `${x.rater?.name || '#' + x.rater_id} (${x.role})` },
                      { key: 'ratee', label: 'About', render: (x) => x.ratee?.name || `#${x.ratee_id}` },
                      { key: 'tags', label: 'Tags', render: (x) => (x.tags || []).join(', ') },
                      { key: 'comment', label: 'Comment' },
                      { key: 'tip', label: 'Tip', render: (x) => (x.tip_cents ? money(x.tip_cents) : '') },
                    ]} />
                )}
              </Tabs.Panel>
            )}
          </Tabs>
        </Grid.Col>
      </Grid>

      <ReasonModal
        opened={modal === 'override'} onClose={() => setModal(null)} title="Admin stage override" confirmLabel="Override" color="orange"
        description={<Alert color="orange">Moves the ride through the state machine as “admin”. Notifications, payments and refunds fire exactly as for a normal transition.</Alert>}
        onSubmit={async (reason) => {
          if (!toStage) throw new Error('Choose a target stage');
          try { await http.post(`/admin/rides/${type}/${id}/transition`, { to_stage: toStage, reason }); } catch (e) { throw new Error(describeError(e)); }
          notifyOk(`Moved to ${humanize(toStage)}`);
          refresh();
        }}
      >
        <Select label="Target stage" required data={(r.allowed_next || []).map((s) => ({ value: s, label: humanize(s) }))} value={toStage} onChange={setToStage}
          description={`Current: ${humanize(r.stage)}. Only transitions allowed by the state machine are listed.`} />
      </ReasonModal>

      <ReasonModal
        opened={modal === 'cancel'} onClose={() => setModal(null)} title={`Cancel ${RIDE_TYPES[r.ride_type]} #${r.id}`} confirmLabel="Cancel ride" color="red"
        onSubmit={async (reason) => {
          let res;
          try { res = await http.post(`/admin/rides/${type}/${id}/cancel`, { reason, policy_reason: policy }); } catch (e) { throw new Error(describeError(e)); }
          setCancelResult(res);
          notifyOk('Ride cancelled');
          refresh();
        }}
      >
        <Select label="Which cancellation-policy rule applies" data={POLICY_REASONS} value={policy} onChange={(v) => setPolicy(v)} allowDeselect={false} />
      </ReasonModal>

      <ReasonModal
        opened={modal === 'reassign'} onClose={() => setModal(null)} title="Reassign driver" confirmLabel="Reassign" color="blue"
        description={<Text size="sm">Current driver: {r.driver ? `${r.driver.name} (#${r.driver.id})` : 'none'}. The new driver must be approved and active. Both drivers and the customer are notified; a timeline event and an audit entry are written.</Text>}
        onSubmit={async (reason) => {
          if (!driverId) throw new Error('Enter the new driver’s user ID');
          try { await http.post(`/admin/rides/${type}/${id}/reassign`, { driver_id: Number(driverId), reason }); } catch (e) { throw new Error(describeError(e)); }
          notifyOk('Driver reassigned');
          setDriverId('');
          refresh();
        }}
      >
        <NumberInput label="New driver user ID" required value={driverId} onChange={setDriverId} hideControls data-testid="reassign-driver-id" />
      </ReasonModal>

      {settle && <SettleSafetyModal ride={r} settlement={settle} opened={modal === 'settle'} onClose={() => setModal(null)} onDone={refresh} />}
      <RefundModal key={refundFor?.id} payment={refundFor} opened={!!refundFor} onClose={() => setRefundFor(null)} onDone={refresh} />
    </>
  );
}
