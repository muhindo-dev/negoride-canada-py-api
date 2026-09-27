import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Box, Button, Group, Text } from '@mantine/core';
import { FiAlertTriangle } from 'react-icons/fi';
import { useSos } from '../lib/sos';
import { ago, humanize } from '../lib/format';
import { notifyErr } from './ui';

/** Full-width red banner, pinned while any SOS is un-acknowledged (spec §8.2.4). */
export default function SosBanner() {
  const { alarming, acknowledge, enabled } = useSos();
  const [busy, setBusy] = useState(null);
  if (!enabled || !alarming.length) return null;
  return (
    <Box
      role="alert" data-testid="sos-banner"
      style={{ background: '#c92a2a', color: 'white', animation: 'sosPulse 1s ease-in-out infinite alternate', margin: 'calc(-1 * var(--app-shell-padding)) calc(-1 * var(--app-shell-padding)) var(--mantine-spacing-md)', position: 'sticky', top: 'var(--app-shell-header-height)', zIndex: 150 }}
      px="md" py="xs"
    >
      {alarming.slice(0, 4).map((i) => (
        <Group key={i.id} justify="space-between" wrap="wrap" gap="xs" py={4}>
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <FiAlertTriangle size={20} style={{ flexShrink: 0 }} />
            <Text fw={800} size="sm" style={{ whiteSpace: 'nowrap' }}>SOS #{i.id}</Text>
            <Text size="sm" truncate>
              {i.user?.name || `User #${i.user?.id || i.user_id || '?'}`} ({humanize(i.role)})
              {i.ride_type ? ` · ${humanize(i.ride_type)} #${i.ride_id}` : ' · no ride'}
              {' · '}{ago(i.created_at)}
              {Number.isFinite(i.lat) ? ` · ${Number(i.lat).toFixed(5)}, ${Number(i.lng).toFixed(5)}` : ''}
            </Text>
          </Group>
          <Group gap="xs">
            <Button size="xs" variant="white" color="red" component={Link} to={`/safety/incidents/${i.id}`}>Open</Button>
            <Button
              size="xs" color="dark" loading={busy === i.id} data-testid="sos-ack"
              onClick={async () => {
                setBusy(i.id);
                try { await acknowledge(i.id); } catch (e) { notifyErr(e, 'Acknowledge failed'); } finally { setBusy(null); }
              }}
            >
              Acknowledge
            </Button>
          </Group>
        </Group>
      ))}
      {alarming.length > 4 && <Text size="xs">+{alarming.length - 4} more open SOS</Text>}
    </Box>
  );
}
