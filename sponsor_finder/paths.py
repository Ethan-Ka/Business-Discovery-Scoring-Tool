"""
Path resolution for app data files.
Data folder is created relative to the executable (packaged) or project root (dev).
"""

import os
import shutil
import sys


def get_app_base_dir() -> str:
    """
    Return the base directory for app-local files.

    - Packaged executable: directory containing the executable
    - Source/dev mode: project root (parent of sponsor_finder package)
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))

    sponsor_finder_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(sponsor_finder_dir)


def get_data_dir() -> str:
    """
    Get the data directory path, creating it if necessary.
    The data folder is at the project root (parent of sponsor_finder).

    Returns:
        Absolute path to the data directory
    """
    data_dir = os.path.join(get_app_base_dir(), "data")

    # Create if doesn't exist
    os.makedirs(data_dir, exist_ok=True)

    # One-time best-effort migration from legacy package-local data path.
    # Copies files only when missing in the app-base data directory.
    _migrate_legacy_data_dir(data_dir)

    return data_dir


def _migrate_legacy_data_dir(data_dir: str) -> None:
    """Copy files from sponsor_finder/data -> {app_base}/data when needed."""
    legacy_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    if not os.path.isdir(legacy_data_dir):
        return

    # If source and destination are the same folder, nothing to do.
    try:
        if os.path.samefile(legacy_data_dir, data_dir):
            return
    except OSError:
        return

    for root, _, files in os.walk(legacy_data_dir):
        rel_dir = os.path.relpath(root, legacy_data_dir)
        target_root = data_dir if rel_dir == "." else os.path.join(data_dir, rel_dir)
        os.makedirs(target_root, exist_ok=True)

        for filename in files:
            src = os.path.join(root, filename)
            dst = os.path.join(target_root, filename)
            if os.path.exists(dst):
                continue
            try:
                shutil.copy2(src, dst)
            except OSError:
                continue


def get_config_path() -> str:
    """Get path to config.json in the data folder."""
    return os.path.join(get_data_dir(), "config.json")


def get_notes_path() -> str:
    """Get path to notes.json in the data folder."""
    return os.path.join(get_data_dir(), "notes.json")


def get_shortlist_path() -> str:
    """Get path to shortlist.json in the data folder."""
    return os.path.join(get_data_dir(), "shortlist.json")


def get_cache_path() -> str:
    """Get path to entity_cache.json in the data folder."""
    return os.path.join(get_data_dir(), "entity_cache.json")


def get_models_dir() -> str:
    """Get path to models directory in app-local data folder."""
    models_dir = os.path.join(get_data_dir(), "models")
    os.makedirs(models_dir, exist_ok=True)
    return models_dir


def get_profiles_dir() -> str:
    """Get profiles directory path, creating it if necessary."""
    if getattr(sys, "frozen", False):
        profiles_dir = os.path.join(get_app_base_dir(), "profiles")
    else:
        profiles_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
    os.makedirs(profiles_dir, exist_ok=True)

    # One-time best-effort migration from legacy locations:
    # 1) {script_dir}/profiles.json
    # 2) {app_base}/profiles/profiles.json
    # 3) {app_base}/profiles.json
    target_profiles = os.path.join(profiles_dir, "profiles.json")
    if not os.path.exists(target_profiles):
        legacy_candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles.json"),
            os.path.join(get_app_base_dir(), "profiles", "profiles.json"),
            os.path.join(get_app_base_dir(), "profiles.json"),
        ]
        for legacy_path in legacy_candidates:
            if not os.path.exists(legacy_path):
                continue
            try:
                shutil.copy2(legacy_path, target_profiles)
                break
            except OSError:
                continue

    return profiles_dir


def get_profiles_path() -> str:
    """Get path to profiles.json in the app-local profiles folder."""
    return os.path.join(get_profiles_dir(), "profiles.json")
