import React, { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Button, Card, Checkbox, Grid, Group, Modal, MultiSelect, SegmentedControl, SimpleGrid, Stack, Text, Textarea, TextInput, Timeline,
} from '@mantine/core';
import { FiCheck, FiExternalLink, FiRefreshCw, FiX } from 'react-icons/fi';
import { http } from '../../lib/api';
import { fmt, humanize, money, statusColor } from '../../lib/format';
import { DocThumb, DocZoomModal } from '../../components/DocViewer';
import { ErrorBox, KV, Loading, notifyErr, notifyOk, PageHeader, StatusBadge, UserLink } from '../../components/ui';

const SERVICE_TYPES = ['car_hire', 'rideshare', 'courier', 'movers', 'airport', 'special_car'];

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
  const refresh = () => qc.invalidateQueries({ queryKey: ['onboarding'] });

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

  return (
    <>
      <PageHeader
        title={<Group gap="xs">Application #{a.id} <StatusBadge value={a.status} size="lg" /></Group>}
        subtitle={<>{u ? <UserLink id={u.id} name={`${u.name} · ${u.email || u.phone_number || ''}`} /> : `User #${a.user_id}`} · step {humanize(a.current_step)} · submitted {fmt.dateTime(a.submitted_at)}</>}
        actions={<>
          <Button color="green" leftSection={<FiCheck />} onClick={() => { setDecision('approve'); setTypes(a.service_types || ['car_hire']); setReason(''); setOverride(false); }}>Approve</Button>
          <Button color="orange" variant="light" onClick={() => { setDecision('needs_changes'); setReason(''); }}>Needs changes</Button>
          <Button color="red" variant="light" leftSection={<FiX />} onClick={() => { setDecision('reject'); setReason(''); }}>Reject</Button>
        </>}
      />
      {blockers?.length > 0 && <Alert color="yellow" mb="sm" title="Submit blockers">{blockers.map((b) => (typeof b === 'string' ? b : b.message || JSON.stringify(b))).join(' · ')}</Alert>}
      {a.rejection_reason && <Alert color="red" mb="sm">Last decision reason: {a.rejection_reason}</Alert>}
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
              <Text fw={600} mb="xs">Applicant</Text>
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
              ]} />
            </Card>
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Stack gap="sm">
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
                  <KV cols={2} items={[
                    ['Fee', `${money(b.fee_cents)} · paid by ${b.paid_by}${b.fee_paid_at ? ` · ${fmt.date(b.fee_paid_at)}` : ''}`],
                    ['Provider ID', b.provider_application_id], ['Raw status', b.raw_status],
                    ['Adjudication', b.adjudicated_at ? `${fmt.dateTime(b.adjudicated_at)} — ${b.adjudication_note || ''}` : '—'],
                    ['Expires', fmt.date(b.expires_at)], ['Last polled', fmt.dateTime(b.last_polled_at)],
                  ]} />
                  <Group gap="xs" mt={6}>{(b.timeline || []).map((t) => <Text key={t.event} size="xs" c="dimmed">{humanize(t.event)} {fmt.date(t.at)} ·</Text>)}</Group>
                </Card>
              ))}
              {!bgcs.length && <Text size="sm" c="dimmed">No background check started.</Text>}
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>

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
    </>
  );
}
