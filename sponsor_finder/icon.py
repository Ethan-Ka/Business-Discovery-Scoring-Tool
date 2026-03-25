"""Icon loader for development and packaged (PyInstaller) runs."""

import os
import sys
import tkinter as tk


def _resource_candidates(filename: str) -> list[str]:
    """Return possible resource paths for source and frozen runs."""
    here = os.path.dirname(__file__)
    candidates = [
        os.path.join(here, filename),
        os.path.join(here, "sponsor_finder", filename),
    ]

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        exe_dir = os.path.dirname(sys.executable)
        for base in (meipass, exe_dir):
            if not base:
                continue
            candidates.extend([
                os.path.join(base, filename),
                os.path.join(base, "sponsor_finder", filename),
            ])

    seen = set()
    unique = []
    for path in candidates:
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(path)
    return unique


def _first_existing(filename: str) -> str | None:
    for path in _resource_candidates(filename):
        if os.path.isfile(path):
            return path
    return None


def apply_icon(root: tk.Tk) -> None:
    """Set app icon for title bar/taskbar with Windows .ico preference."""
    ico_path = _first_existing("icon.ico")
    png_path = _first_existing("icon.png")

    try:
        if os.name == "nt" and ico_path:
            root.iconbitmap(default=ico_path)
    except Exception:
        pass

    try:
        if png_path:
            img = tk.PhotoImage(file=png_path)
            root.wm_iconphoto(True, img)
            root._icon_image = img
    except Exception:
        pass
