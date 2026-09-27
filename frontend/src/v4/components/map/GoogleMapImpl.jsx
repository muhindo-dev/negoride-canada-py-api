import React, { useEffect, useRef } from 'react';
import { APIProvider, Map, Marker, useMap } from '@vis.gl/react-google-maps';
import { useComputedColorScheme } from '@mantine/core';
import { boundsOf, GOOGLE_KEY } from './MapView';

function Shapes({ polylines, circles }) {
  const map = useMap();
  useEffect(() => {
    if (!map || !window.google) return undefined;
    const g = window.google.maps;
    const objs = [];
    polylines.forEach((p) => {
      objs.push(new g.Polyline({
        map, path: p.points.map(([lat, lng]) => ({ lat, lng })), strokeColor: p.color || '#228be6',
        strokeWeight: p.weight || 4, strokeOpacity: p.dashed ? 0 : (p.opacity ?? 0.85),
        icons: p.dashed ? [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 1, scale: 3 }, offset: '0', repeat: '14px' }] : undefined,
      }));
    });
    circles.forEach((c) => {
      objs.push(new g.Circle({
        map, center: { lat: c.lat, lng: c.lng }, radius: c.radiusM, strokeWeight: c.weight ?? 0,
        fillColor: c.color, fillOpacity: c.fillOpacity ?? 0.3, strokeColor: c.color,
      }));
    });
    return () => objs.forEach((o) => o.setMap(null));
  }, [map, polylines, circles]);
  return null;
}

function Fitter({ fitKey, pts }) {
  const map = useMap();
  const last = useRef(null);
  useEffect(() => {
    if (!map || !window.google || fitKey === undefined || fitKey === last.current || !pts.length) return;
    last.current = fitKey;
    if (pts.length === 1) {
      map.setCenter({ lat: pts[0][0], lng: pts[0][1] });
      map.setZoom(Math.max(map.getZoom() || 0, 14));
      return;
    }
    const b = new window.google.maps.LatLngBounds();
    pts.forEach(([lat, lng]) => b.extend({ lat, lng }));
    map.fitBounds(b, 30);
  }, [map, fitKey, pts]);
  return null;
}

function Follower({ follow }) {
  const map = useMap();
  const lat = follow?.[0];
  const lng = follow?.[1];
  useEffect(() => {
    if (map && Number.isFinite(lat) && Number.isFinite(lng)) map.panTo({ lat, lng });
  }, [map, lat, lng]);
  return null;
}

export default function GoogleMapImpl({ center, zoom, markers = [], polylines = [], circles = [], fitKey, follow }) {
  const scheme = useComputedColorScheme('light');
  const pts = boundsOf(markers, polylines, circles);
  return (
    <APIProvider apiKey={GOOGLE_KEY}>
      <Map
        defaultCenter={{ lat: center[0], lng: center[1] }} defaultZoom={zoom} gestureHandling="greedy"
        colorScheme={scheme === 'dark' ? 'DARK' : 'LIGHT'} style={{ width: '100%', height: '100%' }}
        disableDefaultUI={false} clickableIcons={false}
      >
        <Shapes polylines={polylines} circles={circles} />
        <Fitter fitKey={fitKey} pts={pts} />
        {follow && <Follower follow={follow} />}
        {markers.filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lng)).map((m) => (
          <Marker
            key={m.id} position={{ lat: m.lat, lng: m.lng }} title={m.label}
            onClick={m.onClick ? () => m.onClick(m) : undefined}
            icon={window.google ? {
              path: window.google.maps.SymbolPath.CIRCLE, scale: m.radius || 8, fillColor: m.color || '#228be6',
              fillOpacity: 0.95, strokeColor: m.ring || '#ffffff', strokeWeight: m.ringWeight ?? 2,
            } : undefined}
          />
        ))}
      </Map>
    </APIProvider>
  );
}
