"""
CSV export and notes persistence.
Notes are stored in notes.json, keyed by OSM node ID.
"""

import csv
import json
import os
from datetime import datetime

from paths import (
    get_data_dir, get_config_path, get_notes_path, get_shortlist_path, get_cache_path,
    get_history_path, get_saved_searches_path, get_collections_path,
)


# ---------------------------------------------------------------------------
# Notes persistence
# ---------------------------------------------------------------------------

def load_notes() -> dict:
    """Load notes from notes.json. Returns {} if file doesn't exist."""
    notes_file = get_notes_path()
    if os.path.exists(notes_file):
        try:
            with open(notes_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_notes(notes: dict) -> None:
    """Persist notes dict to notes.json."""
    try:
        notes_file = get_notes_path()
        with open(notes_file, "w", encoding="utf-8") as f:
            json.dump(notes, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise RuntimeError(f"Could not save notes: {e}") from e


# ---------------------------------------------------------------------------
# Shortlist persistence
# ---------------------------------------------------------------------------

def load_shortlist() -> set:
    """Load shortlist from shortlist.json. Returns empty set if missing."""
    shortlist_file = get_shortlist_path()
    if os.path.exists(shortlist_file):
        try:
            with open(shortlist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def save_shortlist(shortlist: set) -> None:
    """Persist shortlist to shortlist.json."""
    try:
        shortlist_file = get_shortlist_path()
        with open(shortlist_file, "w", encoding="utf-8") as f:
            json.dump(sorted(shortlist), f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = {
    "saved_location": {"address": "", "lat": None, "lon": None},
    "window": {"width": 1200, "height": 750, "x": 100, "y": 100},
    "last_radius_miles": 5.0,
    "last_max_results": 250,
    "ai_settings": {
        "model": "llama3",
        "weight": 0.5,
        "explain_on": True,
        "scoring_on": False,
        "max_score": 500,
        "disable_max_limit": True,
        "debug_mode": False,
    },
    "data_sources": {
        "google_places_enabled": False,
        "yelp_enabled": False,
    },
    "search_settings": {
        "overpass_timeout": 68,
        "max_enrichment_workers": 10,
    },
    "debug_settings": {
        "verbose_enrichment": False,
        "show_ai_prompts": False,
    },
}


def ensure_data_files_exist() -> None:
    """Create all app directories and seed default files on first run.

    Safe to call on every startup — only creates what is missing.
    """
    # Ensure data/ directory (and models/ subdirectory) exist.
    from paths import get_models_dir
    get_data_dir()
    get_models_dir()

    # Seed core data files with empty/default content.
    file_defaults: dict[str, object] = {
        get_config_path(): dict(_DEFAULT_CONFIG),
        get_notes_path(): {},
        get_shortlist_path(): [],
        get_cache_path(): {},
        get_history_path(): [],
        get_saved_searches_path(): [],
        get_collections_path(): {},
    }

    for file_path, default_value in file_defaults.items():
        if os.path.exists(file_path):
            continue
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(default_value, f, indent=2, ensure_ascii=False)
        except OSError:
            continue

    # Ensure profiles/ directory exists and profiles.json is seeded with defaults.
    try:
        from profiles import _ensure_profiles_file_exists
    except ImportError:
        from sponsor_finder.profiles import _ensure_profiles_file_exists
    _ensure_profiles_file_exists()


def load_config() -> dict:
    """Load config.json. Returns defaults if file doesn't exist or is corrupt."""
    config_file = get_config_path()
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so new keys always exist
            merged = dict(_DEFAULT_CONFIG)
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """Persist config dict to config.json."""
    try:
        config_file = get_config_path()
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise RuntimeError(f"Could not save config: {e}") from e


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

EXPORT_COLUMNS = [
    ("Name",        lambda b, n: b.get("name", "")),
    ("Address",     lambda b, n: b.get("address", "")),
    ("Phone",       lambda b, n: b.get("phone") or b.get("tags", {}).get("phone", "")),
    ("Website",     lambda b, n: b.get("website") or b.get("tags", {}).get("website", "")),
    ("Score",       lambda b, n: b.get("score", "")),
    ("Category",    lambda b, n: b.get("industry", "")),
    ("Chain",       lambda b, n: "Yes" if b.get("is_chain") else "No"),
    ("Distance (mi)", lambda b, n: b.get("distance_miles", "")),
    ("Target Audience", lambda b, n: b.get("target_audience", "")),
    ("Est. Status", lambda b, n: b.get("establishment_status", "")),
    ("Notes",       lambda b, n: n.get(b.get("osm_id", ""), "")),
]


def export_shortlist_csv(
    shortlisted: list[dict],
    notes: dict,
    filepath: str,
) -> int:
    """
    Export shortlisted businesses to CSV.
    Returns the number of rows written.
    """
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([col[0] for col in EXPORT_COLUMNS])
        for business in shortlisted:
            writer.writerow([extractor(business, notes) for _, extractor in EXPORT_COLUMNS])
    return len(shortlisted)


def default_export_filename() -> str:
    """Generate a timestamped default filename for CSV export."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"redline_sponsors_{ts}.csv"


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------

def load_history() -> list:
    """Load view history from history.json. Returns [] if missing."""
    history_file = get_history_path()
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_history(history: list) -> None:
    """Persist history list to history.json."""
    try:
        with open(get_history_path(), "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def append_history_entry(history: list, business: dict) -> list:
    """Prepend a view event, cap list at 500, return updated list."""
    entry = {
        "osm_id":    business.get("osm_id", ""),
        "name":      business.get("name", ""),
        "industry":  business.get("industry", ""),
        "score":     business.get("score", 0),
        "viewed_at": datetime.now().isoformat(timespec="seconds"),
    }
    updated = [entry] + [h for h in history if h.get("osm_id") != entry["osm_id"]]
    return updated[:500]


# ---------------------------------------------------------------------------
# Saved searches persistence
# ---------------------------------------------------------------------------

def load_saved_searches() -> list:
    """Load saved searches from saved_searches.json. Returns [] if missing."""
    path = get_saved_searches_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_saved_searches(searches: list) -> None:
    """Persist saved searches list to saved_searches.json."""
    try:
        with open(get_saved_searches_path(), "w", encoding="utf-8") as f:
            json.dump(searches, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Collections persistence
# ---------------------------------------------------------------------------

def load_collections() -> dict:
    """Load collections from collections.json. Returns {} if missing.
    Dict of collection_name -> list[osm_id].
    """
    path = get_collections_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_collections(collections: dict) -> None:
    """Persist collections dict to collections.json."""
    try:
        with open(get_collections_path(), "w", encoding="utf-8") as f:
            json.dump(collections, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(businesses: list[dict], notes: dict, filepath: str) -> int:
    """Export businesses to JSON (array of objects). Returns count written."""
    rows = []
    for b in businesses:
        row = {
            "name":            b.get("name", ""),
            "address":         b.get("address", ""),
            "phone":           b.get("phone", ""),
            "website":         b.get("website", ""),
            "score":           b.get("score", 0),
            "industry":        b.get("industry", ""),
            "is_chain":        b.get("is_chain", False),
            "distance_mi":     b.get("distance_miles", 0),
            "target_audience": b.get("target_audience", ""),
            "osm_id":          b.get("osm_id", ""),
            "notes":           notes.get(b.get("osm_id", ""), ""),
        }
        rows.append(row)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    return len(rows)
