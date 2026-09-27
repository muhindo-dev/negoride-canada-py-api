import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Avatar, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core';
import { useAuth } from '../../contexts/AuthContext';
import { unlockAudio } from '../lib/alarm';

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    unlockAudio(); // the sign-in click unlocks the SOS alarm audio
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      nav('/', { replace: true });
    } catch (err) {
      setError(err?.response?.data?.message || err.message || 'Login failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Center mih="100vh" p="md" bg="var(--mantine-color-body)">
      <Paper withBorder shadow="md" p="xl" radius="md" w="100%" maw={400}>
        <form onSubmit={submit}>
          <Stack>
            <Stack gap={4} align="center">
              <Avatar color="orange" variant="filled" radius="md" size={48}>N</Avatar>
              <Title order={3}>NegoRide Operations</Title>
              <Text c="dimmed" size="sm">Sign in with your admin account</Text>
            </Stack>
            {error && <Alert color="red">{error}</Alert>}
            <TextInput label="Email or username" value={email} onChange={(e) => setEmail(e.currentTarget.value)} required autoComplete="username" name="email" />
            <PasswordInput label="Password" value={password} onChange={(e) => setPassword(e.currentTarget.value)} required autoComplete="current-password" name="password" />
            <Button type="submit" loading={busy} fullWidth color="orange">Sign in</Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
