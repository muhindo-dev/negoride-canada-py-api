// Legacy (v3) admin pages, kept working under /legacy/* inside the new shell.
// Their stylesheet is scoped to .legacy-scope so it can't leak into the v4 UI.
import React from 'react';
import { Outlet } from 'react-router-dom';
import { Alert } from '@mantine/core';
import './legacy.css';

export default function LegacyOutlet() {
  return (
    <>
      <Alert color="gray" variant="light" mb="sm" py={6}>
        Legacy v3 screen — kept for reference. Prefer the new modules in the navigation.
      </Alert>
      <div className="legacy-scope" style={{ borderRadius: 8, padding: 16, minHeight: 400 }}>
        <Outlet />
      </div>
    </>
  );
}
