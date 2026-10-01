import React, { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Badge, Box, Button, Card, Checkbox, Collapse, Grid, Group, Modal, MultiSelect, NumberInput, Progress, Select, SegmentedControl, SimpleGrid, Stack, Tabs, Text, Textarea, TextInput, Timeline, Tooltip,
} from '@mantine/core';
import { FiAlertTriangle, FiCheck, FiCheckCircle, FiExternalLink, FiRefreshCw, FiShield, FiX } from 'react-icons/fi';
import { http } from '../../lib/api';
import { ago, fmt, humanize, money, statusColor } from '../../lib/format';
import { DocThumb, DocZoomModal } from '../../components/DocViewer';
import UserHistory from '../../components/UserHistory';
import { ErrorBox, Json, KV, Loading, notifyErr, notifyOk, PageHeader, StatusBadge, UserLink } from '../../components/ui';

const SERVICE_TYPES = ['car_hire', 'rideshare', 'courier', 'movers', 'airport', 'special_car'];
const BGC_STATUSES = ['awaiting_payment', 'paid', 'initiated', 'pending', 'clear', 'consider', 'failed', 'cancelled', 'expired'];
const BGC_DATES = [
  ['fee_paid_at', 'Fee paid at'], ['start_after', 'Certn order after'], ['initiated_at', 'Started at'],
  ['completed_at', 'Completed at'], ['expires_at', 'Expires at'], ['last_polled_at', 'Last polled at'],
  ['refunded_at', 'Refunded at'], ['cancelled_at', 'Cancelled at'], ['deduction_settled_at', 'Deduction settled at'],
  ['recheck_reminded_at', 'Recheck reminder sent at'], ['receipt_emailed_at', 'Receipt emailed at'],
  ['adjudicated_at', 'Adjudicated at'],
];
const BGC_STRINGS = [
  ['provider', 'Provider'], ['provider_application_id', 'Provider application ID'], ['package', 'Provider package'],
  ['result', 'Result'], ['raw_status', 'Provider raw status'], ['provider_score', 'Provider score'],
  ['adjudication_note', 'Adjudication note'],
];

function dateTimeLocal(value) {
  if (!value) return '';
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return '';
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function dateTimeIso(value) {
  return value ? new Date(value).toISOString() : null;
}

const FACE_STATUS = {
  match: { color: 'green', label: 'Match', text: 'The provider scored the selfie at or above the threshold. Still compare by eye before approving.' },
  no_match: { color: 'red', label: 'No match', text: 'The provider scored below the threshold — likely a different person or a poor photo. Ask for a new selfie if in doubt.' },
  no_face: { color: 'orange', label: 'No face found', text: 'No face was detected in one of the photos — request a clearer selfie / licence photo.' },
  manual_review: { color: 'blue', label: 'Manual review', text: 'Automatic comparison was not possible — compare the two photos manually.' },
  pending: { color: 'yellow', label: 'Pending', text: 'The comparison has not run yet (it runs after both photos are uploaded).' },
  error: { color: 'red', label: 'Error', text: 'The comparison failed — compare manually.' },
};

/** Selfie vs licence photo side by side with the (advisory) face-match result. Never auto-approves. */
function FaceMatch({ fm, documents, onOpen }) {
  const selfie = documents.find((d) => d.id === fm?.selfie_document_id) || documents.find((d) => d.type === 'selfie' && d.status !== 'superseded');
  const licence = documents.find((d) => d.id === fm?.licence_document_id) || documents.find((d) => d.type === 'licence_front' && d.status !== 'superseded');
  if (!selfie && !licence) return null;
  const st = FACE_STATUS[fm?.status] || (fm?.status ? { color: 'gray', label: humanize(fm.status) } : null);
  const score = fm?.score !== null && fm?.score !== undefined ? Number(fm.score) : null;
  const thr = fm?.threshold ?? null;
  return (
    <Card withBorder radius="md" padding="sm" data-testid="face-match">
      <Group justify="space-between" mb="xs" wrap="wrap">
        <Group gap="xs">
          <Text fw={600}>Identity check — selfie vs licence</Text>
          {st ? <Badge color={st.color} data-testid="face-match-status">{st.label}</Badge> : <Badge color="gray" variant="light">Not run</Badge>}
          {score !== null && <Badge variant="light" color={thr !== null && score >= thr ? 'green' : 'red'}>Score {score.toFixed(1)}{thr !== null ? ` / threshold ${thr}` : ''}</Badge>}
        </Group>
        <Tooltip label="The face-match score only helps the reviewer. Documents and applications are always approved by a person." multiline w={260} withArrow>
          <Badge variant="outline" color="gray" leftSection={<FiShield size={10} />}>Advisory only · never auto-approves</Badge>
        </Tooltip>
      </Group>
      <SimpleGrid cols={2} spacing="sm">
        {[['Selfie', selfie], ['Driver’s licence (front)', licence]].map(([label, d]) => (
          <Box key={label}>
            <Text size="xs" c="dimmed" mb={4}>{label}{d ? ` · #${d.id} · ` : ''}{d && <StatusBadge value={d.status} size="xs" />}</Text>
            {d ? <DocThumb doc={d} h={240} onOpen={() => onOpen(d)} /> : <Box h={240} style={{ borderRadius: 6, background: 'var(--mantine-color-default-hover)', display: 'grid', placeItems: 'center' }}><Text size="sm" c="dimmed">Not uploaded</Text></Box>}
          </Box>
        ))}
      </SimpleGrid>
      {score !== null && <Progress value={Math.max(0, Math.min(100, score))} color={thr !== null && score >= thr ? 'green' : 'red'} size="sm" mt="xs" />}
      <Text size="xs" c="dimmed" mt={6}>
        {st?.text || 'No comparison result yet.'}
        {fm?.provider ? ` Provider: ${fm.provider}.` : ''}{fm?.checked_at ? ` Checked ${fmt.dateTime(fm.checked_at)}.` : ''}
        {fm?.detail ? ` ${fm.detail}` : ''}
      </Text>
    </Card>
  );
}

function Endorsement({ doc, required, province }) {
  const m = doc?.meta || {};
  if (!doc) return required ? <Badge size="xs" color="red" variant="light">endorsement required</Badge> : null;
  if (m.attestation_rideshare_endorsement) {
    return (
      <Tooltip label={`Driver attested the policy includes a rideshare endorsement${m.attested_at ? ` on ${fmt.dateTime(m.attested_at)}` : ''}${m.province ? ` (${m.province})` : ''}. Verify it on the document.`} multiline w={260} withArrow>
        <Badge size="xs" color="green" leftSection={<FiCheckCircle size={9} />} data-testid="endorsement-attested">Endorsement attested</Badge>
      </Tooltip>
    );
  }
  return required
    ? <Badge size="xs" color="red" leftSection={<FiAlertTriangle size={9} />} data-testid="endorsement-missing">Not attested ({province})</Badge>
    : <Badge size="xs" color="gray" variant="light">Endorsement not required</Badge>;
}

function BgcState({ b, renewalDue }) {
  const now = Date.now();
  const startAfter = b.start_after ? Date.parse(b.start_after.endsWith('Z') ? b.start_after : `${b.start_after}Z`) : null;
  const inCancelWindow = b.status === 'paid' && !b.provider_application_id && startAfter && startAfter > now;
  return (
    <Group gap={6} wrap="wrap">
      {b.cancelled_at && <Badge size="xs" color="gray">Cancelled {fmt.date(b.cancelled_at)}</Badge>}
      {Number(b.refunded_cents) > 0 && <Badge size="xs" color="grape">Refunded {money(b.refunded_cents)}{b.refunded_at ? ` · ${fmt.date(b.refunded_at)}` : ''}</Badge>}
      {b.paid_by === 'earnings' && (
        <Badge size="xs" color={b.deduction_status === 'settled' ? 'green' : b.deduction_status === 'waived' ? 'gray' : 'yellow'} variant="light">
          Pay-later: {humanize(b.deduction_status || 'pending')} · recovered {money(b.deducted_cents)} / {money(b.fee_cents)}
        </Badge>
      )}
      {inCancelWindow && <Badge size="xs" color="blue" variant="light">Driver can still cancel (full refund) until {fmt.time(b.start_after)}</Badge>}
      {b.status === 'paid' && !inCancelWindow && !b.provider_application_id && <Badge size="xs" color="orange" variant="light">Awaiting order to Certn</Badge>}
      {renewalDue && <Badge size="xs" color="orange" data-testid="bgc-renewal">Annual re-check due{b.expires_at ? ` · expires ${fmt.date(b.expires_at)}` : ''}</Badge>}
      {!renewalDue && b.status === 'clear' && b.expires_at && <Badge size="xs" color="green" variant="light">Valid until {fmt.date(b.expires_at)} ({ago(b.expires_at)})</Badge>}
      {b.receipt_emailed_at && <Badge size="xs" variant="outline" color="gray">Receipt emailed {fmt.date(b.receipt_emailed_at)}</Badge>}
    </Group>
  );
}

function ConsentEvidence({ ev }) {
  const [open, setOpen] = useState(false);
  return (
    <Box mt={6}>
      <Button size="compact-xs" variant="subtle" onClick={() => setOpen((v) => !v)}>{open ? 'Hide' : 'Show'} consent evidence (e-signature)</Button>
      <Collapse in={open}>
        <KV cols={2} items={[
          ev.signature_name && ['Signed as', ev.signature_name], ev.at && ['Signed at', fmt.dateTimeSec(ev.at)],
          ev.ip && ['IP', ev.ip], ev.document && ['Document', typeof ev.document === 'object' ? `${ev.document.type || ''} v${ev.document.version || ''}` : ev.document],
        ]} />
        <Json value={ev} maxH={160} />
      </Collapse>
    </Box>
  );
}

export default function ApplicationDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['onboarding', 'app', id], queryFn: () => http.get(`/admin/onboarding/applications/${id}`) });
  const [doc, setDoc] = useState(null);
  const [docNote, setDocNote] = useState('');
  const [docExpiry, setDocExpiry] = useState('');
  const [decision, setDecision] = useState(null);
  const [reason, setReason] = useState('');
  const [types, setTypes] = useState(null);
  const [override, setOverride] = useState(false);
  const [adj, setAdj] = useState(null);
  const [busy, setBusy] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState(null);
  const [editReason, setEditReason] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const [bgcEdit, setBgcEdit] = useState(null);
  const [bgcEditReason, setBgcEditReason] = useState('');
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['onboarding', 'app', id] });
    qc.invalidateQueries({ queryKey: ['onboarding', 'apps'] });
    qc.invalidateQueries({ queryKey: ['onboarding', 'funnel'] });
  };

  const review = async (d, dec) => {
    setBusy(`doc-${dec}`);
    try {
      await http.post(`/admin/onboarding/documents/${d.id}/review`, { decision: dec, note: docNote || undefined, expires_at: docExpiry || undefined });
      notifyOk(`${d.title} ${dec === 'approve' ? 'approved' : 'rejected'}`);
      setDoc(null); setDocNote(''); setDocExpiry('');
      refresh();
    } catch (e) { notifyErr(e); } finally { setBusy(null); }
  };

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const { application: a, user: u, steps, submit_blockers: blockers, documents, background_checks: bgcs } = q.data;
  const current = documents.filter((d) => d.status !== 'superseded');
  const old = documents.filter((d) => d.status === 'superseded');
  const fm = q.data.face_match;
  const endorsementRequired = !!q.data.insurance_endorsement_required;
  const renewalDue = !!q.data.renewal_due;
  const insurance = current.find((d) => d.type === 'insurance');
  const province = a.province || u?.province;

  const openEditor = () => {
    setEditForm({
      legal_first_name: a.legal_first_name || '', legal_last_name: a.legal_last_name || '',
      date_of_birth: a.date_of_birth || '', address_line: a.address_line || '', city: a.city || '',
      province: a.province || '', postal_code: a.postal_code || '', service_types: a.service_types || [],
      licence_class: a.licence_class || '', licence_number: a.licence_number || '',
      licence_expires_at: a.licence_expires_at || '', vehicle_make: a.vehicle_make || '',
      vehicle_model: a.vehicle_model || '', vehicle_year: a.vehicle_year ?? '',
      vehicle_color: a.vehicle_color || '', vehicle_plate: a.vehicle_plate || '',
      vehicle_seats: a.vehicle_seats ?? '',
    });
    setEditReason('');
    setEditOpen(true);
  };

  const saveApplication = async () => {
    if (!editForm || editReason.trim().length < 5) return;
    const changes = {};
    Object.entries(editForm).forEach(([key, value]) => {
      const original = a[key] ?? (Array.isArray(value) ? [] : '');
      if (Array.isArray(value) ? JSON.stringify(value) !== JSON.stringify(original) : String(value) !== String(original)) {
        changes[key] = key === 'vehicle_year' || key === 'vehicle_seats'
          ? (value === '' ? null : Number(value)) : value;
      }
    });
    setSavingProfile(true);
    try {
      const result = await http.put(`/admin/onboarding/applications/${a.id}/profile`, {
        changes, reason_text: editReason.trim(),
      });
      notifyOk(result.message || 'Application details saved.');
      setEditOpen(false);
      refresh();
    } catch (e) {
      notifyErr(e, 'Could not save applicant details');
    } finally {
      setSavingProfile(false);
    }
  };

  const openBgcEditor = (b) => {
    const values = {};
    BGC_STRINGS.forEach(([key]) => { values[key] = b[key] ?? ''; });
    BGC_DATES.forEach(([key]) => { values[key] = dateTimeLocal(b[key]); });
    values.status = b.status || 'awaiting_payment';
    values.paid_by = b.paid_by || 'driver';
    values.deduction_status = b.deduction_status || '';
    values.fee_cents = Number(b.fee_cents) || 0;
    values.refunded_cents = Number(b.refunded_cents) || 0;
    values.deducted_cents = Number(b.deducted_cents) || 0;
    setBgcEdit({ id: b.id, values });
    setBgcEditReason('');
  };

  const saveBgcRecord = async () => {
    if (!bgcEdit || bgcEditReason.trim().length < 5) return;
    const values = bgcEdit.values;
    const changes = {};
    BGC_STRINGS.forEach(([key]) => { changes[key] = values[key].trim() || null; });
    BGC_DATES.forEach(([key]) => { changes[key] = dateTimeIso(values[key]); });
    changes.status = values.status;
    changes.paid_by = values.paid_by;
    changes.deduction_status = values.deduction_status || null;
    changes.fee_cents = Number(values.fee_cents);
    changes.refunded_cents = Number(values.refunded_cents);
    changes.deducted_cents = Number(values.deducted_cents);
    setBusy('bgc-edit');
    try {
      await http.patch(`/admin/onboarding/background-checks/${bgcEdit.id}/record`, {
        changes, reason: bgcEditReason.trim(),
      });
      notifyOk('Background-check record updated.');
      setBgcEdit(null);
      refresh();
    } catch (e) {
      notifyErr(e, 'Could not update background-check record');
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        title={<Group gap="xs">Application #{a.id} <StatusBadge value={a.status} size="lg" /></Group>}
        subtitle={<>{u ? <UserLink id={u.id} name={`${u.name} · ${u.email || u.phone_number || ''}`} /> : `User #${a.user_id}`} · step {humanize(a.current_step)} · submitted {fmt.dateTime(a.submitted_at)}</>}
        actions={<>
          <Button variant="default" onClick={openEditor}>Edit applicant details</Button>
          <Button color="green" leftSection={<FiCheck />} onClick={() => { setDecision('approve'); setTypes(a.service_types || ['car_hire']); setReason(''); setOverride(false); }}>Approve</Button>
          <Button color="orange" variant="light" onClick={() => { setDecision('needs_changes'); setReason(''); }}>Needs changes</Button>
          <Button color="red" variant="light" leftSection={<FiX />} onClick={() => { setDecision('reject'); setReason(''); }}>Reject</Button>
        </>}
      />
      {blockers?.length > 0 && <Alert color="yellow" mb="sm" title="Submit blockers">{blockers.map((b) => (typeof b === 'string' ? b : b.message || JSON.stringify(b))).join(' · ')}</Alert>}
      {a.rejection_reason && <Alert color="red" mb="sm">Last decision reason: {a.rejection_reason}</Alert>}
      {fm?.status === 'no_match' && <Alert color="red" mb="sm" icon={<FiAlertTriangle />} title="Face match: no match">The selfie did not match the licence photo (score {fm.score ?? '—'} &lt; {fm.threshold}). Compare the photos before approving — the score never approves or rejects on its own.</Alert>}
      {endorsementRequired && !insurance?.meta?.attestation_rideshare_endorsement && (
        <Alert color="orange" mb="sm" icon={<FiAlertTriangle />}>Insurance in {province} must include a rideshare endorsement — {insurance ? 'the uploaded policy was not attested.' : 'no insurance uploaded yet.'}</Alert>
      )}
      {renewalDue && <Alert color="orange" mb="sm" icon={<FiRefreshCw />}>Annual background re-check is due — the driver is prompted to start (and pay for) a new check.</Alert>}
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Stack gap="sm">
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Steps</Text>
              <Timeline bulletSize={16} lineWidth={2}>
                {steps.map((s) => (
                  <Timeline.Item key={s.key} color={statusColor(s.status === 'done' ? 'approved' : s.status === 'action_needed' ? 'rejected' : s.status === 'in_progress' || s.status === 'under_review' ? 'pending' : 'draft')}
                    title={<Text size="sm">{s.number ? `${s.number}. ` : ''}{s.title}</Text>}>
                    <Text size="xs" c="dimmed">{humanize(s.status)}</Text>
                  </Timeline.Item>
                ))}
              </Timeline>
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Group justify="space-between" mb="xs">
                <Text fw={600}>Applicant details</Text>
                <Button size="compact-xs" variant="subtle" onClick={openEditor}>Edit details</Button>
              </Group>
              <KV items={[
                ['Legal name', `${a.legal_first_name || ''} ${a.legal_last_name || ''}`.trim() || '—'], ['Date of birth', a.date_of_birth],
                ['Address', [a.address_line, a.city, a.province, a.postal_code].filter(Boolean).join(', ')],
                ['Service types', (a.service_types || []).map(humanize).join(', ')],
                ['Licence', `${a.licence_class || ''} ${a.licence_number || ''} · exp ${a.licence_expires_at || '—'}`],
                ['Vehicle', [a.vehicle_year, a.vehicle_make, a.vehicle_model, a.vehicle_color].filter(Boolean).join(' ')],
                ['Plate / seats', `${a.vehicle_plate || '—'} / ${a.vehicle_seats || '—'}`],
                ['Pre-qualification', a.prequal ? (a.prequal.passed ? 'Passed' : `Failed: ${(a.prequal.reasons || []).join(', ')}`) : '—'],
                ['Pay later', a.pay_later_from_earnings ? 'Yes (fee from earnings)' : 'No'],
                ['Orientation', a.orientation_completed_at ? `Done · score ${a.orientation_score}` : '—'],
                ['Phone verified', u?.phone_verified_at ? fmt.dateTime(u.phone_verified_at) : 'No'],
                ['Insurance endorsement', <Group gap={4}>{endorsementRequired ? `Required in ${province}` : 'Not required'} <Endorsement doc={insurance} required={endorsementRequired} province={province} /></Group>],
                ['Face match', fm ? <StatusBadge value={FACE_STATUS[fm.status]?.label || fm.status} /> : '—'],
              ]} />
            </Card>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Stack gap="sm">
            <FaceMatch fm={fm} documents={documents} onOpen={(d) => { setDoc(d); setDocNote(d.reviewer_note || ''); setDocExpiry(d.expires_at || ''); }} />
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Documents — click to zoom, approve or reject each one</Text>
              <SimpleGrid cols={{ base: 2, sm: 3, lg: 4 }} spacing="sm">
                {current.map((d) => (
                  <Card key={d.id} withBorder padding="xs" radius="md">
                    <DocThumb doc={d} onOpen={() => { setDoc(d); setDocNote(d.reviewer_note || ''); setDocExpiry(d.expires_at || ''); }} />
                    <Text size="sm" fw={500} mt={4} truncate>{d.title}</Text>
                    <Group gap={4} justify="space-between">
                      <StatusBadge value={d.status} size="xs" />
                      {d.expires_at && <Text size="xs" c="dimmed">exp {d.expires_at}</Text>}
                    </Group>
                    {d.type === 'insurance' && <Box mt={4}><Endorsement doc={d} required={endorsementRequired} province={province} /></Box>}
                    {d.type === 'selfie' && d.face_match_status && <Box mt={4}><Badge size="xs" color={FACE_STATUS[d.face_match_status]?.color || 'gray'}>Face {FACE_STATUS[d.face_match_status]?.label || d.face_match_status}{d.face_match_score !== null && d.face_match_score !== undefined ? ` · ${Number(d.face_match_score).toFixed(0)}` : ''}</Badge></Box>}
                    {d.status === 'pending' && (
                      <Group gap={4} mt={4} grow>
                        <Button size="compact-xs" color="green" variant="light" loading={busy === 'doc-approve'} onClick={() => review(d, 'approve')}>Approve</Button>
                        <Button size="compact-xs" color="red" variant="light" onClick={() => { setDoc(d); setDocNote(''); }}>Reject…</Button>
                      </Group>
                    )}
                  </Card>
                ))}
              </SimpleGrid>
              {!current.length && <Text size="sm" c="dimmed">No documents uploaded yet.</Text>}
              {old.length > 0 && <Text size="xs" c="dimmed" mt="xs">{old.length} superseded upload(s) hidden.</Text>}
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Background checks (Certn)</Text>
              {bgcs.map((b) => (
                <Card key={b.id} withBorder padding="sm" mb="xs">
                  <Group justify="space-between" wrap="wrap">
                    <Group gap="xs"><Text fw={500}>#{b.id}</Text><StatusBadge value={b.status} />{b.result && <StatusBadge value={b.result} />}<Text size="xs" c="dimmed">{b.package}</Text></Group>
                    <Group gap="xs">
                      <Button size="compact-xs" variant="default" onClick={() => openBgcEditor(b)}>Edit record</Button>
                      <Button size="compact-xs" variant="default" leftSection={<FiRefreshCw />} loading={busy === `r${b.id}`} onClick={async () => {
                        setBusy(`r${b.id}`);
                        try { await http.post(`/admin/onboarding/background-checks/${b.id}/refresh`); notifyOk('Refreshed from Certn'); refresh(); } catch (e) { notifyErr(e); } finally { setBusy(null); }
                      }}>Refresh</Button>
                      <Button size="compact-xs" variant="default" leftSection={<FiExternalLink />} loading={busy === `p${b.id}`} onClick={async () => {
                        setBusy(`p${b.id}`);
                        try { const r = await http.get(`/admin/onboarding/background-checks/${b.id}/report`); window.open(r.url, '_blank', 'noopener'); } catch (e) { notifyErr(e, 'Report unavailable'); } finally { setBusy(null); }
                      }}>Report</Button>
                      {['consider', 'pending', 'initiated', 'clear', 'failed'].includes(b.status) && (
                        <Button size="compact-xs" color="orange" variant="light" onClick={() => setAdj({ b, decision: 'clear', note: '' })}>Adjudicate…</Button>
                      )}
                    </Group>
                  </Group>
                  <BgcState b={b} renewalDue={renewalDue && b.id === bgcs[0]?.id} />
                  <KV cols={2} items={[
                    ['Fee', `${money(b.fee_cents)} · ${b.fee_paid_at || ['paid', 'initiated', 'pending', 'clear', 'consider', 'failed', 'expired'].includes(b.status) ? `payment recorded · ${b.paid_by}` : `payment not recorded · ${b.paid_by}`}${b.fee_paid_at ? ` · ${fmt.date(b.fee_paid_at)}` : ''}`],
                    ['Provider ID', b.provider_application_id], ['Raw status', b.raw_status],
                    ['Certn score', b.provider_score || '—'],
                    ['Adjudication', b.adjudicated_at ? `${fmt.dateTime(b.adjudicated_at)} — ${b.adjudication_note || ''}` : '—'],
                    ['Ordered after', b.start_after ? fmt.dateTime(b.start_after) : '—'],
                    ['Expires', fmt.date(b.expires_at)], ['Last polled', fmt.dateTime(b.last_polled_at)],
                    ['Refund', Number(b.refunded_cents) ? `${money(b.refunded_cents)} · ${fmt.dateTime(b.refunded_at)}` : 'none'],
                    ['Cancelled', b.cancelled_at ? fmt.dateTime(b.cancelled_at) : '—'],
                  ]} />
                  <Group gap="xs" mt={6}>{(b.timeline || []).map((t) => <Text key={t.event} size="xs" c="dimmed">{humanize(t.event)} {fmt.date(t.at)} ·</Text>)}{b.typical_turnaround && <Text size="xs" c="dimmed">{b.typical_turnaround}</Text>}</Group>
                  {b.consent_evidence && <ConsentEvidence ev={b.consent_evidence} />}
                </Card>
              ))}
              {!bgcs.length && <Text size="sm" c="dimmed">No background check started.</Text>}
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Applicant history (onboarding, background checks, safety, support, account)</Text>
              <UserHistory id={a.user_id} />
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>

      <Modal
        opened={editOpen}
        onClose={() => { if (!savingProfile) setEditOpen(false); }}
        title={`Edit application #${a.id}`}
        size="1000px"
        centered
        closeOnClickOutside={!savingProfile}
        closeOnEscape={!savingProfile}
        styles={{ content: { maxHeight: 'min(90vh, 980px)', display: 'flex', flexDirection: 'column' }, body: { overflowY: 'auto' } }}
      >
        {editForm && (
          <Stack gap="md">
            <Alert color="blue" variant="light">
              Correct the applicant’s submitted details in one place. Contact verification, consent evidence, document review, background checks and final decisions stay in their audited workflows.
            </Alert>
            <Card withBorder radius="md" padding="md">
              <Text fw={600} mb="sm">Identity and address</Text>
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                <TextInput label="Legal first name" value={editForm.legal_first_name} onChange={(e) => setEditForm({ ...editForm, legal_first_name: e.currentTarget.value })} maxLength={100} />
                <TextInput label="Legal last name" value={editForm.legal_last_name} onChange={(e) => setEditForm({ ...editForm, legal_last_name: e.currentTarget.value })} maxLength={100} />
                <TextInput type="date" label="Date of birth" value={editForm.date_of_birth} onChange={(e) => setEditForm({ ...editForm, date_of_birth: e.currentTarget.value })} />
                <TextInput label="Street address" value={editForm.address_line} onChange={(e) => setEditForm({ ...editForm, address_line: e.currentTarget.value })} maxLength={255} />
                <TextInput label="City" value={editForm.city} onChange={(e) => setEditForm({ ...editForm, city: e.currentTarget.value })} maxLength={100} />
                <Select
                  label="Province or territory"
                  value={editForm.province || null}
                  onChange={(value) => setEditForm({ ...editForm, province: value || '' })}
                  data={['AB','BC','MB','NB','NL','NS','NT','NU','ON','PE','QC','SK','YT'].map((value) => ({ value, label: value }))}
                  searchable
                />
                <TextInput label="Postal code" value={editForm.postal_code} onChange={(e) => setEditForm({ ...editForm, postal_code: e.currentTarget.value.toUpperCase() })} maxLength={10} />
              </SimpleGrid>
            </Card>
            <Card withBorder radius="md" padding="md">
              <Text fw={600} mb="sm">Services and driver’s licence</Text>
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                <MultiSelect
                  label="Services requested"
                  description="Select every service this driver is applying to provide."
                  data={[...new Set([...(q.data.available_service_types || SERVICE_TYPES), ...(editForm.service_types || [])])].map((value) => ({ value, label: humanize(value) }))}
                  value={editForm.service_types}
                  onChange={(value) => setEditForm({ ...editForm, service_types: value })}
                  searchable
                />
                <TextInput label="Licence class" value={editForm.licence_class} onChange={(e) => setEditForm({ ...editForm, licence_class: e.currentTarget.value.toUpperCase() })} maxLength={10} />
                <TextInput label="Licence number" value={editForm.licence_number} onChange={(e) => setEditForm({ ...editForm, licence_number: e.currentTarget.value })} maxLength={60} />
                <TextInput type="date" label="Licence expiry" value={editForm.licence_expires_at} onChange={(e) => setEditForm({ ...editForm, licence_expires_at: e.currentTarget.value })} />
              </SimpleGrid>
            </Card>
            <Card withBorder radius="md" padding="md">
              <Text fw={600} mb="sm">Vehicle details</Text>
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                <TextInput label="Make" value={editForm.vehicle_make} onChange={(e) => setEditForm({ ...editForm, vehicle_make: e.currentTarget.value })} maxLength={60} />
                <TextInput label="Model" value={editForm.vehicle_model} onChange={(e) => setEditForm({ ...editForm, vehicle_model: e.currentTarget.value })} maxLength={60} />
                <TextInput type="number" label="Model year" value={editForm.vehicle_year} onChange={(e) => setEditForm({ ...editForm, vehicle_year: e.currentTarget.value })} min={1900} max={new Date().getFullYear() + 1} />
                <TextInput label="Color" value={editForm.vehicle_color} onChange={(e) => setEditForm({ ...editForm, vehicle_color: e.currentTarget.value })} maxLength={40} />
                <TextInput label="Licence plate" value={editForm.vehicle_plate} onChange={(e) => setEditForm({ ...editForm, vehicle_plate: e.currentTarget.value.toUpperCase() })} maxLength={20} />
                <TextInput type="number" label="Passenger seats" description="Optional · 1 to 14" value={editForm.vehicle_seats} onChange={(e) => setEditForm({ ...editForm, vehicle_seats: e.currentTarget.value })} min={1} max={14} />
              </SimpleGrid>
            </Card>
            <Textarea
              label="Reason for correction"
              description="Required for the audit history (at least 5 characters)."
              placeholder="For example: corrected from the driver’s updated licence"
              value={editReason}
              onChange={(e) => setEditReason(e.currentTarget.value)}
              minRows={2}
              maxLength={500}
              required
            />
            <Group justify="space-between">
              <Text size="xs" c="dimmed">Email, phone and verification are managed from the linked user profile.</Text>
              <Group>
                <Button variant="default" disabled={savingProfile} onClick={() => setEditOpen(false)}>Cancel</Button>
                <Button loading={savingProfile} disabled={editReason.trim().length < 5} onClick={saveApplication}>Save changes</Button>
              </Group>
            </Group>
          </Stack>
        )}
      </Modal>

      <DocZoomModal
        doc={doc} opened={!!doc} onClose={() => setDoc(null)}
        footer={doc && (
          <Stack mt="sm" gap="xs">
            <Group grow>
              <Textarea label="Reviewer note (required to reject — the driver sees it)" value={docNote} onChange={(e) => setDocNote(e.currentTarget.value)} autosize minRows={1} />
              <TextInput type="date" label="Expiry date" value={docExpiry || ''} onChange={(e) => setDocExpiry(e.currentTarget.value)} />
            </Group>
            <Group justify="flex-end">
              <StatusBadge value={doc.status} />
              <Button color="red" variant="light" disabled={!docNote.trim()} loading={busy === 'doc-reject'} onClick={() => review(doc, 'reject')}>Reject</Button>
              <Button color="green" loading={busy === 'doc-approve'} onClick={() => review(doc, 'approve')}>Approve</Button>
            </Group>
          </Stack>
        )}
      />

      <Modal opened={!!decision} onClose={() => setDecision(null)} title={`${humanize(decision)} application #${a.id}`} centered>
        <Stack>
          {decision === 'approve' && (
            <>
              <MultiSelect label="Approved service types" data={SERVICE_TYPES.map((s) => ({ value: s, label: humanize(s) }))} value={types || []} onChange={setTypes} />
              <Checkbox label="Approve without a clear background check (reason required)" checked={override} onChange={(e) => setOverride(e.currentTarget.checked)} />
            </>
          )}
          <Textarea label={decision === 'approve' ? 'Reason / note' : 'Reason (sent to the driver)'} required={decision !== 'approve' || override} value={reason} onChange={(e) => setReason(e.currentTarget.value)} autosize minRows={2} />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDecision(null)}>Cancel</Button>
            <Button color={decision === 'approve' ? 'green' : decision === 'reject' ? 'red' : 'orange'} loading={busy === 'decide'}
              disabled={(decision !== 'approve' || override) && !reason.trim()}
              onClick={async () => {
                setBusy('decide');
                try {
                  const r = await http.postFull(`/admin/onboarding/applications/${a.id}/decision`, { decision, reason: reason || undefined, service_types: decision === 'approve' ? types : undefined, override_background_check: override });
                  notifyOk(r.message); setDecision(null); refresh();
                } catch (e) { notifyErr(e, 'Decision failed'); } finally { setBusy(null); }
              }}>Confirm</Button>
          </Group>
        </Stack>
      </Modal>

      <Modal opened={!!adj} onClose={() => setAdj(null)} title={`Adjudicate check #${adj?.b.id}`} centered>
        {adj && (
          <Stack>
            <SegmentedControl value={adj.decision} onChange={(v) => setAdj({ ...adj, decision: v })} data={[{ value: 'clear', label: 'Clear' }, { value: 'failed', label: 'Failed' }]} />
            <Textarea label="Reason" required value={adj.note} onChange={(e) => setAdj({ ...adj, note: e.currentTarget.value })} />
            <Group justify="flex-end">
              <Button disabled={!adj.note.trim()} loading={busy === 'adj'} onClick={async () => {
                setBusy('adj');
                try { await http.post(`/admin/onboarding/background-checks/${adj.b.id}/adjudicate`, { decision: adj.decision, note: adj.note }); notifyOk('Decision recorded'); setAdj(null); refresh(); } catch (e) { notifyErr(e); } finally { setBusy(null); }
              }}>Save decision</Button>
            </Group>
          </Stack>
        )}
      </Modal>

      <Modal
        opened={!!bgcEdit}
        onClose={() => { if (busy !== 'bgc-edit') setBgcEdit(null); }}
        title={`Edit background-check record #${bgcEdit?.id}`}
        size="1000px"
        centered
        closeOnClickOutside={busy !== 'bgc-edit'}
        closeOnEscape={busy !== 'bgc-edit'}
      >
        {bgcEdit && (
          <Stack>
            <Alert color="yellow" title="Record correction">
              Saves audited NegoRide record values. It does not charge or refund a card, change signed consent,
              contact Certn, or change the payment-provider ledger. Use Refresh for Certn updates and Adjudicate
              for a reviewed result.
            </Alert>
            <Grid gutter="sm">
              <Grid.Col span={{ base: 12, sm: 6 }}>
                <Select
                  label="Background-check status"
                  value={bgcEdit.values.status}
                  onChange={(value) => setBgcEdit({ ...bgcEdit, values: { ...bgcEdit.values, status: value || '' } })}
                  data={BGC_STATUSES.map((value) => ({ value, label: humanize(value) }))}
                  allowDeselect={false}
                  required
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6 }}>
                <Select
                  label="Paid by"
                  value={bgcEdit.values.paid_by}
                  onChange={(value) => setBgcEdit({ ...bgcEdit, values: { ...bgcEdit.values, paid_by: value || '' } })}
                  data={['driver', 'platform', 'earnings'].map((value) => ({ value, label: humanize(value) }))}
                  allowDeselect={false}
                  required
                />
              </Grid.Col>
              {BGC_STRINGS.map(([key, label]) => (
                <Grid.Col key={key} span={{ base: 12, sm: key === 'adjudication_note' || key === 'raw_status' ? 12 : 6 }}>
                  <TextInput
                    label={label}
                    value={bgcEdit.values[key]}
                    onChange={(event) => setBgcEdit({ ...bgcEdit, values: { ...bgcEdit.values, [key]: event.currentTarget.value } })}
                    maxLength={key === 'adjudication_note' ? 4000 : undefined}
                  />
                </Grid.Col>
              ))}
              <Grid.Col span={{ base: 12, sm: 4 }}>
                <NumberInput label="Fee (cents)" min={0} allowDecimal={false} value={bgcEdit.values.fee_cents}
                  onChange={(value) => setBgcEdit({ ...bgcEdit, values: { ...bgcEdit.values, fee_cents: value ?? 0 } })} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 4 }}>
                <NumberInput label="Refund recorded (cents)" min={0} allowDecimal={false} value={bgcEdit.values.refunded_cents}
                  onChange={(value) => setBgcEdit({ ...bgcEdit, values: { ...bgcEdit.values, refunded_cents: value ?? 0 } })} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 4 }}>
                <NumberInput label="Earnings deducted (cents)" min={0} allowDecimal={false} value={bgcEdit.values.deducted_cents}
                  onChange={(value) => setBgcEdit({ ...bgcEdit, values: { ...bgcEdit.values, deducted_cents: value ?? 0 } })} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6 }}>
                <Select
                  label="Earnings deduction status"
                  value={bgcEdit.values.deduction_status || null}
                  onChange={(value) => setBgcEdit({ ...bgcEdit, values: { ...bgcEdit.values, deduction_status: value || '' } })}
                  data={['pending', 'settled', 'waived'].map((value) => ({ value, label: humanize(value) }))}
                  clearable
                />
              </Grid.Col>
              {BGC_DATES.map(([key, label]) => (
                <Grid.Col key={key} span={{ base: 12, sm: 6 }}>
                  <TextInput
                    type="datetime-local"
                    label={label}
                    value={bgcEdit.values[key]}
                    onChange={(event) => setBgcEdit({ ...bgcEdit, values: { ...bgcEdit.values, [key]: event.currentTarget.value } })}
                  />
                </Grid.Col>
              ))}
            </Grid>
            <Text size="xs" c="dimmed">
              Payment record link: {bgcs.find((check) => check.id === bgcEdit.id)?.fee_payment_id || 'none'} ·
              consent evidence is preserved and cannot be edited here.
            </Text>
            <Textarea
              label="Reason for correction"
              description="Required for the audit history."
              required
              minRows={2}
              value={bgcEditReason}
              onChange={(event) => setBgcEditReason(event.currentTarget.value)}
            />
            <Group justify="flex-end">
              <Button variant="default" disabled={busy === 'bgc-edit'} onClick={() => setBgcEdit(null)}>Cancel</Button>
              <Button loading={busy === 'bgc-edit'} disabled={bgcEditReason.trim().length < 5} onClick={saveBgcRecord}>
                Save record
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}
