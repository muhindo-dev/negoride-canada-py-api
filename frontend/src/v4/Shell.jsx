import React, { Suspense, useEffect } from 'react';
import { NavLink as RouterLink, Outlet, useLocation } from 'react-router-dom';
import {
  ActionIcon, AppShell, Avatar, Badge, Burger, Group, Indicator, Menu, NavLink, ScrollArea, Text, Tooltip,
  useMantineColorScheme, useComputedColorScheme,
} from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  FiActivity, FiAlertOctagon, FiArchive, FiBell, FiBarChart2, FiDollarSign, FiFileText, FiHome, FiLifeBuoy,
  FiLogOut, FiMap, FiMoon, FiNavigation, FiSettings, FiShield, FiStar, FiSun, FiUserCheck, FiUsers, FiKey, FiList,
} from 'react-icons/fi';
import { useAuth } from '../contexts/AuthContext';
import { useRoles, ROLE_LABELS } from './lib/roles';
import { useRealtimeStatus } from './lib/realtime';
import { useSos } from './lib/sos';
import { unlockAudio } from './lib/alarm';
import SosBanner from './components/SosBanner';
import { Loading } from './components/ui';
import { initials } from './lib/format';

export const NAV = [
  { group: 'Operations', items: [
    { to: '/', label: 'Command Center', icon: FiHome, access: 'commandCenter', end: true },
    { to: '/live', label: 'Live Operations Map', icon: FiMap, access: 'liveMap' },
    { to: '/safety', label: 'Safety Center', icon: FiShield, access: 'safety', sos: true },
    { to: '/rides', label: 'Rides', icon: FiNavigation, access: 'rides' },
  ] },
  { group: 'People', items: [
    { to: '/users', label: 'Users', icon: FiUsers, access: 'users' },
    { to: '/onboarding', label: 'Driver Onboarding', icon: FiUserCheck, access: 'onboarding' },
    { to: '/support', label: 'Disputes & Support', icon: FiLifeBuoy, access: 'support' },
    { to: '/ratings', label: 'Ratings', icon: FiStar, access: 'ratings' },
  ] },
  { group: 'Business', items: [
    { to: '/finance', label: 'Payments & Finance', icon: FiDollarSign, access: 'finance' },
    { to: '/reports', label: 'Reports & Analytics', icon: FiBarChart2, access: 'reports' },
    { to: '/notifications', label: 'Notifications', icon: FiBell, access: 'notifications' },
  ] },
  { group: 'Platform', items: [
    { to: '/legal', label: 'Legal', icon: FiFileText, access: 'legal' },
    { to: '/settings', label: 'Settings', icon: FiSettings, access: 'settings' },
    { to: '/admin-users', label: 'Admin users & roles', icon: FiKey, access: 'adminUsers' },
    { to: '/audit', label: 'Audit log', icon: FiList, access: 'audit' },
  ] },
  { group: 'Legacy', collapsed: true, items: [
    { to: '/legacy/dashboard', label: 'Dashboard', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/users', label: 'Users & Drivers', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/trips', label: 'Trips', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/bookings', label: 'Bookings', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/negotiations', label: 'Negotiations', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/payments', label: 'Payments', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/payouts', label: 'Payouts', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/wallets', label: 'Wallets', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/chats', label: 'Chats', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/companies', label: 'Companies', icon: FiArchive, access: 'legacy' },
    { to: '/legacy/route-stages', label: 'Route Stages', icon: FiArchive, access: 'legacy' },
  ] },
];

function RealtimeDot() {
  const { status } = useRealtimeStatus();
  const color = status === 'connected' ? 'green' : status === 'connecting' ? 'yellow' : 'red';
  return (
    <Tooltip label={`Realtime: ${status}`}>
      <Badge variant="dot" color={color} size="sm" data-testid="rt-status" data-status={status}>
        {status === 'connected' ? 'Live' : status === 'connecting' ? 'Connecting' : 'Offline'}
      </Badge>
    </Tooltip>
  );
}

export default function Shell() {
  const [opened, { toggle, close }] = useDisclosure();
  const { user, logout } = useAuth();
  const { can, roles } = useRoles();
  const { alarming } = useSos();
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme('light');
  const loc = useLocation();

  useEffect(() => { close(); }, [loc.pathname, close]);
  useEffect(() => {
    const h = () => unlockAudio();
    window.addEventListener('pointerdown', h);
    window.addEventListener('keydown', h);
    return () => { window.removeEventListener('pointerdown', h); window.removeEventListener('keydown', h); };
  }, []);

  const isActive = (to, end) => (end ? loc.pathname === to : loc.pathname === to || loc.pathname.startsWith(`${to}/`));

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 250, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding={{ base: 'sm', sm: 'md' }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <Group gap={8} wrap="nowrap">
              <Avatar color="orange" variant="filled" radius="sm" size={30}>N</Avatar>
              <div>
                <Text fw={800} lh={1}>NegoRide</Text>
                <Text size="xs" c="dimmed" lh={1}>Operations console</Text>
              </div>
            </Group>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <RealtimeDot />
            {alarming.length > 0 && (
              <Badge color="red" variant="filled" leftSection={<FiAlertOctagon />} component={RouterLink} to="/safety" style={{ cursor: 'pointer' }}>
                {alarming.length} SOS
              </Badge>
            )}
            <Tooltip label={scheme === 'dark' ? 'Light theme' : 'Dark theme'}>
              <ActionIcon variant="default" size="lg" aria-label="Toggle theme" onClick={() => setColorScheme(scheme === 'dark' ? 'light' : 'dark')}>
                {scheme === 'dark' ? <FiSun /> : <FiMoon />}
              </ActionIcon>
            </Tooltip>
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <ActionIcon variant="subtle" size="lg" radius="xl" aria-label="Account">
                  <Avatar size={30} radius="xl" color="blue">{initials(user?.name)}</Avatar>
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{user?.name}</Menu.Label>
                <Menu.Label>{roles.map((r) => ROLE_LABELS[r] || r).join(', ')}</Menu.Label>
                <Menu.Divider />
                <Menu.Item leftSection={<FiLogOut />} onClick={logout} color="red">Sign out</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs">
        <AppShell.Section grow component={ScrollArea}>
          {NAV.map((g) => {
            const items = g.items.filter((i) => can(i.access));
            if (!items.length) return null;
            const body = items.map((i) => (
              <NavLink
                key={i.to} component={RouterLink} to={i.to} label={i.label} active={isActive(i.to, i.end)}
                leftSection={
                  i.sos && alarming.length ? (
                    <Indicator color="red" processing size={8}><i.icon /></Indicator>
                  ) : <i.icon />
                }
                styles={{ root: { borderRadius: 6 } }}
              />
            ));
            if (g.collapsed) {
              return (
                <NavLink key={g.group} label={g.group} leftSection={<FiArchive />} defaultOpened={loc.pathname.startsWith('/legacy')} childrenOffset={12} styles={{ root: { borderRadius: 6 } }}>
                  {body}
                </NavLink>
              );
            }
            return (
              <div key={g.group}>
                <Text size="xs" fw={700} c="dimmed" tt="uppercase" px="sm" mt="sm" mb={4}>{g.group}</Text>
                {body}
              </div>
            );
          })}
        </AppShell.Section>
        <AppShell.Section>
          <Group gap={6} px="sm" py={6}>
            <FiActivity size={12} />
            <Text size="xs" c="dimmed">NegoRide Canada · v4 admin</Text>
          </Group>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <SosBanner />
        <Suspense fallback={<Loading h={240} />}>
          <Outlet />
        </Suspense>
      </AppShell.Main>
    </AppShell>
  );
}
