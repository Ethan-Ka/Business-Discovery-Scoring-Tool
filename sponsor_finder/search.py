"""
Overpass API query builder and fetcher.
Runs in a background thread; results posted back via a callback.
"""

import math
import threading
import requests

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]
MAX_RESULTS = 2000
QUERY_TIMEOUT = 60   # seconds granted to the Overpass server for query execution
REQUEST_TIMEOUT = 68  # socket deadline — must exceed QUERY_TIMEOUT so server error arrives


# ---------------------------------------------------------------------------
# Haversine distance  (miles)
# ---------------------------------------------------------------------------

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Overpass QL builder
# ---------------------------------------------------------------------------

def _build_query(lat: float, lon: float, radius_miles: float) -> str:
    # Use the Overpass `around` filter — a true geodesic circle — instead of a
    # bounding box.  A bbox is a square that extends ~41% further in the corners,
    # which causes businesses well outside the radius to be returned.
    radius_meters = int(radius_miles * 1609.344)
    around = f"around:{radius_meters},{lat},{lon}"

    tags = ["shop", "amenity", "office", "leisure"]
    union_parts = "\n".join(
        f'  node["{t}"]({around});\n  way["{t}"]({around});'
        for t in tags
    )

    return f"""
[out:json][timeout:{QUERY_TIMEOUT}];
(
{union_parts}
);
out center tags;
""".strip()


# ---------------------------------------------------------------------------
# Result parser
# ---------------------------------------------------------------------------

def _parse_element(element: dict, center_lat: float, center_lon: float) -> dict | None:
    tags = element.get("tags", {})

    # Require a name
    name = tags.get("name", "").strip()
    if not name:
        return None

    # Lat/lon — ways use 'center'
    if element["type"] == "node":
        lat = element.get("lat")
        lon = element.get("lon")
    else:
        center = element.get("center", {})
        lat = center.get("lat")
        lon = center.get("lon")

    if lat is None or lon is None:
        return None

    distance = haversine_miles(center_lat, center_lon, lat, lon)

    # Build address string
    addr_parts = [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
        tags.get("addr:city", ""),
        tags.get("addr:state", ""),
        tags.get("addr:postcode", ""),
    ]
    address = ", ".join(p for p in addr_parts if p)

    return {
        "osm_id":        f"{element['type']}/{element['id']}",
        "name":          name,
        "lat":           lat,
        "lon":           lon,
        "distance_miles": round(distance, 2),
        "address":       address,
        "phone":         tags.get("phone", tags.get("contact:phone", "")),
        "email":         tags.get("email", tags.get("contact:email", "")),
        "website":       tags.get("website", tags.get("contact:website", "")),
        "opening_hours": tags.get("opening_hours", ""),
        "tags":          tags,
    }


# ---------------------------------------------------------------------------
# Main fetch function  (runs in background thread)
# ---------------------------------------------------------------------------

def fetch_businesses(
    lat: float,
    lon: float,
    radius_miles: float,
    on_success,
    on_error,
    max_results: int | None = None,
    on_progress=None,
):
    """
    Fetch businesses from Overpass in a background thread.

    on_success(results: list[dict])  — called with parsed results
    on_error(message: str)           — called on network/parse failure
    on_progress(message: str)        — optional status updates
    """

    def _run():
        try:
            if on_progress:
                on_progress("Building query…")

            query = _build_query(lat, lon, radius_miles)

            if on_progress:
                on_progress("Fetching from OpenStreetMap…")

            response = None
            last_error = None
            for i, mirror in enumerate(OVERPASS_MIRRORS):
                try:
                    if i > 0 and on_progress:
                        on_progress(f"Retrying on mirror {i}…")
                    response = requests.post(
                        mirror,
                        data={"data": query},
                        timeout=REQUEST_TIMEOUT,
                        headers={"User-Agent": "RedlineSponsorFinder/1.0"},
                    )
                    response.raise_for_status()
                    break  # success — stop trying mirrors
                except (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.HTTPError) as e:
                    last_error = e
                    response = None

            if response is None:
                raise last_error

            if on_progress:
                on_progress("Parsing results…")

            data = response.json()
            elements = data.get("elements", [])

            results = []
            for el in elements:
                parsed = _parse_element(el, lat, lon)
                if parsed:
                    results.append(parsed)

            # Client-side radius guard (the `around` filter is authoritative, but
            # floating-point edge cases and way-center approximations can still
            # push a result slightly over the limit).
            results = [r for r in results if r["distance_miles"] <= radius_miles]

            effective_max = max_results if max_results is not None else MAX_RESULTS

            # Sort by distance, cap at effective limit
            results.sort(key=lambda b: b["distance_miles"])
            results = results[:effective_max]

            on_success(results)

        except requests.exceptions.Timeout:
            on_error("All Overpass mirrors timed out. Try a smaller radius or retry later.")
        except requests.exceptions.ConnectionError:
            on_error("No internet connection. Check your network and retry.")
        except requests.exceptions.HTTPError as e:
            on_error(f"Overpass API error: {e}")
        except Exception as e:
            on_error(f"Unexpected error: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
