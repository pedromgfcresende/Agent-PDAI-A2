"""Google Maps tools for place search, geocoding, and route calculation."""

from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request

from langchain_core.tools import tool

# Maximum distance (km) a place can be from the location center
_MAX_RADIUS_KM = 15.0


def _maps_key() -> str | None:
    return os.getenv("GOOGLE_MAPS_API_KEY")


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in km between two points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _geocode_location(location: str) -> tuple[float, float] | None:
    """Geocode a location string to (lat, lng). Returns None on failure."""
    api_key = _maps_key()
    if not api_key:
        return None
    encoded = urllib.parse.urlencode({"address": location, "key": api_key})
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{encoded}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return loc["lat"], loc["lng"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Place Search (Google Places API — New)
# ---------------------------------------------------------------------------

@tool
def search_places(
    query: str,
    location_bias: str = "Porto, Portugal",
    center_lat: float = 0.0,
    center_lng: float = 0.0,
) -> str:
    """Search for real places, venues, and landmarks using Google Maps.

    Use specific place-type queries for best results — e.g. 'seafood restaurants
    in Porto', 'museums in Porto', 'parks near Matosinhos'. Avoid vague queries
    like 'activities' or 'things to do'.

    Results are restricted to a 15 km radius from the center of the target
    location. Places outside this radius are automatically filtered out.

    Args:
        query: Specific place search, e.g. 'wine cellars Vila Nova de Gaia'
        location_bias: City or area to bias results toward
        center_lat: Latitude of the center point (0 = auto-geocode from location_bias)
        center_lng: Longitude of the center point (0 = auto-geocode from location_bias)
    """
    api_key = _maps_key()
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY not set"

    # Resolve center coordinates for distance filtering
    if center_lat == 0.0 and center_lng == 0.0:
        coords = _geocode_location(location_bias)
        if coords:
            center_lat, center_lng = coords

    url = "https://places.googleapis.com/v1/places:searchText"

    request_body: dict = {
        "textQuery": f"{query} near {location_bias}",
        "maxResultCount": 10,
        "languageCode": "en",
    }

    # Use a 15 km circle bias when we have center coordinates
    if center_lat and center_lng:
        request_body["locationBias"] = {
            "circle": {
                "center": {"latitude": center_lat, "longitude": center_lng},
                "radius": _MAX_RADIUS_KM * 1000,  # metres
            }
        }

    body = json.dumps(request_body).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.displayName,places.formattedAddress,"
                "places.location,places.types,places.rating,"
                "places.editorialSummary"
            ),
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return f"Error searching places: {e}"

    results = []
    for p in data.get("places", []):
        loc = p.get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        summary = p.get("editorialSummary", {}).get("text", "")

        # Filter out places beyond 15 km from center
        if lat and lng and center_lat and center_lng:
            dist = _haversine_km(center_lat, center_lng, lat, lng)
            if dist > _MAX_RADIUS_KM:
                continue

        results.append({
            "name": p.get("displayName", {}).get("text", "Unknown"),
            "address": p.get("formattedAddress", ""),
            "latitude": lat,
            "longitude": lng,
            "types": p.get("types", [])[:3],
            "rating": p.get("rating"),
            "summary": summary,
        })

    if not results:
        return "No places found for this query."
    return json.dumps(results, indent=2)


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

@tool
def geocode_address(address: str) -> str:
    """Get the latitude and longitude for a given address.

    Args:
        address: The address or place name to geocode
    """
    api_key = _maps_key()
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY not set"

    encoded = urllib.parse.urlencode({"address": address, "key": api_key})
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{encoded}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return f"Error geocoding: {e}"

    if data.get("status") != "OK" or not data.get("results"):
        return f"Could not geocode '{address}'"

    loc = data["results"][0]["geometry"]["location"]
    return json.dumps({
        "address": data["results"][0]["formatted_address"],
        "latitude": loc["lat"],
        "longitude": loc["lng"],
    })


# ---------------------------------------------------------------------------
# Route / Travel Duration (Google Routes API v2)
# ---------------------------------------------------------------------------

@tool
def get_travel_time(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    travel_mode: str = "DRIVE",
) -> str:
    """Calculate travel time and distance between two points using Google Maps Routes API.

    Args:
        origin_lat: Origin latitude
        origin_lng: Origin longitude
        dest_lat: Destination latitude
        dest_lng: Destination longitude
        travel_mode: DRIVE or WALK
    """
    api_key = _maps_key()
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY not set"

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"
    body = json.dumps({
        "origin": {"location": {"latLng": {"latitude": origin_lat, "longitude": origin_lng}}},
        "destination": {"location": {"latLng": {"latitude": dest_lat, "longitude": dest_lng}}},
        "travelMode": travel_mode,
        "routingPreference": "TRAFFIC_AWARE" if travel_mode == "DRIVE" else "ROUTING_PREFERENCE_UNSPECIFIED",
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return f"Error calculating route: {e}"

    routes = data.get("routes", [])
    if not routes:
        return "No route found between these points."

    route = routes[0]
    duration_sec = int(route.get("duration", "0s").rstrip("s"))
    distance_m = route.get("distanceMeters", 0)

    return json.dumps({
        "duration_minutes": round(duration_sec / 60, 1),
        "distance_km": round(distance_m / 1000, 1),
        "travel_mode": travel_mode,
    })


# ---------------------------------------------------------------------------
# Google Maps URL Builder
# ---------------------------------------------------------------------------

@tool
def build_google_maps_url(stops_json: str) -> str:
    """Build a Google Maps directions URL that shows the full driving route between stops.
    The URL will render with the actual road path drawn on the map.

    Args:
        stops_json: JSON string of a list of stops. Each stop must have 'name'
            and optionally 'latitude'/'longitude'. Example:
            '[{"name": "Ribeira, Porto", "latitude": 41.14, "longitude": -8.61},
              {"name": "Livraria Lello", "latitude": 41.15, "longitude": -8.61}]'
    """
    try:
        stops = json.loads(stops_json) if isinstance(stops_json, str) else stops_json
    except (json.JSONDecodeError, TypeError):
        return "Error: stops_json must be a valid JSON array"

    if not stops or len(stops) < 2:
        return "Need at least 2 stops to build a route URL."

    def _place_str(stop: dict) -> str:
        if stop.get("latitude") and stop.get("longitude"):
            return f"{stop['latitude']},{stop['longitude']}"
        return stop.get("name", "Unknown")

    origin = urllib.parse.quote(_place_str(stops[0]))
    destination = urllib.parse.quote(_place_str(stops[-1]))

    # Use the Google Maps Directions URL format which renders the actual route path
    params = {
        "api": "1",
        "origin": _place_str(stops[0]),
        "destination": _place_str(stops[-1]),
        "travelmode": "driving",
    }

    if len(stops) > 2:
        waypoints = "|".join(_place_str(s) for s in stops[1:-1])
        params["waypoints"] = waypoints

    query_string = urllib.parse.urlencode(params)
    url = f"https://www.google.com/maps/dir/?{query_string}"

    return url
