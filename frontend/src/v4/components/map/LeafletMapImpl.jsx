import React, { useEffect, useRef } from 'react';
import { Circle, CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet';
import { useComputedColorScheme } from '@mantine/core';
import 'leaflet/dist/leaflet.css';
import { boundsOf } from './MapView';

function Fitter({ fitKey, pts }) {
  const map = useMap();
  const last = useRef(null);
  useEffect(() => {
    if (fitKey === undefined || fitKey === last.current) return;
    if (!pts.length) return;
    last.current = fitKey;
    if (pts.length === 1) map.setView(pts[0], Math.max(map.getZoom(), 14));
    else map.fitBounds(pts, { padding: [30, 30], maxZoom: 16 });
  }, [fitKey, pts, map]);
  return null;
}

function Follower({ follow }) {
  const map = useMap();
  const lat = follow?.[0];
  const lng = follow?.[1];
  useEffect(() => {
    if (Number.isFinite(lat) && Number.isFinite(lng)) map.panTo([lat, lng], { animate: true });
  }, [lat, lng, map]);
  return null;
}

function Resizer() {
  const map = useMap();
  useEffect(() => {
    const el = map.getContainer();
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(el);
    return () => ro.disconnect();
  }, [map]);
  return null;
}

export default function LeafletMapImpl({ center, zoom, markers = [], polylines = [], circles = [], fitKey, follow }) {
  const scheme = useComputedColorScheme('light');
  const pts = boundsOf(markers, polylines, circles);
  const dark = scheme === 'dark';
  return (
    <MapContainer center={center} zoom={zoom} style={{ height: '100%', width: '100%' }} preferCanvas>
      <TileLayer key={dark ? "dark" : "light"}
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution="&copy; OpenStreetMap contributors"
        maxZoom={19}
        className={dark ? 'osm-dark' : undefined}
      />
      <Resizer />
      <Fitter fitKey={fitKey} pts={pts} />
      {follow && <Follower follow={follow} />}
      {circles.map((c) => (
        <Circle
          key={c.id} center={[c.lat, c.lng]} radius={c.radiusM}
          pathOptions={{ color: c.color, fillColor: c.color, fillOpacity: c.fillOpacity ?? 0.3, weight: c.weight ?? 0 }}
        >
          {c.label && <Tooltip>{c.label}</Tooltip>}
        </Circle>
      ))}
      {polylines.map((p) => (
        <Polyline
          key={p.id} positions={p.points}
          pathOptions={{ color: p.color || '#228be6', weight: p.weight || 4, opacity: p.opacity ?? 0.85, dashArray: p.dashed ? '6 8' : undefined }}
        />
      ))}
      {markers.filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lng)).map((m) => (
        <CircleMarker
          key={m.id} center={[m.lat, m.lng]} radius={m.radius || 8}
          pathOptions={{ color: m.ring || '#ffffff', weight: m.ringWeight ?? 2, fillColor: m.color || '#228be6', fillOpacity: 0.95 }}
          eventHandlers={m.onClick ? { click: () => m.onClick(m) } : undefined}
        >
          {m.label && <Tooltip direction="top" offset={[0, -6]}>{m.label}</Tooltip>}
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
