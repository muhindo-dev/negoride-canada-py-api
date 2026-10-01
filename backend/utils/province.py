"""Canadian province / territory from a lat/lng (spec §13.3 — tax by pickup province).

Offline, dependency-free and fast: each province is approximated by one or more
simplified polygons (good to a few km along borders — enough for sales-tax
purposes; the admin can always correct `pickup_province` on a ride). Points
just outside every outline (coast, island) are resolved by probing ~15 km
around them; anything else returns None. Border towns facing each other across
a river (Windsor/Detroit) cannot be told apart at this resolution — pickups
are in Canada by construction, so that is harmless.

    from backend.utils.province import province_at
    province_at(49.2827, -123.1207)   # 'BC'
"""

# Simplified outlines as (lat, lng) rings. Borders between neighbours use the
# legal lines (e.g. AB/SK 110°W, SK/MB ~101.5°W, the 60th parallel for the
# territories); coastlines are generous boxes because water has no riders.
# Ontario / Québec border (Ottawa River, Lake Timiskaming, then 79.52°W), south → north.
_ON_QC = [(45.00, -74.70), (45.30, -74.40), (45.58, -74.38), (45.63, -74.65), (45.53, -75.20),
          (45.46, -75.60), (45.43, -75.72), (45.47, -75.90), (45.55, -76.20), (45.75, -76.70),
          (45.85, -77.20), (46.20, -78.00), (46.32, -78.70), (46.70, -79.10), (47.00, -79.52),
          (51.50, -79.52)]

_POLYGONS = {
    'BC': [[(48.2, -139.1), (60.0, -139.1), (60.0, -120.0), (53.8, -120.0), (52.5, -118.0),
            (51.0, -116.0), (49.0, -114.06), (48.2, -123.3)]],
    'AB': [[(49.0, -114.06), (51.0, -116.0), (52.5, -118.0), (53.8, -120.0), (60.0, -120.0),
            (60.0, -110.0), (49.0, -110.0)]],
    'SK': [[(49.0, -110.0), (60.0, -110.0), (60.0, -102.0), (55.8, -101.9), (49.0, -101.36)]],
    'MB': [[(49.0, -101.36), (55.8, -101.9), (60.0, -102.0), (60.0, -94.8), (56.9, -88.9),
            (52.8, -95.15), (49.0, -95.15)]],
    'ON': [[(41.6, -83.1), (42.0, -83.2), (43.0, -82.4), (45.3, -83.7), (46.5, -84.6), (47.5, -89.6),
            (48.0, -89.6), (48.6, -93.2), (49.0, -95.15), (52.8, -95.15), (56.9, -88.9), (55.2, -82.2),
            (51.5, -79.52)] + list(reversed(_ON_QC)) + [(44.2, -76.4), (43.6, -79.1), (42.8, -79.0),
                                                       (41.6, -82.6)]],
    'QC': [_ON_QC + [(55.2, -82.2),
            (62.6, -78.0), (62.6, -64.0), (60.3, -64.5), (55.0, -67.0), (52.0, -67.2), (52.0, -57.1),
            (51.4, -57.1), (50.0, -60.0), (49.2, -64.0), (48.0, -64.2), (48.0, -67.7), (47.3, -68.3),
            (47.4, -69.2), (46.2, -70.3), (45.3, -70.8), (45.0, -71.5)]],
    'NB': [[(45.0, -67.1), (44.6, -66.9), (45.1, -65.0), (45.8, -64.0), (46.0, -63.8), (47.1, -64.3),
            (47.9, -64.5), (48.0, -64.2), (48.0, -67.7), (47.3, -68.3), (47.4, -69.2), (47.0, -67.8),
            (45.6, -67.8)]],
    'NS': [[(43.3, -66.3), (45.1, -65.0), (45.8, -64.0), (46.0, -63.8), (45.8, -62.0), (47.1, -60.5),
            (47.1, -59.6), (45.8, -59.6), (44.4, -62.0), (43.3, -65.5)]],
    'PE': [[(45.9, -64.45), (46.7, -64.45), (47.1, -64.0), (46.5, -61.9), (45.9, -62.0), (45.95, -63.5)]],
    'NL': [[(46.5, -59.5), (51.9, -55.3), (52.0, -57.1), (52.0, -67.2), (55.0, -67.0), (60.3, -64.5),
            (60.5, -63.5), (53.0, -55.0), (47.8, -52.5), (46.5, -52.5)]],
    'YT': [[(60.0, -141.0), (69.7, -141.0), (68.9, -136.4), (67.0, -136.2), (60.0, -124.0)]],
    'NT': [[(60.0, -124.0), (67.0, -136.2), (68.9, -136.4), (70.5, -135.0), (70.5, -120.0),
            (65.0, -110.0), (65.0, -102.0), (60.0, -102.0)]],
    'NU': [[(60.0, -102.0), (65.0, -102.0), (65.0, -110.0), (70.5, -120.0), (83.2, -120.0),
            (83.2, -61.0), (62.6, -64.0), (62.6, -78.0), (60.0, -94.8)]],
}

_ORDER = ('PE', 'NS', 'NB', 'NL', 'QC', 'ON', 'MB', 'SK', 'AB', 'BC', 'YT', 'NT', 'NU')

# Rough Canada bounding box; outside it we don't guess.
_CANADA_BOX = (41.6, 83.2, -141.1, -52.5)


def _inside(lat, lng, ring):
    """Ray casting on (lat, lng) rings."""
    inside = False
    n = len(ring)
    for i in range(n):
        y1, x1 = ring[i]
        y2, x2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lng < x_cross:
                inside = not inside
    return inside


def province_at(lat, lng):
    """Two-letter province/territory code for a point, or None when it is not
    (plausibly) in Canada."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    # Small provinces first so they win over a generous neighbour outline.
    for code in _ORDER:
        for ring in _POLYGONS[code]:
            if _inside(lat, lng, ring):
                return code
    lo_lat, hi_lat, lo_lng, hi_lng = _CANADA_BOX
    if not (lo_lat <= lat <= hi_lat and lo_lng <= lng <= hi_lng):
        return None
    # Near-miss (coastline, island, polygon sliver): look ~10 km around the point.
    for dlat, dlng in ((0.12, 0), (-0.12, 0), (0, 0.12), (0, -0.12), (0.12, 0.12), (0.12, -0.12),
                       (-0.12, 0.12), (-0.12, -0.12)):
        for code in _ORDER:
            for ring in _POLYGONS[code]:
                if _inside(lat + dlat, lng + dlng, ring):
                    return code
    return None
