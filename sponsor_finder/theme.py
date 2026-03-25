"""
Theme management for Business Discovery & Scoring Tool.

Provides light and dark mode palettes and applies them via ttk.Style.
The active mode is persisted in config.json under "dark_mode".
"""

import sys
import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

LIGHT = {
    "bg":           "#f0f0f0",
    "fg":           "#000000",
    "entry_bg":     "#ffffff",
    "entry_fg":     "#000000",
    "select_bg":    "#0078d7",
    "select_fg":    "#ffffff",
    "button_bg":    "#e1e1e1",
    "frame_bg":     "#f0f0f0",
    "border":       "#cccccc",
    "trough":       "#e0e0e0",
    # Treeview
    "tree_bg":      "#ffffff",
    "tree_fg":      "#000000",
    "tree_odd":     "#f5f5f5",
    "tree_even":    "#ffffff",
    "tree_green":   "#d4efdf",
    "tree_red":     "#fadbd8",
    "tree_heading_bg": "#e8e8e8",
    # Custom widgets
    "sash_color":   "#d0d0d0",
    "detail_bg":    "#f8f8f8",
    "ai_bg":        "#f0f4ff",
    # Status dot states (unchanged by theme)
    "dot_ready":    "#27ae60",
    "dot_offline":  "#95a5a6",
    "dot_error":    "#e74c3c",
}

DARK = {
    "bg":           "#1e1e1e",
    "fg":           "#d4d4d4",
    "entry_bg":     "#2d2d2d",
    "entry_fg":     "#d4d4d4",
    "select_bg":    "#264f78",
    "select_fg":    "#ffffff",
    "button_bg":    "#3c3c3c",
    "frame_bg":     "#252526",
    "border":       "#3c3c3c",
    "trough":       "#2d2d2d",
    # Treeview
    "tree_bg":      "#1e1e1e",
    "tree_fg":      "#d4d4d4",
    "tree_odd":     "#252526",
    "tree_even":    "#1e1e1e",
    "tree_green":   "#1a3a28",
    "tree_red":     "#3a1a1a",
    "tree_heading_bg": "#2d2d2d",
    # Custom widgets
    "sash_color":   "#555555",
    "detail_bg":    "#252526",
    "ai_bg":        "#1e2540",
    # Status dot states (unchanged by theme)
    "dot_ready":    "#27ae60",
    "dot_offline":  "#95a5a6",
    "dot_error":    "#e74c3c",
}


def get_palette(dark: bool) -> dict:
    return DARK if dark else LIGHT


def _native_light_theme() -> str:
    """Return the best native theme name for the current platform."""
    available = ttk.Style().theme_names()
    if sys.platform == "win32" and "vista" in available:
        return "vista"
    if sys.platform == "darwin" and "aqua" in available:
        return "aqua"
    if "clam" in available:
        return "clam"
    return available[0]


def apply_theme(root: tk.Tk, dark: bool) -> None:
    """Apply light or dark theme to the entire application."""
    style = ttk.Style(root)
    p = get_palette(dark)

    if dark:
        # Use clam as the base — it exposes the most style options cross-platform
        style.theme_use("clam")
        _configure_dark_style(style, p)
    else:
        style.theme_use(_native_light_theme())
        # On clam (Linux), also configure light colors explicitly
        if style.theme_use() == "clam":
            _configure_light_clam(style, p)

    # Root window background
    root.configure(bg=p["bg"])


def _configure_dark_style(style: ttk.Style, p: dict) -> None:
    """Configure all ttk widget styles for dark mode."""
    bg    = p["bg"]
    fg    = p["fg"]
    ebg   = p["entry_bg"]
    efg   = p["entry_fg"]
    sbg   = p["select_bg"]
    sfg   = p["select_fg"]
    bbg   = p["button_bg"]
    bdr   = p["border"]
    trou  = p["trough"]

    style.configure(".",
        background=bg, foreground=fg,
        troughcolor=trou, bordercolor=bdr,
        focuscolor=sbg, lightcolor=bdr, darkcolor=bdr,
        relief="flat",
    )
    style.map(".", background=[("disabled", bg)], foreground=[("disabled", "#666666")])

    style.configure("TFrame",       background=bg)
    style.configure("TLabelframe",  background=bg, foreground=fg, bordercolor=bdr)
    style.configure("TLabelframe.Label", background=bg, foreground=fg)

    style.configure("TLabel",       background=bg, foreground=fg)

    style.configure("TButton",      background=bbg, foreground=fg,
                    bordercolor=bdr, focuscolor=sbg, relief="flat", padding=4)
    style.map("TButton",
        background=[("active", "#505050"), ("pressed", "#404040")],
        relief=[("pressed", "flat")],
    )

    style.configure("TEntry",       fieldbackground=ebg, foreground=efg,
                    insertcolor=efg, bordercolor=bdr, relief="flat")
    style.map("TEntry",
        fieldbackground=[("readonly", bg), ("disabled", bg)],
        foreground=[("disabled", "#666666")],
    )

    style.configure("TCombobox",    fieldbackground=ebg, foreground=efg,
                    background=bbg, selectbackground=sbg, selectforeground=sfg,
                    arrowcolor=fg, bordercolor=bdr)
    style.map("TCombobox",
        fieldbackground=[("readonly", ebg)],
        foreground=[("readonly", efg)],
    )

    style.configure("TSpinbox",     fieldbackground=ebg, foreground=efg,
                    background=bbg, arrowcolor=fg, bordercolor=bdr)

    style.configure("TScrollbar",   background=bbg, troughcolor=trou,
                    bordercolor=bdr, arrowcolor=fg, relief="flat")
    style.map("TScrollbar",
        background=[("active", "#505050"), ("disabled", bg)],
    )

    style.configure("TScale",       background=bg, troughcolor=trou,
                    bordercolor=bdr, sliderlength=16)
    style.map("TScale", background=[("active", "#505050")])

    style.configure("TCheckbutton", background=bg, foreground=fg,
                    focuscolor=sbg, indicatorcolor=ebg,
                    indicatordiameter=13)
    style.map("TCheckbutton",
        background=[("active", bg)],
        indicatorcolor=[("selected", sbg), ("pressed", sbg)],
    )

    style.configure("TRadiobutton", background=bg, foreground=fg,
                    focuscolor=sbg, indicatorcolor=ebg)
    style.map("TRadiobutton",
        background=[("active", bg)],
        indicatorcolor=[("selected", sbg)],
    )

    style.configure("TNotebook",    background=bg, bordercolor=bdr, tabmargins=0)
    style.configure("TNotebook.Tab",
        background=p["button_bg"], foreground=fg,
        padding=[8, 4], bordercolor=bdr,
    )
    style.map("TNotebook.Tab",
        background=[("selected", bg), ("active", "#404040")],
        foreground=[("selected", fg)],
        expand=[("selected", [1, 1, 1, 0])],
    )

    style.configure("TPanedwindow", background=bg)
    style.configure("Sash",         sashthickness=6, gripcount=5,
                    background=p["sash_color"])

    style.configure("TSeparator",   background=bdr)

    # Treeview
    style.configure("Treeview",
        background=p["tree_bg"], foreground=p["tree_fg"],
        fieldbackground=p["tree_bg"],
        bordercolor=bdr, relief="flat",
        rowheight=22,
    )
    style.configure("Treeview.Heading",
        background=p["tree_heading_bg"], foreground=fg,
        relief="flat", bordercolor=bdr,
    )
    style.map("Treeview",
        background=[("selected", sbg)],
        foreground=[("selected", sfg)],
    )
    style.map("Treeview.Heading",
        background=[("active", "#404040")],
    )

    # Progress bar
    style.configure("TProgressbar",
        background=sbg, troughcolor=trou,
        bordercolor=bdr,
    )

    # Menu colors (tk.Menu, not ttk — must set on menu widgets directly)
    # Stored in palette so App can apply to each menu it creates.


def _configure_light_clam(style: ttk.Style, p: dict) -> None:
    """Minimal overrides when clam is used as the light theme (Linux)."""
    style.configure(".",
        background=p["bg"], foreground=p["fg"],
        troughcolor=p["trough"],
    )
    style.configure("TFrame",      background=p["bg"])
    style.configure("TLabel",      background=p["bg"], foreground=p["fg"])
    style.configure("Treeview",
        background=p["tree_bg"], foreground=p["tree_fg"],
        fieldbackground=p["tree_bg"],
    )
    style.configure("Treeview.Heading",
        background=p["tree_heading_bg"], foreground=p["fg"],
    )
