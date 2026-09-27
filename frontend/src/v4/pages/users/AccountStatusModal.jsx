// Activate / Deactivate / Suspend / Ban / Reactivate (spec §15): mandatory
// reason (list + free text), notify toggle and a live preview of the message.
import React, { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Checkbox, Group, Modal, NumberInput, SegmentedControl, Select, Stack, Switch, Text, Textarea } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { http } from '../../lib/api';
import { humanize } from '../../lib/format';

const ACTION_COLORS = { activate: 'green', reactivate: 'green', suspend: 'orange', deactivate: 'gray', ban: 'red', pending_review: 'yellow' };

export default function AccountStatusModal({ user, current, opened, onClose, onDone, initialAction }) {
  const reasons = useQuery({ queryKey: ['account-reasons'], queryFn: () => http.get('/admin/account-status/reasons'), staleTime: 3600000 });
  const [action, setAction] = useState(initialAction || 'suspend');
  const [reasonCode, setReasonCode] = useState(null);
  const [text, setText] = useState('');
  const [unit, setUnit] = useState('days');
  const [amount, setAmount] = useState(7);
  const [notify, setNotify] = useState(true);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => { if (opened) { setAction(initialAction || (current === 'active' ? 'suspend' : 'reactivate')); setErr(null); } }, [opened, initialAction, current]);

  const body = {
    action, reason_code: reasonCode, reason_text: text.trim(), notify_user: notify, force,
    ...(action === 'suspend' ? (unit === 'hours' ? { duration_hours: amount } : { duration_days: amount }) : {}),
  };
  const [dBody] = useDebouncedValue(JSON.stringify(body), 300);
  const preview = useQuery({
    queryKey: ['account-preview', user?.id, dBody],
    queryFn: () => http.post(`/admin/users/${user.id}/account-status/preview`, JSON.parse(dBody)),
    enabled: !!(opened && user?.id),
  });

  const actions = (reasons.data?.actions || []).map((a) => a.action);
  return (
    <Modal opened={opened} onClose={onClose} title={`Account status — ${user?.name || `#${user?.id}`}`} size="lg" centered>
      <Stack>
        <Text size="sm">Current status: <b>{humanize(current)}</b>. Changes revoke sessions immediately; an active ride is allowed to finish first.</Text>
        <SegmentedControl fullWidth value={action} onChange={setAction} color={ACTION_COLORS[action]}
          data={(actions.length ? actions : ['activate', 'reactivate', 'suspend', 'deactivate', 'ban']).map((a) => ({ value: a, label: humanize(a) }))} />
        {action === 'suspend' && (
          <Group align="flex-end">
            <NumberInput label="Suspend for" value={amount} onChange={setAmount} min={1} w={140} />
            <SegmentedControl value={unit} onChange={setUnit} data={['hours', 'days']} />
          </Group>
        )}
        <Select label="Reason" required placeholder="Choose from the list" value={reasonCode} onChange={setReasonCode} searchable
          data={(reasons.data?.reasons || []).map((r) => ({ value: r.code, label: `${r.label} (${r.category})` }))} />
        <Textarea label="Explanation" required value={text} onChange={(e) => setText(e.currentTarget.value)} autosize minRows={2}
          description="Internal note, stored with the status change and in the audit log." />
        <Switch label="Notify the user (push / SMS / email)" checked={notify} onChange={(e) => setNotify(e.currentTarget.checked)} />
        <Card withBorder padding="sm" bg="var(--mantine-color-default-hover)">
          <Text size="xs" c="dimmed" mb={4}>Message preview {notify ? '' : '(not sent — notify is off)'}</Text>
          {preview.error ? <Text size="sm" c="red">{preview.error.message}</Text>
            : (
              <Stack gap={6} data-testid="status-preview">
                {['en', 'fr'].map((l) => preview.data?.message?.[l] && (
                  <div key={l}>
                    <Text size="sm" fw={600}>{l.toUpperCase()} · {preview.data.message[l].title}</Text>
                    <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>{preview.data.message[l].body}</Text>
                  </div>
                ))}
                {preview.data?.message?.channels && <Text size="xs" c="dimmed">Channels: {preview.data.message.channels.join(', ')}</Text>}
                {!preview.data && <Text size="sm">…</Text>}
              </Stack>
            )}
        </Card>
        {preview.data?.will_defer && (
          <Alert color="yellow">
            User is on an active ride ({preview.data.active_ride?.ride_type} #{preview.data.active_ride?.ride_id}); the change will apply when it ends.
            <Checkbox mt="xs" label="Apply immediately anyway" checked={force} onChange={(e) => setForce(e.currentTarget.checked)} />
          </Alert>
        )}
        {err && <Alert color="red">{err}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color={ACTION_COLORS[action]} loading={busy} disabled={!reasonCode || !text.trim()}
            onClick={async () => {
              setBusy(true); setErr(null);
              try {
                const res = await http.postFull(`/admin/users/${user.id}/account-status`, body);
                onDone(res.message);
                onClose();
              } catch (e) { setErr(e.message); } finally { setBusy(false); }
            }}>
            {humanize(action)}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
