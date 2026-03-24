"""
CSV export and notes persistence.
Notes are stored in notes.json, keyed by OSM node ID.
"""

import csv
import json
import os
from datetime import datetime

from paths import get_data_dir, get_config_path, get_notes_path, get_shortlist_path, get_cache_path


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
    "last_max_results": 1000,
    "ai_settings": {
        "model": "llama3",
        "weight": 0.5,
        "explain_on": True,
        "scoring_on": False,
        "max_score": 50,
        "disable_max_limit": True,
    },
}


def ensure_data_files_exist() -> None:
    """Create app data folder and core JSON files if they do not exist."""
    get_data_dir()

    file_defaults: dict[str, object] = {
        get_config_path(): dict(_DEFAULT_CONFIG),
        get_notes_path(): {},
        get_shortlist_path(): [],
        get_cache_path(): {},
    }

    for file_path, default_value in file_defaults.items():
        if os.path.exists(file_path):
            continue
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(default_value, f, indent=2, ensure_ascii=False)
        except OSError:
            continue


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
