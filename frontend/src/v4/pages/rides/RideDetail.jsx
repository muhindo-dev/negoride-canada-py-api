import React, { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Badge, Button, Card, Checkbox, Grid, Group, Modal, NumberInput, ScrollArea, Select, Stack, Tabs, Text, Textarea, Timeline,
} from '@mantine/core';
import { FiDollarSign, FiFileText, FiMail, FiRepeat, FiSkipForward, FiXCircle } from 'react-icons/fi';
import { http, idemKey, openBlob } from '../../lib/api';
import { ago, fmt, humanize, money, RIDE_TYPES } from '../../lib/format';
import { useRealtime } from '../../lib/realtime';
import { useRoles } from '../../lib/roles';
import RouteReplay from '../../components/RouteReplay';
import {
  DataTable, Empty, ErrorBox, KV, Loading, Money, notifyErr, notifyOk, PageHeader, ReasonModal, StageBadge, StatusBadge, Time, UserLink,
} from '../../components/ui';

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

export default function RideDetail() {
  const { type, id } = useParams();
  const qc = useQueryClient();
  const { can } = useRoles();
  const q = useQuery({ queryKey: ['ride', type, String(id)], queryFn: () => http.get(`/admin/rides/${type}/${id}`) });
  const ratings = useQuery({ queryKey: ['ratings', 'ride', type, id], queryFn: () => http.get('/admin/ratings', { ride_id: id, ride_type: type }), enabled: can('ratings') });
  const [modal, setModal] = useState(null);
  const [toStage, setToStage] = useState(null);
  const [policy, setPolicy] = useState('customer_cancel');
  const [refundFor, setRefundFor] = useState(null);
  const [driverId, setDriverId] = useState('');
  const [busy, setBusy] = useState(null);
  const [cancelResult, setCancelResult] = useState(null);
  useRealtime('ride.stage_changed', (p) => {
    if (p?.ride_type === type && String(p?.ride_id) === String(id)) q.refetch();
  });
  const refresh = () => { qc.invalidateQueries({ queryKey: ['ride', type, String(id)] }); qc.invalidateQueries({ queryKey: ['ride-route', type, String(id)] }); };

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const r = q.data;
  const sum = r.summary || {};
  const rc = r.receipt;

  return (
    <>
      <PageHeader
        title={<Group gap="xs">{RIDE_TYPES[r.ride_type]} #{r.id} <StageBadge stage={r.stage} size="lg" />{r.disputed && <Badge color="red">Disputed</Badge>}</Group>}
        subtitle={`Legacy status ${r.legacy_status || '—'} · stage changed ${ago(r.stage_changed_at)} · created ${fmt.dateTime(sum.created_at)}`}
        actions={<>
          {can('rideOverride') && !r.is_terminal && <Button size="xs" variant="light" leftSection={<FiSkipForward />} onClick={() => { setToStage(r.allowed_next?.[0] || null); setModal('override'); }}>Override stage</Button>}
          {can('rideCancel') && !r.is_terminal && <Button size="xs" color="red" variant="light" leftSection={<FiXCircle />} onClick={() => setModal('cancel')}>Cancel ride</Button>}
          {can('rideOverride') && r.ride_type === 'scheduled' && !r.is_terminal && <Button size="xs" variant="default" leftSection={<FiRepeat />} onClick={() => setModal('reassign')}>Reassign</Button>}
          {rc && can('receiptResend') && <Button size="xs" variant="default" leftSection={<FiMail />} loading={busy === 'resend'} onClick={async () => {
            setBusy('resend');
            try { const res = await http.postFull(`/admin/receipts/${rc.id}/resend`); notifyOk(res.message); refresh(); } catch (e) { notifyErr(e, 'Resend failed'); } finally { setBusy(null); }
          }}>Resend receipt</Button>}
          {rc && can('finance') && <Button size="xs" variant="default" leftSection={<FiFileText />} onClick={() => openBlob(`/admin/finance/receipts/${rc.id}/pdf`).catch((e) => notifyErr(e))}>Receipt PDF</Button>}
        </>}
      />
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
                ['Status', <StatusBadge value={r.payment?.status} />],
                ['Authorized', money(r.payment?.amount_authorized_cents)], ['Captured', money(r.payment?.amount_captured_cents)],
                ['Refunded', money(r.payment?.amount_refunded_cents)], ['Card', r.payment?.card],
                ['Receipt', rc ? `${rc.number} · ${money(rc.total_cents)} · emailed ${rc.email_count || 0}×` : '—'],
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
                  { key: 'capture_status', label: 'Status', render: (p) => <StatusBadge value={p.capture_status} /> },
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
          await http.post(`/admin/rides/${type}/${id}/transition`, { to_stage: toStage, reason });
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
          const res = await http.post(`/admin/rides/${type}/${id}/cancel`, { reason, policy_reason: policy });
          setCancelResult(res);
          notifyOk('Ride cancelled');
          refresh();
        }}
      >
        <Select label="Which cancellation-policy rule applies" data={POLICY_REASONS} value={policy} onChange={(v) => setPolicy(v)} allowDeselect={false} />
      </ReasonModal>

      <Modal opened={modal === 'reassign'} onClose={() => setModal(null)} title="Reassign driver" centered>
        <Stack>
          <Alert color="yellow">Uses the legacy scheduled-booking assign endpoint (no v4 reassign endpoint exists yet; not written to trip_events).</Alert>
          <NumberInput label="New driver user ID" value={driverId} onChange={setDriverId} hideControls />
          <Group justify="flex-end">
            <Button disabled={!driverId} loading={busy === 'reassign'} onClick={async () => {
              setBusy('reassign');
              try { await http.post(`/admin/bookings/${id}/assign-driver`, { driver_id: driverId }); notifyOk('Driver assigned'); setModal(null); refresh(); } catch (e) { notifyErr(e); } finally { setBusy(null); }
            }}>Assign</Button>
          </Group>
        </Stack>
      </Modal>

      <RefundModal key={refundFor?.id} payment={refundFor} opened={!!refundFor} onClose={() => setRefundFor(null)} onDone={refresh} />
    </>
  );
}
