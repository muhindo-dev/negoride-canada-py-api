import React, { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Alert, Anchor, Badge, Button, Card, Grid, Group, Modal, ScrollArea, Stack, Text, Textarea, Timeline,
} from '@mantine/core';
import { FiCheck, FiDownload, FiPhone, FiSlash, FiShield } from 'react-icons/fi';
import { http, openBlob } from '../../lib/api';
import { ago, fmt, humanize, statusColor } from '../../lib/format';
import { useRealtime } from '../../lib/realtime';
import { useRoles } from '../../lib/roles';
import MapView from '../../components/map/MapView';
import {
  ErrorBox, KV, Loading, notifyErr, notifyOk, PageHeader, RideLink, StageBadge, StatusBadge, UserLink,
} from '../../components/ui';

function ContactModal({ id, opened, onClose }) {
  const q = useQuery({ queryKey: ['safety', 'contact', id], queryFn: () => http.get(`/admin/safety/incidents/${id}/contact`), enabled: opened, staleTime: 0 });
  return (
    <Modal opened={opened} onClose={onClose} title="One-click call" centered>
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : (
        <Stack gap="xs">
          <Text size="xs" c="dimmed">Access to phone numbers is written to the audit log.</Text>
          {(q.data?.people || []).map((p) => (
            <Group key={p.user_id} justify="space-between">
              <div>
                <Text size="sm" fw={500}>{p.name || `User #${p.user_id}`}</Text>
                <Text size="xs" c="dimmed">{humanize(p.relation)}{p.role ? ` · ${p.role}` : ''}</Text>
              </div>
              {p.phone ? <Button component="a" href={`tel:${p.phone}`} size="xs" leftSection={<FiPhone />}>{p.phone}</Button> : <Text size="xs" c="dimmed">no phone</Text>}
            </Group>
          ))}
          <Button component="a" href={`tel:${q.data?.emergency_number || '911'}`} color="red" leftSection={<FiPhone />} mt="sm">Call {q.data?.emergency_number || '911'}</Button>
        </Stack>
      )}
    </Modal>
  );
}

export default function IncidentDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { can } = useRoles();
  const q = useQuery({
    queryKey: ['safety', 'incident', id],
    queryFn: () => http.get(`/admin/safety/incidents/${id}`),
    refetchInterval: (query) => (query.state.data?.is_open ? 5000 : false),
  });
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(null);
  const [contact, setContact] = useState(false);
  useRealtime('safety.sos_updated', (p) => {
    if (String(p?.incident_id) === String(id)) qc.invalidateQueries({ queryKey: ['safety', 'incident', id] });
  });

  const act = async (what, body) => {
    setBusy(what);
    try {
      await http.post(`/admin/safety/incidents/${id}/${what}`, body || (note ? { note } : {}));
      notifyOk(what === 'notes' ? 'Note added' : `Incident ${humanize(what)}`);
      setNote('');
      qc.invalidateQueries({ queryKey: ['safety'] });
      qc.invalidateQueries({ queryKey: ['command-center'] });
    } catch (e) { notifyErr(e); } finally { setBusy(null); }
  };

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const i = q.data;
  const trail = (i.locations || []).map((l) => [l.lat, l.lng]);
  const last = i.last_lat !== null && i.last_lat !== undefined ? [i.last_lat, i.last_lng] : (i.lat !== null ? [i.lat, i.lng] : null);
  const markers = [
    i.lat !== null && { id: 'first', lat: i.lat, lng: i.lng, color: '#fab005', radius: 7, label: `SOS raised · ${fmt.time(i.created_at)}` },
    last && { id: 'last', lat: last[0], lng: last[1], color: '#e03131', radius: 11, ring: '#000', label: `Last position · ${ago(i.last_location_at || i.created_at)}` },
  ].filter(Boolean);
  const accuracy = last && i.accuracy_m ? [{ id: 'acc', lat: last[0], lng: last[1], radiusM: i.accuracy_m, color: '#e03131', fillOpacity: 0.12 }] : [];

  return (
    <>
      <PageHeader
        title={<Group gap="xs"><FiShield /> Incident #{i.id} <StatusBadge value={i.status} size="lg" variant={i.status === 'open' ? 'filled' : 'light'} /></Group>}
        subtitle={`${humanize(i.kind)} · ${humanize(i.severity)} severity · raised ${ago(i.created_at)} (${fmt.dateTimeSec(i.created_at)})`}
        actions={<>
          <Button leftSection={<FiPhone />} variant="light" onClick={() => setContact(true)}>Call</Button>
          <Button leftSection={<FiDownload />} variant="default" loading={busy === 'pdf'} onClick={async () => {
            setBusy('pdf');
            try { await openBlob(`/admin/safety/incidents/${i.id}/report.pdf`); } catch (e) { notifyErr(e, 'PDF export failed'); } finally { setBusy(null); }
          }}>PDF report</Button>
        </>}
      />
      {i.status === 'open' && (
        <Alert color="red" variant="filled" mb="sm" title="Not acknowledged yet">
          Acknowledge to stop the alarm and tell the user help is on the way. Escalation to on-call phones happens automatically if nobody acknowledges.
        </Alert>
      )}
      <Grid gutter="sm">
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Card withBorder radius="md" padding="sm">
            <Group justify="space-between" mb="xs">
              <Text fw={600}>Live location {i.is_open && <Badge ml={6} size="xs" color="red" variant="dot">tracking every few seconds</Badge>}</Text>
              <Text size="xs" c="dimmed">{trail.length} points · last {ago(i.last_location_at || i.created_at)}</Text>
            </Group>
            <MapView
              height={380}
              markers={markers}
              circles={accuracy}
              polylines={trail.length > 1 ? [{ id: 'trail', points: trail, color: '#e03131', weight: 4 }] : []}
              fitKey={`inc-${i.id}`}
              follow={i.is_open && last ? last : null}
            />
            {last && <Text size="xs" mt={6} ff="monospace">{Number(last[0]).toFixed(6)}, {Number(last[1]).toFixed(6)} {i.accuracy_m ? `±${i.accuracy_m} m` : ''} {i.battery_pct ? `· battery ${i.battery_pct}%` : ''}</Text>}
          </Card>
          <Card withBorder radius="md" padding="sm" mt="sm">
            <Text fw={600} mb="xs">Timeline</Text>
            <ScrollArea.Autosize mah={360}>
              <Timeline bulletSize={14} lineWidth={2}>
                {(i.timeline || []).map((t, k) => (
                  <Timeline.Item key={k} color={t.type === 'incident' ? 'red' : t.type === 'audit' ? 'gray' : t.type === 'safety_check' ? 'orange' : 'violet'}
                    title={<Text size="sm">{t.type === 'audit' ? humanize(t.label) : t.label}</Text>}>
                    <Text size="xs" c="dimmed">{fmt.dateTimeSec(t.at)} · {humanize(t.type)}{t.actor_type ? ` · ${t.actor_type}` : ''}{t.actor_id ? ` #${t.actor_id}` : ''}</Text>
                  </Timeline.Item>
                ))}
              </Timeline>
            </ScrollArea.Autosize>
          </Card>
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 5 }}>
          <Stack gap="sm">
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb="xs">Status</Text>
              <Textarea placeholder="Note (optional for status changes)" value={note} onChange={(e) => setNote(e.currentTarget.value)} autosize minRows={2} mb="xs" />
              <Group gap="xs">
                {i.status === 'open' && <Button color="orange" leftSection={<FiCheck />} loading={busy === 'acknowledge'} onClick={() => act('acknowledge')} data-testid="incident-ack">Acknowledge</Button>}
                {i.is_open && <Button color="green" loading={busy === 'resolve'} onClick={() => act('resolve')}>Resolve</Button>}
                {i.is_open && <Button color="gray" variant="light" leftSection={<FiSlash />} loading={busy === 'false-alarm'} onClick={() => act('false-alarm')}>False alarm</Button>}
                <Button variant="default" disabled={!note.trim()} loading={busy === 'notes'} onClick={() => act('notes', { note })}>Add note</Button>
              </Group>
            </Card>
            <Card withBorder radius="md" padding="sm">
              <KV items={[
                ['Raised by', <UserLink id={i.user_id} name={`${i.user?.name || '#' + i.user_id} (${i.role})`} />],
                ['Silent', i.silent ? 'Yes' : 'No'],
                ['Acknowledged', i.acknowledged_at ? `${fmt.dateTime(i.acknowledged_at)} by admin #${i.acknowledged_by}` : '—'],
                ['Escalated', i.escalated_at ? fmt.dateTime(i.escalated_at) : '—'],
                ['Closed', i.resolved_at ? `${fmt.dateTime(i.resolved_at)} by admin #${i.resolved_by}` : '—'],
                ['Ride', i.ride_type ? <RideLink type={i.ride_type} id={i.ride_id} /> : 'No ride'],
                i.ride && ['Ride stage', <StageBadge stage={i.ride.stage} />],
                i.ride && ['Pickup', i.ride.pickup_address],
                i.ride && ['Drop-off', i.ride.dropoff_address],
                i.ride && ['Driver', <UserLink id={i.ride.driver_id} />],
                i.ride && ['Customers', (i.ride.customer_ids || []).map((c) => <UserLink key={c} id={c} />)],
              ]} />
              {i.ride_type && can('rideRoute') && <Anchor component={Link} to={`/live?replay=${i.ride_id}&type=${i.ride_type}`} size="sm" mt="xs" display="block">Replay ride route</Anchor>}
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb={4}>Notes</Text>
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }} c={i.notes ? undefined : 'dimmed'}>{i.notes || 'No notes yet.'}</Text>
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb={4}>Recordings ({i.recordings?.length || 0})</Text>
              {(i.recordings || []).map((r) => (
                <Group key={r.id} justify="space-between">
                  <Text size="sm">#{r.id} · {r.role} · {r.chunk_count} chunks · {humanize(r.status)}</Text>
                  {can('recordings') ? <Anchor component={Link} to={`/safety?tab=recordings&recording=${r.id}`} size="sm">Play</Anchor> : <Text size="xs" c="dimmed">safety reviewer only</Text>}
                </Group>
              ))}
              {!i.recordings?.length && <Text size="sm" c="dimmed">None.</Text>}
            </Card>
            <Card withBorder radius="md" padding="sm">
              <Text fw={600} mb={4}>Reports & checks</Text>
              {(i.reports || []).map((r) => <Text key={r.id} size="sm">Report #{r.id} · {humanize(r.category)} · <Text span c={statusColor(r.status)}>{r.status}</Text></Text>)}
              {(i.checks || []).map((c) => <Text key={c.id} size="sm">Check #{c.id} · {humanize(c.kind)} → {c.status}</Text>)}
              {!i.reports?.length && !i.checks?.length && <Text size="sm" c="dimmed">None.</Text>}
            </Card>
            {i.share_links?.length > 0 && (
              <Card withBorder radius="md" padding="sm">
                <Text fw={600} mb={4}>Live-share links sent to trusted contacts</Text>
                {i.share_links.map((l, k) => (
                  <Text key={k} size="xs">{l.contacts_notified} contact(s) · {l.view_count} views · expires {fmt.dateTime(l.expires_at)} · <Anchor href={l.url} target="_blank" rel="noopener" size="xs">open</Anchor></Text>
                ))}
              </Card>
            )}
          </Stack>
        </Grid.Col>
      </Grid>
      <ContactModal id={i.id} opened={contact} onClose={() => setContact(false)} />
    </>
  );
}
