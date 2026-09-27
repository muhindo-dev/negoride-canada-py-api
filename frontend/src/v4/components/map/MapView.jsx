// Provider-neutral map. Google Maps JS (via @vis.gl/react-google-maps) when
// VITE_GOOGLE_MAPS_KEY is set at build time, otherwise Leaflet + OpenStreetMap
// (works with no key). Each provider is its own lazy chunk.
//
// props:
//   markers   [{id, lat, lng, color, label, radius, ring, onClick}]
//   polylines [{id, points: [[lat,lng]...], color, weight, dashed}]
//   circles   [{id, lat, lng, radiusM, color, fillOpacity, label}]
//   fitKey    change it to re-fit the viewport to everything drawn
//   follow    [lat,lng] — pan to it whenever it changes
//   center/zoom initial viewport; height (px or css)
import React, { lazy, Suspense } from 'react';
import { Box, Center, Loader } from '@mantine/core';

export const GOOGLE_KEY = import.meta.env.VITE_GOOGLE_MAPS_KEY || '';
export const MAP_PROVIDER = GOOGLE_KEY ? 'google' : 'leaflet';

const Impl = GOOGLE_KEY ? lazy(() => import('./GoogleMapImpl')) : lazy(() => import('./LeafletMapImpl'));

export const DEFAULT_CENTER = [43.6532, -79.3832]; // Toronto

export default function MapView({ height = 400, ...props }) {
  return (
    <Box h={height} pos="relative" style={{ borderRadius: 8, overflow: 'hidden', isolation: 'isolate' }} data-map-provider={MAP_PROVIDER}>
      <Suspense fallback={<Center h="100%"><Loader size="sm" /></Center>}>
        <Impl center={DEFAULT_CENTER} zoom={11} {...props} />
      </Suspense>
    </Box>
  );
}

export function boundsOf(markers = [], polylines = [], circles = []) {
  const pts = [];
  markers.forEach((m) => Number.isFinite(m.lat) && Number.isFinite(m.lng) && pts.push([m.lat, m.lng]));
  polylines.forEach((p) => (p.points || []).forEach((q) => pts.push(q)));
  circles.forEach((c) => Number.isFinite(c.lat) && pts.push([c.lat, c.lng]));
  return pts;
}
