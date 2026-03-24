"""
Profile persistence: named search configurations the user can save and reload.

Each profile stores:
  - name          : display name
  - location      : address, lat, lon
  - radius_miles  : search radius
  - filters       : sidebar filter state dict
"""

import json
import os

try:
    from sponsor_finder.paths import get_profiles_path
except ImportError:
    from paths import get_profiles_path

PROFILES_FILE = get_profiles_path()


def _ensure_profiles_file_exists() -> None:
    """Create profiles.json with an empty list if missing or empty."""
    try:
        if not os.path.exists(PROFILES_FILE) or os.path.getsize(PROFILES_FILE) == 0:
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2, ensure_ascii=False)
    except OSError:
        # Best effort only; callers still handle read failures safely.
        pass


def load_profiles() -> list[dict]:
    """Load all profiles from profiles.json. Returns [] if file doesn't exist."""
    _ensure_profiles_file_exists()
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_profiles(profiles: list[dict]) -> None:
    """Persist the full profiles list to profiles.json."""
    try:
        _ensure_profiles_file_exists()
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
    except OSError as e:
        raise RuntimeError(f"Could not save profiles: {e}") from e


def get_profile(profiles: list[dict], name: str) -> dict | None:
    """Find a profile by name. Returns None if not found."""
    for p in profiles:
        if p.get("name") == name:
            return p
    return None


def upsert_profile(profiles: list[dict], profile: dict) -> list[dict]:
    """
    Insert or update a profile in the list (matched by name).
    Returns the updated list.
    """
    name = profile.get("name", "")
    for i, p in enumerate(profiles):
        if p.get("name") == name:
            profiles[i] = profile
            return profiles
    profiles.append(profile)
    return profiles


def delete_profile(profiles: list[dict], name: str) -> list[dict]:
    """Remove the profile with the given name. Returns the updated list."""
    return [p for p in profiles if p.get("name") != name]
