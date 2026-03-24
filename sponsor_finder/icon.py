"""
Icon loader — applies icon.png to the Tk root window (title bar + taskbar).
"""

import os
import tkinter as tk


def apply_icon(root: tk.Tk) -> None:
    """Set icon.png as the window icon for the title bar and taskbar."""
    icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
    if not os.path.isfile(icon_path):
        return
    try:
        img = tk.PhotoImage(file=icon_path)
        # True = apply as default icon for all future Toplevel windows too
        root.wm_iconphoto(True, img)
        # Keep a reference so it isn't garbage-collected
        root._icon_image = img
    except Exception:
        pass
