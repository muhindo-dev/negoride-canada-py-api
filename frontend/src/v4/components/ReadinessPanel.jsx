// Launch readiness (GET /api/admin/readiness): configuration blockers shown as
// a prominent red banner, warnings in a collapsible list. Configuration only —
// the backend never calls a vendor for this.
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Alert, Anchor, Badge, Box, Button, Collapse, Group, List, Stack, Text } from '@mantine/core';
import { FiAlertOctagon, FiAlertTriangle, FiCheckCircle, FiChevronDown, FiChevronUp, FiRefreshCw } from 'react-icons/fi';
import { http } from '../lib/api';
import { ago } from '../lib/format';

// Accepts the documented shape {blockers, warnings, checks} and the plain
// module list [{key, area, level: ok|warning|critical, message}].
export function normalizeReadiness(data) {
  if (!data) return { critical: [], warnings: [], checks: [], production: null, checkedAt: null };
  const list = Array.isArray(data) ? data : (data.checks || [...(data.blockers || []), ...(data.warnings || [])]);
  const items = list.map((c) => {
    const level = c.level || (c.ok ? 'ok' : c.severity === 'blocker' ? 'critical' : 'warning');
    return { key: c.key, area: c.area || String(c.key || '').split('.')[0], level, message: c.message, fix: c.fix };
  });
  return {
    critical: items.filter((c) => c.level === 'critical'),
    warnings: items.filter((c) => c.level === 'warning'),
    checks: items,
    production: Array.isArray(data) ? null : data.production,
    checkedAt: Array.isArray(data) ? null : data.checked_at,
  };
}

function settingsLink(item) {
  const m = /Settings\s*→\s*([a-z_.]+)/i.exec(item.fix || item.message || '');
  if (m) return `/settings?q=${encodeURIComponent(m[1])}`;
  if (/^(company|safety)\./.test(item.key || '')) return `/settings?q=${encodeURIComponent(item.key)}`;
  return null;
}

function Item({ c }) {
  const to = settingsLink(c);
  return (
    <List.Item>
      <Text size="sm" span fw={600} ff="monospace">{c.key}</Text>
      <Text size="sm" span> — {c.message}</Text>
      {c.fix && <Text size="xs" c="dimmed">Fix: {c.fix}{to && <> · <Anchor component={Link} to={to} size="xs">open setting</Anchor></>}</Text>}
    </List.Item>
  );
}

export default function ReadinessPanel() {
  const q = useQuery({ queryKey: ['readiness'], queryFn: () => http.get('/admin/readiness'), refetchInterval: 120000 });
  const [showWarn, setShowWarn] = useState(false);
  const [showAllCrit, setShowAllCrit] = useState(false);
  if (q.isLoading) return null;
  if (q.error) {
    return <Alert color="gray" mb="sm" py={6} icon={<FiAlertTriangle />}>Launch readiness unavailable: {q.error.message}</Alert>;
  }
  const r = normalizeReadiness(q.data);
  const refresh = (
    <Button size="compact-xs" variant="subtle" color={r.critical.length ? 'white' : 'gray'} leftSection={<FiRefreshCw size={12} />} loading={q.isFetching} onClick={() => q.refetch()}>
      Re-check
    </Button>
  );
  return (
    <Stack gap="xs" mb="sm" data-testid="readiness-panel">
      {r.critical.length > 0 && (
        <Box
          role="alert" data-testid="readiness-critical"
          style={{ background: 'var(--mantine-color-red-filled)', color: 'white', borderRadius: 8 }} p="sm"
        >
          <Group justify="space-between" mb={6} wrap="wrap">
            <Group gap="xs">
              <FiAlertOctagon size={20} />
              <Text fw={800}>{r.critical.length} critical launch blocker{r.critical.length === 1 ? '' : 's'}</Text>
              {r.production !== null && <Badge color={r.production ? 'dark' : 'gray'} variant="filled" size="sm">{r.production ? 'PRODUCTION' : 'development'}</Badge>}
            </Group>
            <Group gap="xs">
              {r.checkedAt && <Text size="xs" opacity={0.85}>checked {ago(r.checkedAt)}</Text>}
              {refresh}
            </Group>
          </Group>
          <List size="sm" spacing={4} c="white" styles={{ itemWrapper: { color: 'white' } }}>
            {(showAllCrit ? r.critical : r.critical.slice(0, 3)).map((c) => {
              const to = settingsLink(c);
              return (
                <List.Item key={c.key}>
                  <Text span size="sm" fw={700} ff="monospace" c="white">{c.key}</Text>
                  <Text span size="sm" c="white"> — {c.message}</Text>
                  {c.fix && (
                    <Text size="xs" c="white" opacity={0.9}>
                      Fix: {c.fix}{to && <> · <Anchor component={Link} to={to} size="xs" c="white" underline="always">open setting</Anchor></>}
                    </Text>
                  )}
                </List.Item>
              );
            })}
          </List>
          {r.critical.length > 3 && (
            <Button size="compact-xs" variant="white" color="red" mt={6} onClick={() => setShowAllCrit((v) => !v)} data-testid="readiness-toggle">
              {showAllCrit ? 'Show fewer' : `Show all ${r.critical.length} blockers`}
            </Button>
          )}
        </Box>
      )}
      {r.warnings.length > 0 && (
        <Alert color="yellow" variant="light" py={6} icon={<FiAlertTriangle />}>
          <Group justify="space-between" wrap="nowrap">
            <Text size="sm" fw={600}>{r.warnings.length} readiness warning{r.warnings.length === 1 ? '' : 's'} (features degraded)</Text>
            <Button size="compact-xs" variant="subtle" color="yellow" rightSection={showWarn ? <FiChevronUp /> : <FiChevronDown />} onClick={() => setShowWarn((v) => !v)}>
              {showWarn ? 'Hide' : 'Show'}
            </Button>
          </Group>
          <Collapse in={showWarn}>
            <List size="sm" spacing={4} mt={6}>{r.warnings.map((c) => <Item key={c.key} c={c} />)}</List>
          </Collapse>
        </Alert>
      )}
      {!r.critical.length && !r.warnings.length && (
        <Group gap={6}>
          <FiCheckCircle color="var(--mantine-color-green-6)" />
          <Text size="xs" c="dimmed">Launch readiness: all {r.checks.length} configuration checks pass.</Text>
        </Group>
      )}
    </Stack>
  );
}
