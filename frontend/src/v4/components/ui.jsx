import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Alert, Anchor, Badge, Box, Button, Card, Center, Code, Group, Loader, Modal, Pagination, ScrollArea,
  Stack, Switch, Table, Text, Textarea, Title, Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { FiAlertCircle, FiDownload, FiInbox } from 'react-icons/fi';
import { ago, fmt, humanize, money, RIDE_TYPES, stageColor, statusColor, TZ } from '../lib/format';
import { download } from '../lib/api';

export function PageHeader({ title, subtitle, actions, children }) {
  return (
    <Group justify="space-between" align="flex-end" mb="md" wrap="wrap" gap="sm">
      <div>
        <Title order={2} fz={{ base: 20, sm: 24 }}>{title}</Title>
        {subtitle && <Text c="dimmed" size="sm">{subtitle}</Text>}
        {children}
      </div>
      {actions && <Group gap="xs" wrap="wrap">{actions}</Group>}
    </Group>
  );
}

export function StatCard({ label, value, hint, color, icon: Icon, onClick }) {
  return (
    <Card withBorder padding="md" radius="md" onClick={onClick} style={onClick ? { cursor: 'pointer' } : undefined}>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div style={{ minWidth: 0 }}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
          <Text fz={26} fw={700} c={color} lh={1.2} mt={4}>{value ?? '—'}</Text>
          {hint && <Text size="xs" c="dimmed" mt={2}>{hint}</Text>}
        </div>
        {Icon && <Icon size={22} style={{ opacity: 0.6, flexShrink: 0 }} />}
      </Group>
    </Card>
  );
}

export function StageBadge({ stage, size = 'sm' }) {
  if (!stage) return <Text c="dimmed" size="sm">—</Text>;
  return <Badge color={stageColor(stage)} variant="light" size={size}>{humanize(stage)}</Badge>;
}

export function StatusBadge({ value, size = 'sm', variant = 'light' }) {
  if (value === null || value === undefined || value === '') return <Text c="dimmed" size="sm">—</Text>;
  return <Badge color={statusColor(value)} variant={variant} size={size}>{humanize(value)}</Badge>;
}

export function Money({ cents, ...rest }) {
  return <Text span ff="monospace" {...rest}>{money(cents)}</Text>;
}

export function Time({ value, relative = false, seconds = false }) {
  if (!value) return <Text span c="dimmed">—</Text>;
  const abs = seconds ? fmt.dateTimeSec(value) : fmt.dateTime(value);
  return (
    <Tooltip label={`${relative ? abs : ago(value)} · ${TZ}`} withArrow openDelay={300}>
      <Text span size="sm" style={{ whiteSpace: 'nowrap' }}>{relative ? ago(value) : abs}</Text>
    </Tooltip>
  );
}

export function UserLink({ id, name }) {
  if (!id) return <Text span c="dimmed">—</Text>;
  return <Anchor component={Link} to={`/users/${id}`} size="sm">{name || `User #${id}`}</Anchor>;
}

export function RideLink({ type, id, children }) {
  if (!type || !id) return <Text span c="dimmed">—</Text>;
  return (
    <Anchor component={Link} to={`/rides/${type}/${id}`} size="sm">
      {children || `${RIDE_TYPES[type] || type} #${id}`}
    </Anchor>
  );
}

export function ErrorBox({ error, title = 'Could not load' }) {
  if (!error) return null;
  return (
    <Alert color="red" icon={<FiAlertCircle />} title={title} my="sm">
      {error.message || String(error)}
    </Alert>
  );
}

export function Loading({ h = 160 }) {
  return <Center h={h}><Loader size="sm" /></Center>;
}

export function Empty({ children = 'Nothing here yet.' }) {
  return (
    <Center py="xl">
      <Stack align="center" gap={4}>
        <FiInbox size={22} style={{ opacity: 0.5 }} />
        <Text c="dimmed" size="sm">{children}</Text>
      </Stack>
    </Center>
  );
}

/** Loading / error wrapper for a TanStack query. */
export function QueryView({ q, children, h }) {
  if (q.isLoading) return <Loading h={h} />;
  if (q.error) return <ErrorBox error={q.error} />;
  return children(q.data);
}

/**
 * Plain, responsive table. columns: [{key, label, render?(row), w?, align?}]
 */
export function DataTable({ columns, rows, onRowClick, loading, error, empty, pageInfo, onPage, minWidth = 700, rowKey = 'id', highlight }) {
  return (
    <Card withBorder padding={0} radius="md">
      {error && <Box p="sm"><ErrorBox error={error} /></Box>}
      <ScrollArea type="auto">
        <Table striped highlightOnHover={!!onRowClick} verticalSpacing="xs" miw={minWidth} stickyHeader>
          <Table.Thead>
            <Table.Tr>
              {columns.map((c) => <Table.Th key={c.key} w={c.w} ta={c.align}>{c.label}</Table.Th>)}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(rows || []).map((r, i) => (
              <Table.Tr
                key={r[rowKey] ?? i}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                style={{ cursor: onRowClick ? 'pointer' : undefined }}
                bg={highlight?.(r) ? 'var(--mantine-color-red-light)' : undefined}
              >
                {columns.map((c) => (
                  <Table.Td key={c.key} ta={c.align}>
                    {c.render ? c.render(r) : (r[c.key] ?? '—')}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      {loading && <Loading h={80} />}
      {!loading && !error && (!rows || rows.length === 0) && <Empty>{empty}</Empty>}
      {pageInfo && pageInfo.lastPage > 1 && (
        <Group justify="space-between" p="sm">
          <Text size="xs" c="dimmed">{pageInfo.total} total</Text>
          <Pagination size="sm" total={pageInfo.lastPage} value={pageInfo.page} onChange={onPage} />
        </Group>
      )}
      {pageInfo && pageInfo.lastPage <= 1 && rows?.length > 0 && (
        <Text size="xs" c="dimmed" p="sm">{pageInfo.total} total</Text>
      )}
    </Card>
  );
}

export function CsvButton({ url, params, name = 'export', label = 'CSV' }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="xs" variant="default" leftSection={<FiDownload />} loading={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await download(url, { ...(params || {}), format: 'csv' }, `${name}.csv`);
        } catch (e) {
          notifications.show({ color: 'red', title: 'Export failed', message: e.message });
        } finally {
          setBusy(false);
        }
      }}
    >
      {label}
    </Button>
  );
}

export function Json({ value, maxH = 240 }) {
  if (value === null || value === undefined) return <Text c="dimmed" size="sm">—</Text>;
  return (
    <ScrollArea.Autosize mah={maxH}>
      <Code block fz="xs">{JSON.stringify(value, null, 2)}</Code>
    </ScrollArea.Autosize>
  );
}

export function KV({ items, cols = 1 }) {
  return (
    <Box style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: '6px 16px' }}>
      {items.filter(Boolean).map(([k, v]) => (
        <Group key={k} gap={6} wrap="nowrap" align="flex-start">
          <Text size="sm" c="dimmed" w={130} style={{ flexShrink: 0 }}>{k}</Text>
          <Box size="sm" style={{ minWidth: 0, wordBreak: 'break-word', fontSize: 'var(--mantine-font-size-sm)' }}>{v ?? '—'}</Box>
        </Group>
      ))}
    </Box>
  );
}

/**
 * Modal that collects a mandatory reason (min 5 chars by default) and runs
 * `onSubmit(reason, extra)`. `children` can render extra fields bound to `extra`.
 */
export function ReasonModal({ opened, onClose, title, label = 'Reason', minLength = 5, confirmLabel = 'Confirm', color = 'blue', onSubmit, children, description }) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const close = () => { setReason(''); setErr(null); onClose(); };
  return (
    <Modal opened={opened} onClose={close} title={title} centered size="lg">
      <Stack>
        {description}
        {children}
        <Textarea
          label={label} required autosize minRows={3} value={reason}
          onChange={(e) => setReason(e.currentTarget.value)}
          description={`Mandatory, at least ${minLength} characters. Stored in the audit log.`}
          data-autofocus
        />
        {err && <Alert color="red">{err}</Alert>}
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>Cancel</Button>
          <Button
            color={color} loading={busy} disabled={reason.trim().length < minLength}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await onSubmit(reason.trim());
                close();
              } catch (e) {
                setErr(e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function BoolSwitch({ checked, onChange, disabled, label }) {
  return <Switch checked={!!checked} onChange={(e) => onChange(e.currentTarget.checked)} disabled={disabled} label={label} />;
}

export function notifyOk(message, title = 'Done') {
  notifications.show({ color: 'green', title, message });
}

export function notifyErr(e, title = 'Failed') {
  notifications.show({ color: 'red', title, message: e?.message || String(e) });
}

export function SectionTitle({ children, right }) {
  return (
    <Group justify="space-between" mb="xs">
      <Text fw={600}>{children}</Text>
      {right}
    </Group>
  );
}

export function Forbidden({ what = 'this module' }) {
  return (
    <Alert color="yellow" title="No access" icon={<FiAlertCircle />}>
      Your admin role does not include {what}. Ask a super admin to grant it.
    </Alert>
  );
}
