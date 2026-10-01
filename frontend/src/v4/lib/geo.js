// Map helpers for the admin console.
//  * decodePolyline — Google encoded polyline → [[lat, lng], …]
//  * provinceAt — port of backend/utils/province.py (simplified provincial
//    outlines, good to a few km; generated from the Python source — keep in sync)
//  * CITIES / nearCity — metro areas for the Live map "area" filter

export function decodePolyline(str, precision = 5) {
  if (!str || typeof str !== 'string') return [];
  const factor = 10 ** precision;
  const out = [];
  let index = 0;
  let lat = 0;
  let lng = 0;
  while (index < str.length) {
    let result = 0;
    let shift = 0;
    let b;
    do { b = str.charCodeAt(index++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20 && index <= str.length);
    lat += (result & 1) ? ~(result >> 1) : (result >> 1);
    result = 0;
    shift = 0;
    do { b = str.charCodeAt(index++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20 && index <= str.length);
    lng += (result & 1) ? ~(result >> 1) : (result >> 1);
    out.push([lat / factor, lng / factor]);
  }
  return out;
}

const POLYGONS = {"BC":[[[48.2,-139.1],[60.0,-139.1],[60.0,-120.0],[53.8,-120.0],[52.5,-118.0],[51.0,-116.0],[49.0,-114.06],[48.2,-123.3]]],"AB":[[[49.0,-114.06],[51.0,-116.0],[52.5,-118.0],[53.8,-120.0],[60.0,-120.0],[60.0,-110.0],[49.0,-110.0]]],"SK":[[[49.0,-110.0],[60.0,-110.0],[60.0,-102.0],[55.8,-101.9],[49.0,-101.36]]],"MB":[[[49.0,-101.36],[55.8,-101.9],[60.0,-102.0],[60.0,-94.8],[56.9,-88.9],[52.8,-95.15],[49.0,-95.15]]],"ON":[[[41.6,-83.1],[42.0,-83.2],[43.0,-82.4],[45.3,-83.7],[46.5,-84.6],[47.5,-89.6],[48.0,-89.6],[48.6,-93.2],[49.0,-95.15],[52.8,-95.15],[56.9,-88.9],[55.2,-82.2],[51.5,-79.52],[51.5,-79.52],[47.0,-79.52],[46.7,-79.1],[46.32,-78.7],[46.2,-78.0],[45.85,-77.2],[45.75,-76.7],[45.55,-76.2],[45.47,-75.9],[45.43,-75.72],[45.46,-75.6],[45.53,-75.2],[45.63,-74.65],[45.58,-74.38],[45.3,-74.4],[45.0,-74.7],[44.2,-76.4],[43.6,-79.1],[42.8,-79.0],[41.6,-82.6]]],"QC":[[[45.0,-74.7],[45.3,-74.4],[45.58,-74.38],[45.63,-74.65],[45.53,-75.2],[45.46,-75.6],[45.43,-75.72],[45.47,-75.9],[45.55,-76.2],[45.75,-76.7],[45.85,-77.2],[46.2,-78.0],[46.32,-78.7],[46.7,-79.1],[47.0,-79.52],[51.5,-79.52],[55.2,-82.2],[62.6,-78.0],[62.6,-64.0],[60.3,-64.5],[55.0,-67.0],[52.0,-67.2],[52.0,-57.1],[51.4,-57.1],[50.0,-60.0],[49.2,-64.0],[48.0,-64.2],[48.0,-67.7],[47.3,-68.3],[47.4,-69.2],[46.2,-70.3],[45.3,-70.8],[45.0,-71.5]]],"NB":[[[45.0,-67.1],[44.6,-66.9],[45.1,-65.0],[45.8,-64.0],[46.0,-63.8],[47.1,-64.3],[47.9,-64.5],[48.0,-64.2],[48.0,-67.7],[47.3,-68.3],[47.4,-69.2],[47.0,-67.8],[45.6,-67.8]]],"NS":[[[43.3,-66.3],[45.1,-65.0],[45.8,-64.0],[46.0,-63.8],[45.8,-62.0],[47.1,-60.5],[47.1,-59.6],[45.8,-59.6],[44.4,-62.0],[43.3,-65.5]]],"PE":[[[45.9,-64.45],[46.7,-64.45],[47.1,-64.0],[46.5,-61.9],[45.9,-62.0],[45.95,-63.5]]],"NL":[[[46.5,-59.5],[51.9,-55.3],[52.0,-57.1],[52.0,-67.2],[55.0,-67.0],[60.3,-64.5],[60.5,-63.5],[53.0,-55.0],[47.8,-52.5],[46.5,-52.5]]],"YT":[[[60.0,-141.0],[69.7,-141.0],[68.9,-136.4],[67.0,-136.2],[60.0,-124.0]]],"NT":[[[60.0,-124.0],[67.0,-136.2],[68.9,-136.4],[70.5,-135.0],[70.5,-120.0],[65.0,-110.0],[65.0,-102.0],[60.0,-102.0]]],"NU":[[[60.0,-102.0],[65.0,-102.0],[65.0,-110.0],[70.5,-120.0],[83.2,-120.0],[83.2,-61.0],[62.6,-64.0],[62.6,-78.0],[60.0,-94.8]]]};
const ORDER = ["PE", "NS", "NB", "NL", "QC", "ON", "MB", "SK", "AB", "BC", "YT", "NT", "NU"];
const CANADA_BOX = [41.6, 83.2, -141.1, -52.5];

export const PROVINCE_NAMES = {
  AB: 'Alberta', BC: 'British Columbia', MB: 'Manitoba', NB: 'New Brunswick', NL: 'Newfoundland and Labrador',
  NS: 'Nova Scotia', NT: 'Northwest Territories', NU: 'Nunavut', ON: 'Ontario', PE: 'Prince Edward Island',
  QC: 'Québec', SK: 'Saskatchewan', YT: 'Yukon',
};

function inside(lat, lng, ring) {
  let ins = false;
  for (let i = 0, n = ring.length; i < n; i += 1) {
    const [y1, x1] = ring[i];
    const [y2, x2] = ring[(i + 1) % n];
    if ((y1 > lat) !== (y2 > lat)) {
      const xc = x1 + ((lat - y1) * (x2 - x1)) / (y2 - y1);
      if (lng < xc) ins = !ins;
    }
  }
  return ins;
}

function lookup(lat, lng) {
  for (const code of ORDER) {
    if (POLYGONS[code].some((ring) => inside(lat, lng, ring))) return code;
  }
  return null;
}

/** Two-letter province/territory code for a point, or null outside Canada. */
export function provinceAt(lat, lng) {
  const a = Number(lat);
  const b = Number(lng);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const hit = lookup(a, b);
  if (hit) return hit;
  const [loLat, hiLat, loLng, hiLng] = CANADA_BOX;
  if (!(a >= loLat && a <= hiLat && b >= loLng && b <= hiLng)) return null;
  const d = 0.12;
  for (const [dy, dx] of [[d, 0], [-d, 0], [0, d], [0, -d], [d, d], [d, -d], [-d, d], [-d, -d]]) {
    const h = lookup(a + dy, b + dx);
    if (h) return h;
  }
  return null;
}

// Metro areas (centre + radius) for the "City" filter.
export const CITIES = [
  { key: 'toronto', label: 'Toronto (GTA)', lat: 43.6532, lng: -79.3832, km: 45 },
  { key: 'montreal', label: 'Montréal', lat: 45.5019, lng: -73.5674, km: 35 },
  { key: 'vancouver', label: 'Vancouver', lat: 49.2827, lng: -123.1207, km: 35 },
  { key: 'calgary', label: 'Calgary', lat: 51.0447, lng: -114.0719, km: 30 },
  { key: 'edmonton', label: 'Edmonton', lat: 53.5461, lng: -113.4938, km: 30 },
  { key: 'ottawa', label: 'Ottawa–Gatineau', lat: 45.4215, lng: -75.6972, km: 30 },
  { key: 'winnipeg', label: 'Winnipeg', lat: 49.8951, lng: -97.1384, km: 25 },
  { key: 'quebec', label: 'Québec City', lat: 46.8139, lng: -71.208, km: 25 },
  { key: 'hamilton', label: 'Hamilton', lat: 43.2557, lng: -79.8711, km: 20 },
  { key: 'kitchener', label: 'Kitchener–Waterloo', lat: 43.4516, lng: -80.4925, km: 20 },
  { key: 'london', label: 'London (ON)', lat: 42.9849, lng: -81.2453, km: 20 },
  { key: 'halifax', label: 'Halifax', lat: 44.6488, lng: -63.5752, km: 25 },
  { key: 'victoria', label: 'Victoria', lat: 48.4284, lng: -123.3656, km: 20 },
  { key: 'saskatoon', label: 'Saskatoon', lat: 52.1332, lng: -106.67, km: 20 },
  { key: 'regina', label: 'Regina', lat: 50.4452, lng: -104.6189, km: 20 },
  { key: 'stjohns', label: 'St. John’s', lat: 47.5615, lng: -52.7126, km: 20 },
];

export function haversineKm(a, b) {
  const R = 6371;
  const toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLng = toRad(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** Area filter: `area` is '' | 'prov:ON' | 'city:toronto'. */
export function inArea(area, lat, lng) {
  if (!area) return true;
  const a = Number(lat);
  const b = Number(lng);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  if (area.startsWith('prov:')) return provinceAt(a, b) === area.slice(5);
  if (area.startsWith('city:')) {
    const c = CITIES.find((x) => x.key === area.slice(5));
    return c ? haversineKm([a, b], [c.lat, c.lng]) <= c.km : true;
  }
  return true;
}
