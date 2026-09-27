// Driver document viewer: bytes fetched with the admin JWT
// (GET /api/admin/onboarding/documents/{id}/file?inline=1, audited) and shown
// with zoom / rotate. PDFs open in an <iframe>.
import React, { useEffect, useState } from 'react';
import { ActionIcon, Box, Center, Group, Image, Loader, Modal, Slider, Text } from '@mantine/core';
import { FiRotateCw, FiZoomIn } from 'react-icons/fi';
import { fetchBlob } from '../lib/api';

const cache = new Map();

export function useDocBlob(docId, enabled = true) {
  const [state, setState] = useState(() => cache.get(docId) || { loading: !!enabled });
  useEffect(() => {
    if (!enabled || !docId) return undefined;
    if (cache.has(docId)) { setState(cache.get(docId)); return undefined; }
    let alive = true;
    fetchBlob(`/admin/onboarding/documents/${docId}/file`, { inline: 1 })
      .then(({ blob, contentType }) => {
        const v = { url: URL.createObjectURL(blob), type: contentType };
        cache.set(docId, v);
        if (alive) setState(v);
      })
      .catch((e) => alive && setState({ error: e.message }));
    return () => { alive = false; };
  }, [docId, enabled]);
  return state;
}

export function DocThumb({ doc, onOpen, h = 110 }) {
  const s = useDocBlob(doc.id);
  return (
    <Box h={h} onClick={onOpen} style={{ cursor: 'zoom-in', borderRadius: 6, overflow: 'hidden', background: 'var(--mantine-color-default-hover)' }}>
      {s.loading ? <Center h={h}><Loader size="xs" /></Center>
        : s.error ? <Center h={h}><Text size="xs" c="red" ta="center" px={4}>{s.error}</Text></Center>
          : s.type?.includes('pdf') ? <Center h={h}><Text size="sm">PDF — click to open</Text></Center>
            : <Image src={s.url} h={h} fit="cover" alt={doc.title} />}
    </Box>
  );
}

export function DocZoomModal({ doc, opened, onClose, footer }) {
  const s = useDocBlob(doc?.id, !!doc);
  const [zoom, setZoom] = useState(1);
  const [rot, setRot] = useState(0);
  useEffect(() => { setZoom(1); setRot(0); }, [doc?.id]);
  return (
    <Modal opened={opened} onClose={onClose} size="xl" title={doc ? `${doc.title} · #${doc.id}` : ''} centered>
      {doc && (
        <>
          <Group mb="xs" gap="sm">
            <FiZoomIn />
            <Slider value={zoom} onChange={setZoom} min={0.5} max={4} step={0.1} style={{ flex: 1 }} label={(v) => `${Math.round(v * 100)}%`} />
            <ActionIcon variant="default" onClick={() => setRot((r) => (r + 90) % 360)} aria-label="Rotate"><FiRotateCw /></ActionIcon>
          </Group>
          <div className="doc-zoom" onWheel={(e) => { if (e.ctrlKey) { e.preventDefault(); setZoom((z) => Math.min(4, Math.max(0.5, z - e.deltaY / 400))); } }}>
            {s.loading ? <Center h={300}><Loader /></Center>
              : s.error ? <Text c="red" p="md">{s.error}</Text>
                : s.type?.includes('pdf') ? <iframe title="document" src={s.url} style={{ width: '100%', height: '70vh', border: 0 }} />
                  : <img src={s.url} alt={doc.title} style={{ width: `${zoom * 100}%`, transform: `rotate(${rot}deg)` }} />}
          </div>
          {footer}
        </>
      )}
    </Modal>
  );
}
