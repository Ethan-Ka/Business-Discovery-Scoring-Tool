"""
Overpass API query builder and fetcher.
Runs in a background thread; results posted back via a callback.

When an area is large enough to risk rate-limiting, the search is automatically
split into concentric ring phases (incremental radius steps).  Each phase
queries a full circle up to the current step radius; new results (beyond the
previous ring boundary) are kept and added to the running total.  This keeps
individual requests small while guaranteeing complete coverage.
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
QUERY_TIMEOUT        = 60   # seconds granted to the Overpass server
REQUEST_TIMEOUT      = 68   # socket deadline — must exceed QUERY_TIMEOUT
COUNT_TIMEOUT        = 20   # quick count query
COUNT_REQUEST_TIMEOUT = 25

# When the estimated element count exceeds this threshold the fetch is split
# into concentric ring phases of RING_STEP_MILES each.
PHASE_THRESHOLD = 350
RING_STEP_MILES = 3.0   # each ring phase covers this many additional miles


# ---------------------------------------------------------------------------
# Haversine distance  (miles)
# ---------------------------------------------------------------------------

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Overpass QL builders
# ---------------------------------------------------------------------------

def _around(lat: float, lon: float, radius_miles: float) -> str:
    return f"around:{int(radius_miles * 1609.344)},{lat},{lon}"


def _build_query(lat: float, lon: float, radius_miles: float,
                 timeout: int = QUERY_TIMEOUT) -> str:
    """Full circle query for all supported tag types."""
    a = _around(lat, lon, radius_miles)
    tags = ["shop", "amenity", "office", "leisure"]
    union_parts = "\n".join(
        f'  node["{t}"]({a});\n  way["{t}"]({a});'
        for t in tags
    )
    return (
        f"[out:json][timeout:{timeout}];\n"
        f"(\n{union_parts}\n);\n"
        "out center tags;"
    )


def _build_count_query(lat: float, lon: float, radius_miles: float) -> str:
    """Lightweight query that returns only the element count (no geometry)."""
    a = _around(lat, lon, radius_miles)
    tags = ["shop", "amenity", "office", "leisure"]
    union_parts = "\n".join(
        f'  node["{t}"]({a});\n  way["{t}"]({a});'
        for t in tags
    )
    return (
        f"[out:json][timeout:{COUNT_TIMEOUT}];\n"
        f"(\n{union_parts}\n);\n"
        "out count;"
    )


def _ring_steps(total_radius: float) -> list[float]:
    """
    Return the list of cumulative radii for each ring phase.

    Example — total_radius=10mi, RING_STEP_MILES=3:
        [3.0, 6.0, 9.0, 10.0]

    The first step starts from 0; each subsequent step picks up from where
    the previous ring ended.  The last entry is always total_radius so the
    full area is always covered.
    """
    steps = []
    r = RING_STEP_MILES
    while r < total_radius:
        steps.append(round(r, 2))
        r += RING_STEP_MILES
    steps.append(round(total_radius, 2))
    return steps


# ---------------------------------------------------------------------------
# Result parser
# ---------------------------------------------------------------------------

def _parse_element(element: dict, center_lat: float, center_lon: float) -> dict | None:
    tags = element.get("tags", {})

    name = tags.get("name", "").strip()
    if not name:
        return None

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

    addr_parts = [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
        tags.get("addr:city", ""),
        tags.get("addr:state", ""),
        tags.get("addr:postcode", ""),
    ]
    address = ", ".join(p for p in addr_parts if p)

    return {
        "osm_id":         f"{element['type']}/{element['id']}",
        "name":           name,
        "lat":            lat,
        "lon":            lon,
        "distance_miles": round(distance, 2),
        "address":        address,
        "phone":          tags.get("phone",   tags.get("contact:phone",   "")),
        "email":          tags.get("email",   tags.get("contact:email",   "")),
        "website":        tags.get("website", tags.get("contact:website", "")),
        "opening_hours":  tags.get("opening_hours", ""),
        "tags":           tags,
    }


# ---------------------------------------------------------------------------
# Mirror helper
# ---------------------------------------------------------------------------

def _post_query(query: str, req_timeout: int,
                on_progress=None, retry_label: str = "",
                cancelled_fn=None) -> requests.Response:
    """Try each Overpass mirror in order; return first successful Response."""
    last_error = None
    for i, mirror in enumerate(OVERPASS_MIRRORS):
        if cancelled_fn and cancelled_fn():
            return None
        if i > 0 and on_progress:
            on_progress(f"Retrying on mirror {i + 1}…{(' ' + retry_label) if retry_label else ''}")
        try:
            resp = requests.post(
                mirror,
                data={"data": query},
                timeout=req_timeout,
                headers={"User-Agent": "RedlineSponsorFinder/1.0"},
            )
            resp.raise_for_status()
            return resp
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            last_error = e
    raise last_error


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
    cancellation_token=None,
):
    """
    Fetch businesses from Overpass in a background thread.

    For small areas (estimated elements ≤ PHASE_THRESHOLD) a single combined
    query is used.  For larger areas the radius is divided into concentric ring
    phases of RING_STEP_MILES each.  Phase N queries a full circle of radius
    r_N; only elements whose distance falls in the ring (r_prev, r_N] are kept,
    so each phase's *net new* result set stays small even as the outer radius
    grows.

    on_success(results: list[dict])  — called with final parsed results
    on_error(message: str)           — called on network/parse failure
    on_progress(message: str)        — optional status updates
    cancellation_token               — optional CancellationToken; if cancelled,
                                       results are silently discarded
    """

    def _cancelled():
        return cancellation_token is not None and cancellation_token.is_cancelled()

    def _prog(msg: str):
        if on_progress and not _cancelled():
            on_progress(msg)

    def _parse_elements(elements: list[dict],
                        inner_radius: float = 0.0,
                        seen_ids: set | None = None) -> list[dict]:
        """
        Parse raw Overpass elements.  Only keep results whose distance_miles is
        greater than inner_radius (ring lower bound) and whose osm_id has not
        been seen yet.
        """
        results = []
        for el in elements:
            if _cancelled():
                return []
            parsed = _parse_element(el, lat, lon)
            if not parsed:
                continue
            if parsed["distance_miles"] <= inner_radius:
                continue
            if seen_ids is not None and parsed["osm_id"] in seen_ids:
                continue
            if seen_ids is not None:
                seen_ids.add(parsed["osm_id"])
            results.append(parsed)
        return results

    def _run():
        try:
            if _cancelled():
                return

            effective_max = max_results if max_results is not None else MAX_RESULTS

            # ── Step 1: quick count to decide strategy ───────────────────
            _prog("Checking area size…")
            raw_count = None
            try:
                count_query = _build_count_query(lat, lon, radius_miles)
                resp = _post_query(count_query, COUNT_REQUEST_TIMEOUT,
                                   on_progress=on_progress,
                                   cancelled_fn=_cancelled)
                if resp is not None:
                    count_tags = resp.json().get("elements", [{}])[0].get("tags", {})
                    raw_count = int(count_tags.get("total", 0))
            except Exception:
                raw_count = None  # fall through to single query

            if _cancelled():
                return

            # ── Step 2a: single query — small area or count failed ────────
            if raw_count is None or raw_count <= PHASE_THRESHOLD:
                _prog("Fetching from OpenStreetMap…")
                query = _build_query(lat, lon, radius_miles)
                resp = _post_query(query, REQUEST_TIMEOUT,
                                   on_progress=on_progress,
                                   cancelled_fn=_cancelled)
                if _cancelled() or resp is None:
                    return

                _prog("Parsing results…")
                elements = resp.json().get("elements", [])
                results = _parse_elements(elements)

            # ── Step 2b: ring phases — large area ─────────────────────────
            else:
                steps = _ring_steps(radius_miles)
                total_phases = len(steps)
                _prog(
                    f"Large area (~{raw_count} elements) — "
                    f"searching in {total_phases} ring phases…"
                )

                seen_ids: set[str] = set()
                results: list[dict] = []
                prev_radius = 0.0

                for phase_idx, step_radius in enumerate(steps):
                    if _cancelled():
                        return

                    inner_mi = round(prev_radius, 1)
                    outer_mi = round(step_radius, 1)
                    _prog(
                        f"Phase {phase_idx + 1}/{total_phases}: "
                        f"searching {inner_mi}–{outer_mi} mi "
                        f"({len(results)} found so far)…"
                    )

                    query = _build_query(lat, lon, step_radius)
                    try:
                        resp = _post_query(
                            query, REQUEST_TIMEOUT,
                            on_progress=on_progress,
                            retry_label=f"({inner_mi}–{outer_mi} mi)",
                            cancelled_fn=_cancelled,
                        )
                    except (requests.exceptions.Timeout,
                            requests.exceptions.ConnectionError,
                            requests.exceptions.HTTPError) as e:
                        # Partial failure — keep what we have and stop.
                        _prog(
                            f"Phase {phase_idx + 1} failed ({e}). "
                            f"Returning {len(results)} results so far."
                        )
                        break

                    if _cancelled() or resp is None:
                        return

                    phase_elements = resp.json().get("elements", [])
                    phase_results  = _parse_elements(
                        phase_elements,
                        inner_radius=prev_radius,
                        seen_ids=seen_ids,
                    )
                    if _cancelled():
                        return

                    results.extend(phase_results)
                    prev_radius = step_radius

                    _prog(
                        f"Phase {phase_idx + 1}/{total_phases} done "
                        f"(+{len(phase_results)} new, {len(results)} total)…"
                    )

            if _cancelled():
                return

            # ── Step 3: final radius guard, sort, cap ─────────────────────
            results = [r for r in results if r["distance_miles"] <= radius_miles]
            results.sort(key=lambda b: b["distance_miles"])
            results = results[:effective_max]

            on_success(results)

        except requests.exceptions.Timeout:
            if not _cancelled():
                on_error("All Overpass mirrors timed out. Try a smaller radius or retry later.")
        except requests.exceptions.ConnectionError:
            if not _cancelled():
                on_error("No internet connection. Check your network and retry.")
        except requests.exceptions.HTTPError as e:
            if not _cancelled():
                on_error(f"Overpass API error: {e}")
        except Exception as e:
            if not _cancelled():
                on_error(f"Unexpected error: {e}")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
