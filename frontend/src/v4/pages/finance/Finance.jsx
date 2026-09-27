import React, { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Anchor, Badge, Button, Card, Group, Select, SimpleGrid, Stack, Switch, Tabs, Text, TextInput,
} from '@mantine/core';
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { FiFileText, FiMail, FiPlay } from 'react-icons/fi';
import { http, openBlob, page } from '../../lib/api';
import { humanize, money } from '../../lib/format';
import {
  CsvButton, DataTable, ErrorBox, Money, notifyErr, notifyOk, PageHeader, RideLink, StatCard, StatusBadge, Time, UserLink,
} from '../../components/ui';

const M = (c) => <Money cents={c} size="sm" />;

function usePaged(key, url, params) {
  const [p, setP] = useState(1);
  const q = useQuery({ queryKey: ['finance', key, params, p], queryFn: () => http.get(url, { ...params, page: p, per_page: 25 }) });
  return { q, pg: page(q.data), setP };
}

function Overview({ range }) {
  const s = useQuery({ queryKey: ['finance', 'summary', range], queryFn: () => http.get('/admin/finance/payments/summary', range) });
  const c = useQuery({ queryKey: ['finance', 'commission', range], queryFn: () => http.get('/admin/finance/commission', range) });
  const t = s.data?.totals || {};
  const ct = c.data?.totals || {};
  return (
    <Stack gap="sm">
      <ErrorBox error={s.error || c.error} />
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm">
        <StatCard label="Captured" value={money(t.captured_cents)} />
        <StatCard label="Refunded" value={money(t.refunded_cents)} color={t.refunded_cents ? 'grape' : undefined} />
        <StatCard label="Net collected" value={money(t.net_collected_cents)} color="green" />
        <StatCard label="Holds released" value={money(t.released_cents)} />
        <StatCard label="Open authorizations" value={money(t.open_holds_cents)} hint={`${t.open_holds_count ?? 0} holds · ${t.expiring_24h_count ?? 0} expiring < 24h`} color={t.expiring_24h_count ? 'orange' : undefined} />
        <StatCard label="Commission revenue" value={money(ct.revenue_cents)} hint={`${ct.rides ?? 0} receipted rides`} color="orange" />
        <StatCard label="Commission" value={money(ct.commission_cents)} />
        <StatCard label="Booking fees" value={money(ct.booking_fees_cents)} />
      </SimpleGrid>
      <Card withBorder radius="md" padding="sm">
        <Group justify="space-between" mb="xs"><Text fw={600}>Commission revenue by day</Text><CsvButton url="/admin/finance/commission" params={range} name="commission" /></Group>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={(c.data?.days || []).map((d) => ({ ...d, commission: d.commission_cents / 100, fees: d.booking_fees_cents / 100 }))}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
            <Tooltip formatter={(v) => money(Math.round(v * 100))} />
            <Legend />
            <Area type="monotone" dataKey="commission" name="Commission" stackId="1" stroke="#ef9b11" fill="#ef9b11" fillOpacity={0.4} />
            <Area type="monotone" dataKey="fees" name="Booking fees" stackId="1" stroke="#1c7ed6" fill="#1c7ed6" fillOpacity={0.3} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>
      <Card withBorder radius="md" padding="sm">
        <Group justify="space-between" mb="xs"><Text fw={600}>By capture status</Text><CsvButton url="/admin/finance/payments/summary" params={range} name="payments-summary" /></Group>
        <DataTable rows={Object.entries(s.data?.by_status || {}).map(([k, v]) => ({ id: k, ...v }))} minWidth={500}
          columns={[
            { key: 'id', label: 'Status', render: (r) => <StatusBadge value={r.id} /> }, { key: 'count', label: 'Count' },
            { key: 'a', label: 'Authorized', align: 'right', render: (r) => M(r.authorized_cents) },
            { key: 'c', label: 'Captured', align: 'right', render: (r) => M(r.captured_cents) },
            { key: 'r', label: 'Refunded', align: 'right', render: (r) => M(r.refunded_cents) },
          ]} />
      </Card>
    </Stack>
  );
}

function Payments({ range, fixed = {}, title }) {
  const [purpose, setPurpose] = useState('');
  const [status, setStatus] = useState(fixed.capture_status || '');
  const params = { ...range, purpose, capture_status: status };
  const { q, pg, setP } = usePaged(`payments-${title}`, '/admin/finance/payments', params);
  return (
    <>
      <Group mb="sm" gap="xs" justify="space-between">
        <Group gap="xs">
          {!fixed.capture_status && <Select size="xs" placeholder="Any status" clearable value={status} onChange={(v) => setStatus(v || '')} data={['pending', 'authorized', 'captured', 'partially_captured', 'canceled', 'failed', 'refunded', 'partially_refunded']} w={180} />}
          <Select size="xs" placeholder="Any purpose" clearable value={purpose} onChange={(v) => setPurpose(v || '')} data={['ride', 'tip', 'background_check', 'cancellation_fee']} w={170} />
        </Group>
        <CsvButton url="/admin/finance/payments" params={params} name="payments" />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={1100} empty="No payments."
        columns={[
          { key: 'id', label: '#' },
          { key: 'ride', label: 'Ride', render: (r) => (r.ride_id ? <RideLink type={r.ride_type} id={r.ride_id} /> : '—') },
          { key: 'purpose', label: 'Purpose', render: (r) => humanize(r.purpose) },
          { key: 'capture_status', label: 'Status', render: (r) => <StatusBadge value={r.capture_status} /> },
          { key: 'customer', label: 'Customer', render: (r) => <UserLink id={r.customer_id} /> },
          { key: 'fare', label: 'Fare', align: 'right', render: (r) => M(r.fare_cents) },
          { key: 'auth', label: 'Authorized', align: 'right', render: (r) => M(r.amount_authorized_cents) },
          { key: 'cap', label: 'Captured', align: 'right', render: (r) => M(r.amount_captured_cents) },
          { key: 'ref', label: 'Refunded', align: 'right', render: (r) => M(r.amount_refunded_cents) },
          { key: 'pm', label: 'Method', render: (r) => r.payment_method || '—' },
          { key: 'created_at', label: 'Created', render: (r) => <Time value={r.created_at} /> },
        ]} />
    </>
  );
}

function Refunds({ range }) {
  const [kind, setKind] = useState('');
  const params = { ...range, kind };
  const { q, pg, setP } = usePaged('refunds', '/admin/finance/refunds', params);
  return (
    <>
      <Group mb="sm" justify="space-between">
        <Select size="xs" placeholder="Any kind" clearable value={kind} onChange={(v) => setKind(v || '')} data={['refund', 'release', 'partial_capture']} w={170} />
        <CsvButton url="/admin/finance/refunds" params={params} name="refunds" />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={1000} empty="No refunds."
        columns={[
          { key: 'id', label: '#' }, { key: 'kind', label: 'Kind', render: (r) => humanize(r.kind) },
          { key: 'status', label: 'Status', render: (r) => <StatusBadge value={r.status} /> },
          { key: 'ride', label: 'Ride', render: (r) => <RideLink type={r.ride_type} id={r.ride_id} /> },
          { key: 'amount', label: 'Amount', align: 'right', render: (r) => M(r.amount_cents) },
          { key: 'rule_id', label: 'Rule' }, { key: 'reason', label: 'Reason', render: (r) => <Text size="xs" lineClamp={2} maw={260}>{r.reason}</Text> },
          { key: 'by', label: 'By', render: (r) => `${r.initiated_by_type || ''}${r.initiated_by ? ` #${r.initiated_by}` : ''}` },
          { key: 'cn', label: 'Credit note', render: (r) => (r.credit_note_id ? `#${r.credit_note_id}` : '—') },
          { key: 'created_at', label: 'When', render: (r) => <Time value={r.created_at} /> },
        ]} />
    </>
  );
}

function Receipts({ range }) {
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const params = { ...range, q: search };
  const { q, pg, setP } = usePaged('receipts', '/admin/finance/receipts', params);
  const resend = async (r) => {
    try { const res = await http.postFull(`/admin/finance/receipts/${r.id}/resend`); notifyOk(res.message); qc.invalidateQueries({ queryKey: ['finance', 'receipts'] }); } catch (e) { notifyErr(e, 'Resend failed'); }
  };
  return (
    <>
      <Group mb="sm" justify="space-between">
        <TextInput size="xs" placeholder="Receipt number" value={search} onChange={(e) => setSearch(e.currentTarget.value)} w={200} />
        <CsvButton url="/admin/finance/receipts" params={params} name="receipts" />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={1100} empty="No receipts."
        columns={[
          { key: 'number', label: 'Number', render: (r) => <Text size="sm" ff="monospace">{r.number}</Text> },
          { key: 'ride', label: 'Ride', render: (r) => <RideLink type={r.ride_type} id={r.ride_id} /> },
          { key: 'customer', label: 'Customer', render: (r) => <UserLink id={r.customer_id} /> },
          { key: 'province', label: 'Prov.' },
          { key: 'sub', label: 'Subtotal', align: 'right', render: (r) => M(r.subtotal_cents) },
          { key: 'tax', label: 'Tax', align: 'right', render: (r) => M(r.tax_cents) },
          { key: 'total', label: 'Total', align: 'right', render: (r) => M(r.total_cents) },
          { key: 'credited', label: 'Credited', align: 'right', render: (r) => (r.credited_cents ? M(r.credited_cents) : '—') },
          { key: 'emailed', label: 'Emailed', render: (r) => `${r.email_count || 0}×` },
          { key: 'issued_at', label: 'Issued', render: (r) => <Time value={r.issued_at} /> },
          { key: 'x', label: '', render: (r) => (
            <Group gap={4} wrap="nowrap">
              <Button size="compact-xs" variant="subtle" leftSection={<FiFileText />} onClick={() => openBlob(`/admin/finance/receipts/${r.id}/pdf`).catch(notifyErr)}>PDF</Button>
              <Button size="compact-xs" variant="subtle" leftSection={<FiMail />} onClick={() => resend(r)}>Resend</Button>
            </Group>
          ) },
        ]} />
    </>
  );
}

function CreditNotes({ range }) {
  const { q, pg, setP } = usePaged('credit-notes', '/admin/finance/credit-notes', range);
  return (
    <>
      <Group mb="sm" justify="flex-end"><CsvButton url="/admin/finance/credit-notes" params={range} name="credit-notes" /></Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={900} empty="No credit notes."
        columns={[
          { key: 'number', label: 'Number', render: (r) => <Text size="sm" ff="monospace">{r.number}</Text> },
          { key: 'receipt_number', label: 'Receipt' }, { key: 'customer', label: 'Customer', render: (r) => <UserLink id={r.customer_id} /> },
          { key: 'province', label: 'Prov.' }, { key: 'amount', label: 'Amount', align: 'right', render: (r) => M(r.amount_cents) },
          { key: 'tax', label: 'Tax', align: 'right', render: (r) => M(r.tax_cents) },
          { key: 'reason', label: 'Reason', render: (r) => <Text size="xs" lineClamp={2}>{r.reason}</Text> },
          { key: 'issued_at', label: 'Issued', render: (r) => <Time value={r.issued_at} /> },
          { key: 'x', label: '', render: (r) => <Button size="compact-xs" variant="subtle" onClick={() => openBlob(`/admin/finance/credit-notes/${r.id}/pdf`).catch(notifyErr)}>PDF</Button> },
        ]} />
    </>
  );
}

function Payouts({ range }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState('');
  const params = { ...range, status };
  const { q, pg, setP } = usePaged('payouts', '/admin/finance/payouts', params);
  const act = async (r, what) => {
    let body = {};
    if (what === 'reject') {
      const reason = window.prompt('Reason for rejecting this payout?');
      if (!reason) return;
      body = { reason, admin_notes: reason };
    }
    try { await http.post(`/admin/payout-requests/${r.id}/${what}`, body); notifyOk(`Payout ${what}d`); qc.invalidateQueries({ queryKey: ['finance', 'payouts'] }); } catch (e) { notifyErr(e); }
  };
  return (
    <>
      <Group mb="sm" gap="xs">
        {Object.entries(q.data?.overview || {}).map(([k, v]) => <Badge key={k} variant="light" color="gray">{humanize(k)}: {v.count} · {money(v.amount_cents)}</Badge>)}
      </Group>
      <Group mb="sm" justify="space-between">
        <Select size="xs" placeholder="Any status" clearable value={status} onChange={(v) => setStatus(v || '')} data={['pending', 'approved', 'processing', 'completed', 'rejected', 'failed']} w={160} />
        <CsvButton url="/admin/finance/payouts" params={params} name="payouts" />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={1000} empty="No payout requests."
        columns={[
          { key: 'id', label: '#' }, { key: 'user', label: 'Driver', render: (r) => <UserLink id={r.user_id} /> },
          { key: 'status', label: 'Status', render: (r) => <StatusBadge value={r.status} /> },
          { key: 'method', label: 'Method', render: (r) => humanize(r.payout_method) },
          { key: 'amount', label: 'Amount', align: 'right', render: (r) => M(r.amount_cents) },
          { key: 'fee', label: 'Fee', align: 'right', render: (r) => M(r.fee_cents) },
          { key: 'net', label: 'Net', align: 'right', render: (r) => M(r.net_cents) },
          { key: 'requested_at', label: 'Requested', render: (r) => <Time value={r.requested_at} /> },
          { key: 'failure', label: 'Failure', render: (r) => <Text size="xs" c="red">{r.failure_reason}</Text> },
          { key: 'x', label: '', render: (r) => (r.status === 'pending' ? (
            <Group gap={4} wrap="nowrap">
              <Button size="compact-xs" color="green" variant="light" onClick={() => act(r, 'approve')}>Approve</Button>
              <Button size="compact-xs" color="red" variant="light" onClick={() => act(r, 'reject')}>Reject</Button>
            </Group>
          ) : r.status === 'approved' ? <Button size="compact-xs" variant="light" onClick={() => act(r, 'complete')}>Mark paid</Button> : null) },
        ]} />
    </>
  );
}

function Wallets() {
  const [p, setP] = useState(1);
  const q = useQuery({ queryKey: ['finance', 'wallets', p], queryFn: () => http.get('/admin/wallets', { page: p, per_page: 25 }) });
  const pg = page(q.data);
  return (
    <>
      <Text size="xs" c="dimmed" mb="xs">Driver wallet ledger (legacy wallet service; balances in dollars). Adjustments: Users → legacy Users & Drivers.</Text>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={700} empty="No wallets."
        columns={[
          { key: 'user', label: 'User', render: (w) => <UserLink id={w.user_id} name={w.user_name || w.user?.name} /> },
          { key: 'balance', label: 'Balance', align: 'right', render: (w) => money(Math.round(Number(w.balance ?? w.wallet_balance ?? 0) * 100)) },
          { key: 'total_earnings', label: 'Earned', align: 'right', render: (w) => (w.total_earnings !== undefined ? money(Math.round(Number(w.total_earnings) * 100)) : '—') },
          { key: 'type', label: 'Type', render: (w) => w.user_type || '—' },
          { key: 'connect', label: 'Stripe Connect', render: (w) => (w.stripe_account_id ? <Badge size="xs" color="green" variant="light">connected</Badge> : '—') },
          { key: 'updated_at', label: 'Updated', render: (w) => <Time value={w.updated_at} /> },
        ]} />
    </>
  );
}

function Tax({ range }) {
  const q = useQuery({ queryKey: ['finance', 'tax', range], queryFn: () => http.get('/admin/finance/tax', range) });
  const t = q.data?.totals || {};
  return (
    <>
      <Group mb="sm" justify="space-between">
        <Text size="sm">Net tax collected: <b>{money(t.net_tax_cents)}</b> on {money(t.taxable_cents)} taxable · {t.receipts ?? 0} receipts</Text>
        <CsvButton url="/admin/finance/tax" params={range} name="tax-by-province" />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={(q.data?.provinces || []).map((r) => ({ id: r.province, ...r }))} minWidth={900} empty="No taxable receipts in range."
        columns={[
          { key: 'province', label: 'Province', render: (r) => `${r.province_name} (${r.province})` }, { key: 'receipts', label: 'Receipts' },
          { key: 'taxable', label: 'Taxable', align: 'right', render: (r) => M(r.taxable_cents) },
          { key: 'gst', label: 'GST', align: 'right', render: (r) => M(r.gst_cents) }, { key: 'hst', label: 'HST', align: 'right', render: (r) => M(r.hst_cents) },
          { key: 'pst', label: 'PST', align: 'right', render: (r) => M(r.pst_cents) }, { key: 'qst', label: 'QST', align: 'right', render: (r) => M(r.qst_cents) },
          { key: 'credited', label: 'Credited', align: 'right', render: (r) => M(r.credited_tax_cents) },
          { key: 'net', label: 'Net tax', align: 'right', render: (r) => <b>{M(r.net_tax_cents)}</b> },
        ]} />
    </>
  );
}

function Statements({ range }) {
  const [week, setWeek] = useState('');
  const { q, pg, setP } = usePaged('statements', '/admin/finance/statements', range);
  return (
    <>
      <Group mb="sm" justify="space-between" align="flex-end">
        <Group gap="xs" align="flex-end">
          <TextInput size="xs" type="date" label="Week starting (Monday)" value={week} onChange={(e) => setWeek(e.currentTarget.value)} />
          <Button size="xs" leftSection={<FiPlay />} onClick={async () => {
            try { await http.post('/admin/finance/statements/run', week ? { week_start: week } : {}); notifyOk('Statement run queued'); } catch (e) { notifyErr(e); }
          }}>Build statements</Button>
        </Group>
        <CsvButton url="/admin/finance/statements" params={range} name="statements" />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={900} empty="No driver statements."
        columns={[
          { key: 'number', label: 'Number', render: (r) => <Text size="sm" ff="monospace">{r.number}</Text> },
          { key: 'driver', label: 'Driver', render: (r) => <UserLink id={r.driver_id} /> }, { key: 'period_start', label: 'Week of' },
          { key: 'gross', label: 'Gross', align: 'right', render: (r) => M(r.gross_cents) }, { key: 'comm', label: 'Commission', align: 'right', render: (r) => M(r.commission_cents) },
          { key: 'net', label: 'Net', align: 'right', render: (r) => M(r.net_cents) }, { key: 'payouts', label: 'Payouts', align: 'right', render: (r) => M(r.payouts_cents) },
          { key: 'x', label: '', render: (r) => <Button size="compact-xs" variant="subtle" onClick={() => openBlob(`/admin/finance/statements/${r.id}/pdf`).catch(notifyErr)}>PDF</Button> },
        ]} />
    </>
  );
}

function Reconciliation({ range }) {
  const [only, setOnly] = useState(false);
  const params = { ...range, only: only ? 'issues' : undefined };
  const { q, pg, setP } = usePaged('recon', '/admin/finance/reconciliation', params);
  const s = q.data?.summary || {};
  return (
    <>
      <SimpleGrid cols={{ base: 2, md: 3, lg: 5 }} spacing="sm" mb="sm">
        <StatCard label="Checked" value={s.checked} hint={`provider: ${s.provider || '—'}`} />
        <StatCard label="OK" value={s.ok} color="green" />
        <StatCard label="Mismatch" value={s.mismatch} color={s.mismatch ? 'orange' : undefined} />
        <StatCard label="Errors" value={s.error} color={s.error ? 'red' : undefined} />
        <StatCard label="DB vs provider captured" value={`${money(s.db_captured_cents)} / ${money(s.provider_captured_cents)}`} />
      </SimpleGrid>
      <Group mb="sm" justify="space-between">
        <Switch size="xs" label="Only rows with issues" checked={only} onChange={(e) => setOnly(e.currentTarget.checked)} />
        <CsvButton url="/admin/finance/reconciliation" params={params} name="reconciliation" />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} rowKey="ride_payment_id" minWidth={1100} empty="No captured payments to reconcile in range."
        highlight={(r) => r.status !== 'ok'}
        columns={[
          { key: 'ride_payment_id', label: 'Payment' }, { key: 'intent_id', label: 'Intent', render: (r) => <Text size="xs" ff="monospace">{r.intent_id}</Text> },
          { key: 'ride', label: 'Ride', render: (r) => <RideLink type={r.ride_type} id={r.ride_id} /> },
          { key: 'dbc', label: 'DB captured', align: 'right', render: (r) => M(r.db_captured_cents) },
          { key: 'pc', label: 'Provider captured', align: 'right', render: (r) => M(r.provider_captured_cents) },
          { key: 'dbr', label: 'DB refunded', align: 'right', render: (r) => M(r.db_refunded_cents) },
          { key: 'pr', label: 'Provider refunded', align: 'right', render: (r) => M(r.provider_refunded_cents) },
          { key: 'receipt', label: 'Receipt', render: (r) => r.receipt_number || '—' },
          { key: 'status', label: 'Status', render: (r) => <StatusBadge value={r.status} /> },
          { key: 'issues', label: 'Issues', render: (r) => <Text size="xs" c="red">{r.issues}</Text> },
        ]} />
    </>
  );
}

function Webhooks() {
  const [provider, setProvider] = useState('');
  const [status, setStatus] = useState('');
  const [p, setP] = useState(1);
  const q = useQuery({ queryKey: ['finance', 'webhooks', provider, status, p], queryFn: () => http.get('/admin/webhook-events', { provider, status, page: p }) });
  const pg = page(q.data);
  return (
    <>
      <Group mb="sm" gap="xs">
        <Select size="xs" placeholder="Provider" clearable value={provider} onChange={(v) => setProvider(v || '')} data={['stripe', 'certn', 'twilio', 'onesignal']} w={150} />
        <Select size="xs" placeholder="Status" clearable value={status} onChange={(v) => setStatus(v || '')} data={['received', 'processed', 'failed', 'ignored']} w={150} />
      </Group>
      <DataTable loading={q.isLoading} error={q.error} rows={pg.items} pageInfo={pg} onPage={setP} minWidth={900} empty="No webhook events."
        columns={[
          { key: 'id', label: '#' }, { key: 'provider', label: 'Provider' }, { key: 'event_type', label: 'Type' },
          { key: 'event_id', label: 'Event ID', render: (r) => <Text size="xs" ff="monospace">{r.event_id}</Text> },
          { key: 'status', label: 'Status', render: (r) => <StatusBadge value={r.status} /> },
          { key: 'signature_valid', label: 'Signature', render: (r) => (r.signature_valid ? 'valid' : <Text c="red" size="sm">invalid</Text>) },
          { key: 'attempts', label: 'Attempts' }, { key: 'error', label: 'Error', render: (r) => <Text size="xs" c="red" lineClamp={2}>{r.error}</Text> },
          { key: 'received_at', label: 'Received', render: (r) => <Time value={r.received_at} /> },
        ]} />
    </>
  );
}

export default function Finance() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') || 'overview';
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const range = { from: from || undefined, to: to || undefined };
  return (
    <>
      <PageHeader title="Payments & Finance" subtitle="All amounts CAD · date filters are UTC days · every view and export is audited"
        actions={<>
          <TextInput size="xs" type="date" label="From" value={from} onChange={(e) => setFrom(e.currentTarget.value)} />
          <TextInput size="xs" type="date" label="To" value={to} onChange={(e) => setTo(e.currentTarget.value)} />
          {(from || to) && <Anchor size="xs" onClick={() => { setFrom(''); setTo(''); }} mt="lg">clear</Anchor>}
        </>} />
      <Tabs value={tab} onChange={(v) => setSp({ tab: v })} keepMounted={false}>
        <Tabs.List mb="sm" style={{ flexWrap: 'wrap' }}>
          {[['overview', 'Overview'], ['payments', 'Payments'], ['auth', 'Authorizations'], ['captures', 'Captures'], ['refunds', 'Refunds'], ['credit', 'Credit notes'],
            ['receipts', 'Receipts'], ['payouts', 'Payouts'], ['wallets', 'Wallets'], ['tax', 'Tax by province'], ['statements', 'Driver statements'],
            ['recon', 'Reconciliation'], ['webhooks', 'Webhooks']].map(([v, l]) => <Tabs.Tab key={v} value={v}>{l}</Tabs.Tab>)}
        </Tabs.List>
        <Tabs.Panel value="overview"><Overview range={range} /></Tabs.Panel>
        <Tabs.Panel value="payments"><Payments range={range} title="all" /></Tabs.Panel>
        <Tabs.Panel value="auth"><Payments range={range} fixed={{ capture_status: 'authorized' }} title="auth" /></Tabs.Panel>
        <Tabs.Panel value="captures"><Payments range={range} fixed={{ capture_status: 'captured' }} title="captured" /></Tabs.Panel>
        <Tabs.Panel value="refunds"><Refunds range={range} /></Tabs.Panel>
        <Tabs.Panel value="credit"><CreditNotes range={range} /></Tabs.Panel>
        <Tabs.Panel value="receipts"><Receipts range={range} /></Tabs.Panel>
        <Tabs.Panel value="payouts"><Payouts range={range} /></Tabs.Panel>
        <Tabs.Panel value="wallets"><Wallets /></Tabs.Panel>
        <Tabs.Panel value="tax"><Tax range={range} /></Tabs.Panel>
        <Tabs.Panel value="statements"><Statements range={range} /></Tabs.Panel>
        <Tabs.Panel value="recon"><Reconciliation range={range} /></Tabs.Panel>
        <Tabs.Panel value="webhooks"><Webhooks /></Tabs.Panel>
      </Tabs>
    </>
  );
}
