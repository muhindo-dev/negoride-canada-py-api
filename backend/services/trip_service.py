"""Trip search service — Haversine distance, driver matching."""
import math
from backend.models.user import AdminUser
from backend.models.trip import Trip


def haversine(lat1, lon1, lat2, lon2):
    """Haversine formula — returns distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# Service type → user model field mapping (matches Laravel)
SERVICE_TYPE_MAP = {
    'car': 'is_car',
    'special car': 'is_car',
    'airport pickup': 'is_airport',
    'movers': 'is_movers',
    'courier': 'is_courier',
    'boda': 'is_boda',
    'taxi': 'is_taxi',
    'bus': 'is_bus',
    'emergency': 'is_emergency',
    'ambulance': 'is_ambulance',
}


def search_nearby_drivers(
    automobile: str,
    current_lat: float,
    current_lng: float,
    max_distance_km: float = 50.0,
):
    """Search for available drivers by service type and distance.

    Returns drivers sorted by distance (nearest-first), each with:
    - distance (km)
    - min_time / max_time (estimated travel time in minutes)
    """
    field = SERVICE_TYPE_MAP.get(automobile.lower(), 'is_car')

    q = AdminUser.query.filter(
        AdminUser.user_type == 'Driver',
        AdminUser.status == 1,
        AdminUser.online_offline == 'online',
        AdminUser.current_latitude.isnot(None),
        AdminUser.current_longitude.isnot(None),
    )

    # Filter by service capability
    col = getattr(AdminUser, field, None)
    if col is not None:
        q = q.filter(col == 'Yes')

    # Also check service approval
    approval_field = field.replace('is_', '') + '_approved'
    approval_col = getattr(AdminUser, approval_field, None)
    if approval_col is not None:
        q = q.filter(approval_col == 'Yes')

    drivers = q.all()

    results = []
    for d in drivers:
        try:
            d_lat = float(d.current_latitude)
            d_lng = float(d.current_longitude)
        except (TypeError, ValueError):
            continue

        dist = haversine(current_lat, current_lng, d_lat, d_lng)

        if dist <= max_distance_km:
            # Estimate travel time (avg 40 km/h city driving)
            min_time = round(dist / 60 * 60)  # at 60 km/h
            max_time = round(dist / 30 * 60)  # at 30 km/h

            driver_data = d.to_dict()
            driver_data['distance'] = round(dist, 2)
            driver_data['min_time'] = max(1, min_time)
            driver_data['max_time'] = max(2, max_time)
            results.append(driver_data)

    results.sort(key=lambda x: x['distance'])
    return results


def search_available_trips(start_gps=None, end_gps=None, max_distance_km=50.0):
    """Search available rideshare trips near the given GPS coordinates."""
    trips = Trip.query.filter(
        Trip.status.in_(['Active', 'Scheduled']),
    ).all()

    if not start_gps:
        return [t.to_dict() for t in trips]

    try:
        parts = start_gps.split(',')
        s_lat, s_lng = float(parts[0]), float(parts[1])
    except (ValueError, IndexError):
        return [t.to_dict() for t in trips]

    results = []
    for t in trips:
        try:
            parts = t.start_gps.split(',')
            t_lat, t_lng = float(parts[0]), float(parts[1])
        except (ValueError, IndexError, AttributeError):
            continue

        dist = haversine(s_lat, s_lng, t_lat, t_lng)
        if dist <= max_distance_km:
            td = t.to_dict()
            td['distance'] = round(dist, 2)
            results.append(td)

    results.sort(key=lambda x: x['distance'])
    return results
