"""
Profile Editor — full Tkinter dialog for create/edit business discovery profiles.

Provides tabbed interface for:
  - General (name, description)
  - Scoring Rules (rule builder table with operators)
  - Audience (keyword chip input)
  - Filters (default filter settings)
  - Export (column picker with drag-to-reorder)
  - Sources (data source checkboxes)
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------

class Tooltip:
    """
    Lightweight hover tooltip for any Tkinter widget.
    Shows after a short delay; dismisses on mouse leave or click.
    """
    _DELAY_MS = 400
    _BG = "#fffbe6"
    _FG = "#333333"
    _WRAPLENGTH = 320

    def __init__(self, widget, text: str):
        self._widget = widget
        self._text = text
        self._tip_window = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        widget.bind("<ButtonPress>", self._cancel, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self._widget.after(self._DELAY_MS, self._show)

    def _cancel(self, _event=None):
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None

    def _show(self):
        if self._tip_window or not self._text:
            return
        x = self._widget.winfo_rootx() + 16
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(
            tw, text=self._text,
            background=self._BG, foreground=self._FG,
            relief="solid", borderwidth=1,
            wraplength=self._WRAPLENGTH,
            justify="left", padx=8, pady=5,
            font=("Segoe UI", 9),
        )
        lbl.pack()
        self._tip_window = tw


# ---------------------------------------------------------------------------
# Field reference
# ---------------------------------------------------------------------------

# Per-field help: shown in the hint bar when a scoring rule field is selected.
FIELD_HELP: dict[str, str] = {
    "industry": (
        "AI-inferred industry label (human-readable).\n"
        "Set by AI from the raw OSM tags — more readable than category.\n\n"
        "Example values:  Auto Parts · Car Wash · Tire Shop · Performance Shop\n"
        "                 Fast Food · Brewery · Tattoo Studio · Gas Station\n\n"
        "Operators:  = for exact match  |  contains for partial match"
    ),
    "category": (
        "Raw OSM tag value assigned by map contributors.\n"
        "More specific than industry but uses OpenStreetMap's internal vocabulary.\n\n"
        "Example values:  fuel · fast_food · car_repair · supermarket\n"
        "                 bar · convenience · car_wash · tyres\n\n"
        "Operators:  = for exact match  |  contains for partial match"
    ),
    "entity_type": (
        "Classified business type based on chain confidence and location count.\n\n"
        "Exact values (use = operator):\n"
        "  Local            — chain confidence < 30%\n"
        "  Unknown          — chain confidence 30–59%\n"
        "  Regional Chain   — confidence ≥ 60%, < 10 locations\n"
        "  National Chain   — confidence ≥ 60%, 10–99 locations\n"
        "  Franchise        — confidence ≥ 60%, 100+ locations"
    ),
    "is_chain": (
        "True when chain confidence is 60% or higher, False otherwise.\n\n"
        "Values:  true  |  false\n\n"
        "Tip: Rule  is_chain = false  rewards local independents —\n"
        "a common high-value signal for event sponsorship."
    ),
    "chain_confidence": (
        "How confident the app is that this is a chain business (0–100).\n\n"
        "How the score is built:\n"
        "  95  — OSM brand:wikidata tag present\n"
        "  75  — OSM brand tag present\n"
        "  70  — franchise tag present\n"
        "  80  — Wikidata description matches chain keywords\n"
        "   0  — no chain signals found\n\n"
        "Operators:  < · > · <= · >= · = · !="
    ),
    "has_website": (
        "True if the business has a website listed in OpenStreetMap.\n\n"
        "Values:  true  |  false\n\n"
        "Good proxy for professionalism. Businesses with websites are\n"
        "easier to contact and more likely to have a marketing budget."
    ),
    "has_phone": (
        "True if the business has a phone number in OpenStreetMap.\n\n"
        "Values:  true  |  false\n\n"
        "Most businesses with a physical presence have a phone listed."
    ),
    "has_email": (
        "True if the business has an email address in OpenStreetMap.\n\n"
        "Values:  true  |  false\n\n"
        "Rarer than phone — most OSM listings omit email.\n"
        "A strong positive signal when present."
    ),
    "has_opening_hours": (
        "True if the business has opening hours in OpenStreetMap.\n\n"
        "Values:  true  |  false\n\n"
        "Indicates an actively maintained OSM listing,\n"
        "which often correlates with an engaged local business."
    ),
    "osm_completeness": (
        "Percentage of expected OSM fields that are filled in (0–100).\n\n"
        "Fields checked: name · phone · email · website\n"
        "                opening_hours · street · city\n\n"
        "Score = (fields present ÷ 7) × 100\n\n"
        "Operators:  > 50  to filter out sparse listings\n"
        "            > 70  for well-documented businesses"
    ),
    "distance_mi": (
        "Distance from the search center in miles (decimal).\n\n"
        "Distance rules are mutually exclusive — when multiple distance\n"
        "rules match, only the best (highest points) tier scores.\n\n"
        "Typical pattern — add three rules:\n"
        "  distance_mi < 2   →  15 pts  (very close)\n"
        "  distance_mi < 5   →  10 pts  (nearby)\n"
        "  distance_mi < 10  →   5 pts  (within range)"
    ),
    "audience_overlap": (
        "AI-inferred description of who shops or visits this business.\n\n"
        "Example values:\n"
        "  'Car enthusiasts, mechanics'\n"
        "  'Families, commuters'\n"
        "  'Young adults, sports fans'\n\n"
        "Operator:  contains  to match on a keyword\n"
        "Example:   audience_overlap contains car  →  +15 pts"
    ),
    "num_locations": (
        "Estimated number of locations from Wikidata (integer).\n\n"
        "0 or blank = unknown (Wikidata had no data).\n"
        "Only populated when a Wikidata match is found.\n\n"
        "Example rules:\n"
        "  num_locations < 5    — very small / micro-chain\n"
        "  num_locations < 20   — regional presence only\n"
        "  num_locations is empty — no Wikidata data at all"
    ),
    "parent_company": (
        "Parent company name if known, sourced from Wikidata.\n\n"
        "Example values:  'Yum! Brands' · '7-Eleven Inc.' · 'Berkshire Hathaway'\n\n"
        "Operators:  contains · is empty · is not empty\n\n"
        "Tip: Use  parent_company is empty  to reward businesses\n"
        "that aren't subsidiaries of a larger corporation."
    ),
    "founded_year": (
        "Year the business was founded (4-digit integer), from Wikidata.\n\n"
        "Only populated when a Wikidata entity is found.\n\n"
        "Example rules:\n"
        "  founded_year > 1990  — established but not ancient\n"
        "  founded_year is empty — no founding data available\n\n"
        "Operators:  < · > · <= · >= · = · !="
    ),
    "wikidata_description": (
        "Raw description text from Wikidata for this business.\n\n"
        "Example values:\n"
        "  'American fast food restaurant chain'\n"
        "  'Regional automotive parts retailer'\n\n"
        "Operator:  contains  to keyword-match the description\n"
        "Only present when a Wikidata entity was found."
    ),
}


# ---------------------------------------------------------------------------
# Field types for operator selection
# ---------------------------------------------------------------------------

FIELD_TYPES = {
    "industry":             "string",
    "category":             "string",
    "audience_overlap":     "string",
    "parent_company":       "string",
    "entity_type":          "string",
    "wikidata_description": "string",
    "is_chain":             "bool",
    "has_website":          "bool",
    "has_email":            "bool",
    "has_phone":            "bool",
    "has_opening_hours":    "bool",
    "chain_confidence":     "numeric",
    "num_locations":        "numeric",
    "osm_completeness":     "numeric",
    "distance_mi":          "numeric",
    "founded_year":         "numeric",
}

AVAILABLE_FIELDS = list(FIELD_TYPES.keys())

STRING_OPERATORS  = ["=", "!=", "contains", "not contains", "is empty", "is not empty"]
NUMERIC_OPERATORS = [">", "<", ">=", "<=", "=", "!=", "is empty", "is not empty"]
BOOL_OPERATORS    = ["=", "!="]

ALL_SOURCES          = ["overpass", "wikidata", "google_places", "yelp"]
SOURCES_REQUIRE_KEY  = {"google_places", "yelp"}

AVAILABLE_EXPORT_COLUMNS = [
    "Name", "Score", "Industry", "Entity Type", "Chain", "Distance", "Phone",
    "Email", "Website", "Address", "Category", "Audience", "OSM Completeness",
    "Chain Confidence", "Num Locations", "Founded Year", "AI Insight", "Notes"
]

# Human-readable names for the field dropdown
FIELD_DISPLAY_NAMES = {
    "industry":             "Industry",
    "category":             "Category (OSM)",
    "entity_type":          "Entity Type",
    "is_chain":             "Is Chain",
    "chain_confidence":     "Chain Confidence",
    "has_website":          "Has Website",
    "has_phone":            "Has Phone",
    "has_email":            "Has Email",
    "has_opening_hours":    "Has Opening Hours",
    "osm_completeness":     "OSM Completeness",
    "distance_mi":          "Distance (mi)",
    "audience_overlap":     "Audience Overlap",
    "num_locations":        "Num Locations",
    "parent_company":       "Parent Company",
    "founded_year":         "Founded Year",
    "wikidata_description": "Wikidata Description",
}
FIELD_INTERNAL = {v: k for k, v in FIELD_DISPLAY_NAMES.items()}
FIELD_DISPLAY_LIST = [FIELD_DISPLAY_NAMES[f] for f in AVAILABLE_FIELDS]


# ---------------------------------------------------------------------------
# Shared UI helpers
# ---------------------------------------------------------------------------

def _info_icon(parent, tooltip_text: str, padx=(4, 0)) -> ttk.Label:
    """
    Return a small ⓘ label with a hover tooltip attached.
    Attach to a row/frame with .pack(side="left", padx=padx).
    """
    lbl = ttk.Label(parent, text="ⓘ", foreground="#5b9bd5", cursor="question_arrow",
                    font=("Segoe UI", 9))
    Tooltip(lbl, tooltip_text)
    return lbl


def _section_banner(parent, text: str) -> ttk.Frame:
    """
    A subtle info banner (light blue-gray background) at the top of a tab.
    Returns the frame so the caller can pack it.
    """
    frm = tk.Frame(parent, background="#eaf1fb", padx=10, pady=6)
    tk.Label(
        frm, text=text,
        background="#eaf1fb", foreground="#1a3a5c",
        font=("Segoe UI", 9), justify="left", wraplength=760,
        anchor="w",
    ).pack(fill="x")
    return frm


# ---------------------------------------------------------------------------
# Scrollable tab container
# ---------------------------------------------------------------------------

class ScrollableTab(ttk.Frame):
    """Simple vertical scroll container for tab content."""
    def __init__(self, parent):
        super().__init__(parent)

        self._canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self._vscroll = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)

        self.content = ttk.Frame(self._canvas)
        self._window_id = self._canvas.create_window((0, 0), window=self.content, anchor="nw")

        self._canvas.pack(side="left", fill="both", expand=True)
        self._vscroll.pack(side="right", fill="y")

        self.content.bind("<Configure>", self._on_content_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._canvas.bind("<Enter>", self._bind_mousewheel)
        self._canvas.bind("<Leave>", self._unbind_mousewheel)

    def _on_content_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfigure(self._window_id, width=event.width)

    def _bind_mousewheel(self, _event=None):
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind_all("<Button-4>", self._on_mousewheel)
        self._canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event=None):
        self._canvas.unbind_all("<MouseWheel>")
        self._canvas.unbind_all("<Button-4>")
        self._canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
            return
        if event.num == 5:
            self._canvas.yview_scroll(1, "units")
            return
        delta = int(-1 * (event.delta / 120)) if event.delta else 0
        if delta:
            self._canvas.yview_scroll(delta, "units")


# ---------------------------------------------------------------------------
# Rule builder widget
# ---------------------------------------------------------------------------

class RuleBuilderWidget(ttk.Frame):
    """
    Table-like widget for editing scoring rules.
    Each rule: Field | Operator | Value (adapted by field type) | Points | Delete
    Includes a live hint bar that describes the selected field.
    """
    def __init__(self, parent, hint_var: tk.StringVar | None = None):
        super().__init__(parent)
        self.rules = []
        # Use an externally supplied StringVar (right-panel mode) or create one (inline mode).
        self._hint_var = hint_var if hint_var is not None else tk.StringVar(
            value="← Select a field to see valid values and examples.")
        self._hint_external = hint_var is not None
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        # Column headers with tooltips
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 4))

        hdr_field = ttk.Label(header, text="Field", width=18, relief="solid", borderwidth=1)
        hdr_field.pack(side="left", padx=1)
        Tooltip(hdr_field, "What attribute of the business to evaluate.\nClick a row's field dropdown to see valid values in the hint below.")

        hdr_op = ttk.Label(header, text="Operator", width=12, relief="solid", borderwidth=1)
        hdr_op.pack(side="left", padx=1)
        Tooltip(hdr_op,
            "How to compare the field value:\n\n"
            "=  !=          exact match / not equal\n"
            ">  <  >=  <=   numeric comparison\n"
            "contains       field text includes this string\n"
            "not contains   field text does not include this\n"
            "is empty       field has no value\n"
            "is not empty   field has any value\n\n"
            "Available operators depend on field type."
        )

        hdr_val = ttk.Label(header, text="Value", width=20, relief="solid", borderwidth=1)
        hdr_val.pack(side="left", padx=1)
        Tooltip(hdr_val, "The value to compare against.\nFor bool fields: true or false.\nFor numeric: a number (decimals allowed).\nFor text fields: the exact or partial string to match.")

        hdr_pts = ttk.Label(header, text="Pts", width=4, relief="solid", borderwidth=1)
        hdr_pts.pack(side="left", padx=1)
        Tooltip(hdr_pts, "Points awarded when this rule matches (0–100).\nAll matching rules are added up, then capped at 100 total.")

        ttk.Label(header, text="", width=2, relief="solid", borderwidth=1).pack(side="left", padx=1)

        # Rules container
        self.rules_container = ttk.Frame(self)
        self.rules_container.pack(fill="both", expand=True)

        # Add rule button
        btn_frm = ttk.Frame(self)
        btn_frm.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_frm, text="+ Add Rule", command=self._add_rule).pack(side="left")
        ttk.Button(btn_frm, text="Clear All", command=self._clear_all).pack(side="left", padx=(6, 0))

        # Inline hint bar — only built when there is no external right-panel hint target.
        if not self._hint_external:
            hint_frm = tk.Frame(self, background="#f5f5f5", padx=8, pady=6)
            hint_frm.pack(fill="x", pady=(8, 0))
            tk.Label(
                hint_frm, text="Field reference:", font=("Segoe UI", 8, "bold"),
                background="#f5f5f5", foreground="#444",
            ).pack(anchor="w")
            tk.Label(
                hint_frm, textvariable=self._hint_var,
                background="#f5f5f5", foreground="#555",
                font=("Segoe UI", 8), justify="left", wraplength=700, anchor="nw",
            ).pack(anchor="w")

    def _update_hint(self, field_internal: str):
        help_text = FIELD_HELP.get(field_internal)
        if help_text:
            self._hint_var.set(help_text)
        else:
            self._hint_var.set("← Select a field to see valid values and examples.")

    def set_rules(self, rules: list[dict]):
        self.rules = [dict(r) for r in rules]
        self._refresh()

    def get_rules(self) -> list[dict]:
        return [dict(r) for r in self.rules]

    def _add_rule(self):
        self.rules.append({
            "field": "industry",
            "operator": "=",
            "value": "",
            "points": 10
        })
        self._refresh()
        self._update_hint("industry")

    def _remove_rule(self, idx: int):
        del self.rules[idx]
        self._refresh()

    def _clear_all(self):
        if self.rules and messagebox.askyesno("Clear Rules", "Remove all scoring rules?"):
            self.rules.clear()
            self._refresh()

    def _refresh(self):
        for w in self.rules_container.winfo_children():
            w.destroy()

        for idx, rule in enumerate(self.rules):
            row = ttk.Frame(self.rules_container)
            row.pack(fill="x", pady=1)

            # Resolve stored internal field name for display
            stored_field = rule.get("field", "industry")
            display_field = FIELD_DISPLAY_NAMES.get(stored_field, stored_field)

            field_var = tk.StringVar(value=display_field)
            op_var    = tk.StringVar(value=rule.get("operator", "="))
            val_var   = tk.StringVar(value=str(rule.get("value", "")))
            pts_var   = tk.StringVar(value=str(rule.get("points", 10)))

            field_combo = ttk.Combobox(
                row, textvariable=field_var,
                values=FIELD_DISPLAY_LIST,
                width=18, state="readonly",
            )
            field_combo.pack(side="left", padx=1)

            op_combo = ttk.Combobox(row, textvariable=op_var, state="readonly", width=12)
            op_combo.pack(side="left", padx=1)

            val_entry = ttk.Entry(row, textvariable=val_var, width=18)
            val_entry.pack(side="left", padx=1)

            pts_spin = ttk.Spinbox(row, textvariable=pts_var, from_=0, to=100, width=4)
            pts_spin.pack(side="left", padx=1)

            del_btn = ttk.Button(row, text="✕", width=2,
                                 command=lambda i=idx: self._remove_rule(i))
            del_btn.pack(side="left", padx=1)

            # Set initial operators based on current field
            self._update_op_combo(op_combo, op_var, stored_field)

            def _get_internal(fv):
                return FIELD_INTERNAL.get(fv.get(), fv.get())

            def make_field_updater(i, fv, ov, vv, pv, oc):
                def _upd(*_):
                    internal = _get_internal(fv)
                    self._update_op_combo(oc, ov, internal)
                    self._update_hint(internal)
                    self._sync_rule(i, fv, ov, vv, pv)
                return _upd

            field_var.trace_add("write", make_field_updater(idx, field_var, op_var, val_var, pts_var, op_combo))
            op_var.trace_add("write",  lambda *_, i=idx, fv=field_var, ov=op_var, vv=val_var, pv=pts_var: self._sync_rule(i, fv, ov, vv, pv))
            val_var.trace_add("write", lambda *_, i=idx, fv=field_var, ov=op_var, vv=val_var, pv=pts_var: self._sync_rule(i, fv, ov, vv, pv))
            pts_var.trace_add("write", lambda *_, i=idx, fv=field_var, ov=op_var, vv=val_var, pv=pts_var: self._sync_rule(i, fv, ov, vv, pv))

            # Clicking the field combo or value entry focuses the hint on this row's field.
            # <<ComboboxSelected>> fires even when the same value is re-selected (trace doesn't).
            # <FocusIn> fires on click/tab so the hint is always in sync with the active row.
            field_combo.bind("<<ComboboxSelected>>", lambda _, fv=field_var: self._update_hint(_get_internal(fv)))
            field_combo.bind("<FocusIn>",            lambda _, fv=field_var: self._update_hint(_get_internal(fv)))
            val_entry.bind("<FocusIn>",              lambda _, fv=field_var: self._update_hint(_get_internal(fv)))

            # Show hint for first row's field on initial load
            if idx == 0:
                self._update_hint(stored_field)

    def _update_op_combo(self, op_combo: ttk.Combobox, op_var: tk.StringVar, internal_field: str):
        ftype = FIELD_TYPES.get(internal_field, "string")
        if ftype == "numeric":
            ops = NUMERIC_OPERATORS
        elif ftype == "bool":
            ops = BOOL_OPERATORS
        else:
            ops = STRING_OPERATORS
        op_combo["values"] = ops
        if op_var.get() not in ops:
            op_var.set(ops[0])

    def _sync_rule(self, idx: int, fv: tk.StringVar, ov: tk.StringVar,
                   vv: tk.StringVar, pv: tk.StringVar):
        if idx < len(self.rules):
            display = fv.get()
            internal = FIELD_INTERNAL.get(display, display)
            ftype = FIELD_TYPES.get(internal, "string")
            self.rules[idx] = {
                "field":    internal,
                "operator": ov.get(),
                "value":    parse_value(ftype, vv.get()),
                "points":   int(pv.get() or 10),
            }


# ---------------------------------------------------------------------------
# Audience keywords widget
# ---------------------------------------------------------------------------

class AudienceKeywordsWidget(ttk.Frame):
    """Keyword chip input: type + Enter to add, click chip to remove. Chips wrap to new rows."""
    def __init__(self, parent):
        super().__init__(parent)
        self.keywords = []
        self._last_reflow_width = -1
        self._build_ui()

    def _build_ui(self):
        input_frm = ttk.Frame(self)
        input_frm.pack(fill="x", pady=(0, 8))
        ttk.Label(input_frm, text="Add keyword:").pack(side="left")
        self.input_var = tk.StringVar()
        self.input_entry = ttk.Entry(input_frm, textvariable=self.input_var, width=24)
        self.input_entry.pack(side="left", padx=4)
        self.input_entry.bind("<Return>", self._add_keyword)
        ttk.Button(input_frm, text="Add", command=self._add_keyword).pack(side="left", padx=(0, 4))

        self.chips_frame = ttk.Frame(self)
        self.chips_frame.pack(fill="x")
        self.chips_frame.bind("<Configure>", self._on_configure)

    def _on_configure(self, event):
        if event.width != self._last_reflow_width:
            self._last_reflow_width = event.width
            self._reflow(event.width)

    def set_keywords(self, keywords: list[str]):
        self.keywords = list(keywords)
        self._refresh()

    def get_keywords(self) -> list[str]:
        return list(self.keywords)

    def _add_keyword(self, *_):
        kw = self.input_var.get().strip()
        if kw and kw not in self.keywords:
            self.keywords.append(kw)
            self.input_var.set("")
            self._refresh()

    def _remove_keyword(self, kw: str):
        if kw in self.keywords:
            self.keywords.remove(kw)
            self._refresh()

    def _refresh(self):
        self._last_reflow_width = -1  # force reflow on next configure
        for w in self.chips_frame.winfo_children():
            w.destroy()
        self.after_idle(self._reflow_idle)

    def _reflow_idle(self):
        w = self.chips_frame.winfo_width()
        self._reflow(w if w > 1 else 400)

    def _reflow(self, available: int):
        for w in self.chips_frame.winfo_children():
            w.destroy()

        if not self.keywords:
            return

        row = ttk.Frame(self.chips_frame)
        row.pack(fill="x", anchor="w")
        row_w = 0

        for kw in self.keywords:
            # Estimate chip width: ~7px per character + padding + × button
            chip_w = len(kw) * 7 + 48
            if row_w + chip_w > available and row_w > 0:
                row = ttk.Frame(self.chips_frame)
                row.pack(fill="x", anchor="w", pady=(2, 0))
                row_w = 0

            chip = tk.Frame(row, bg="#dde8f5", relief="flat", bd=0)
            chip.pack(side="left", padx=(0, 4), pady=2)
            tk.Label(
                chip, text=kw, bg="#dde8f5", fg="#1a3a5c",
                font=("Segoe UI", 9), padx=6, pady=3,
            ).pack(side="left")
            tk.Button(
                chip, text="×", bg="#dde8f5", fg="#5a7a9c",
                relief="flat", bd=0, padx=4, pady=2,
                font=("Segoe UI", 10, "bold"), cursor="hand2",
                activebackground="#c5d8ee", activeforeground="#1a3a5c",
                command=lambda k=kw: self._remove_keyword(k),
            ).pack(side="left")
            row_w += chip_w + 4


# ---------------------------------------------------------------------------
# Export columns widget
# ---------------------------------------------------------------------------

class ExportColumnsWidget(ttk.Frame):
    """Column picker with checkboxes and up/down reorder buttons."""
    def __init__(self, parent):
        super().__init__(parent)
        self.selected_columns = []
        self._build_ui()

    def _build_ui(self):
        left_frame  = ttk.Frame(self)
        left_frame.pack(side="left", fill="both", expand=True)
        right_frame = ttk.Frame(self)
        right_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

        ttk.Label(left_frame, text="Available:").pack(anchor="w")
        self.available_listbox = tk.Listbox(left_frame, height=12)
        self.available_listbox.pack(fill="both", expand=True)

        ttk.Label(right_frame, text="Selected (exported in order):").pack(anchor="w")
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(anchor="e", pady=(0, 4))
        ttk.Button(btn_frame, text="↑", width=3, command=self._move_up).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="↓", width=3, command=self._move_down).pack(side="left", padx=2)

        self.selected_listbox = tk.Listbox(right_frame, height=12)
        self.selected_listbox.pack(fill="both", expand=True)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Add >>",    command=self._add_column).pack(side="left", padx=2)
        ttk.Button(btn_row, text="<< Remove", command=self._remove_column).pack(side="left", padx=2)

    def set_columns(self, columns: list[str]):
        self.selected_columns = list(columns)
        self._refresh()

    def get_columns(self) -> list[str]:
        return list(self.selected_columns)

    def _refresh(self):
        self.available_listbox.delete(0, tk.END)
        self.selected_listbox.delete(0, tk.END)
        for col in AVAILABLE_EXPORT_COLUMNS:
            if col not in self.selected_columns:
                self.available_listbox.insert(tk.END, col)
        for col in self.selected_columns:
            self.selected_listbox.insert(tk.END, col)

    def _add_column(self):
        sel = self.available_listbox.curselection()
        if sel:
            self.selected_columns.append(self.available_listbox.get(sel[0]))
            self._refresh()

    def _remove_column(self):
        sel = self.selected_listbox.curselection()
        if sel:
            col = self.selected_listbox.get(sel[0])
            if col in self.selected_columns:
                self.selected_columns.remove(col)
            self._refresh()

    def _move_up(self):
        sel = self.selected_listbox.curselection()
        if sel and sel[0] > 0:
            idx = sel[0]
            self.selected_columns[idx], self.selected_columns[idx - 1] = \
                self.selected_columns[idx - 1], self.selected_columns[idx]
            self._refresh()
            self.selected_listbox.selection_set(idx - 1)

    def _move_down(self):
        sel = self.selected_listbox.curselection()
        if sel and sel[0] < len(self.selected_columns) - 1:
            idx = sel[0]
            self.selected_columns[idx], self.selected_columns[idx + 1] = \
                self.selected_columns[idx + 1], self.selected_columns[idx]
            self._refresh()
            self.selected_listbox.selection_set(idx + 1)


# ---------------------------------------------------------------------------
# Sources widget
# ---------------------------------------------------------------------------

_SOURCE_DESCRIPTIONS = {
    "overpass":      "OpenStreetMap / Overpass — core business data, always enabled",
    "wikidata":      "Wikidata — chain detection, entity intelligence, founding year",
    "google_places": "Google Places — ratings, review count, richer business data (API key required)",
    "yelp":          "Yelp Fusion — ratings, price level, review snippets (API key required)",
}

_SOURCE_TOOLTIPS = {
    "overpass": (
        "Queries OpenStreetMap via the Overpass API.\n"
        "Always enabled — this is the primary data source.\n"
        "Returns business name, address, phone, website, and OSM category tags."
    ),
    "wikidata": (
        "Looks up businesses in Wikidata to detect chains.\n"
        "Provides: chain confidence, num_locations, parent_company, founded_year.\n"
        "Results are cached — each unique business is only looked up once."
    ),
    "google_places": (
        "Enriches results with Google Places data.\n"
        "Adds: star rating, review count, price level, photos.\n"
        "Requires a Google Places API key (set in Settings → Data Sources)."
    ),
    "yelp": (
        "Enriches results with Yelp Fusion data.\n"
        "Adds: Yelp rating, review count, price level, categories.\n"
        "Requires a Yelp Fusion API key (set in Settings → Data Sources)."
    ),
}

class SourceCheckboxesWidget(ttk.Frame):
    """Checkboxes for each available data source with descriptions and tooltips."""
    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.enabled_sources = []
        self._build_ui()

    def _build_ui(self):
        for source in ALL_SOURCES:
            var = tk.BooleanVar()
            row = ttk.Frame(self)
            row.pack(anchor="w", pady=4, fill="x")

            cb = ttk.Checkbutton(
                row, text="", variable=var,
                command=lambda s=source, v=var: self._update_sources(s, v),
            )
            cb.pack(side="left")

            lbl = ttk.Label(row, text=_SOURCE_DESCRIPTIONS.get(source, source))
            lbl.pack(side="left")

            icon = _info_icon(row, _SOURCE_TOOLTIPS.get(source, ""))
            icon.pack(side="left", padx=(4, 0))

            if source in SOURCES_REQUIRE_KEY:
                ttk.Label(row, text="  ⚠ API key required",
                          foreground="#c0392b", font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))

            setattr(self, f"{source}_var", var)

    def set_sources(self, sources: list[str]):
        self.enabled_sources = list(sources)
        for source in ALL_SOURCES:
            getattr(self, f"{source}_var").set(source in self.enabled_sources)

    def get_sources(self) -> list[str]:
        return [s for s in ALL_SOURCES if getattr(self, f"{s}_var").get()]

    def _update_sources(self, source: str, var: tk.BooleanVar):
        if var.get():
            if source not in self.enabled_sources:
                self.enabled_sources.append(source)
        else:
            if source in self.enabled_sources:
                self.enabled_sources.remove(source)


# ---------------------------------------------------------------------------
# Profile editor dialog
# ---------------------------------------------------------------------------

class ProfileEditorDialog(tk.Toplevel):
    """
    Full profile editor with tabbed interface.
    Pass a profile dict to edit it, or None to create a new profile.
    """
    def __init__(self, parent, profile: Optional[dict] = None):
        super().__init__(parent)
        self.title("Profile Editor")
        self.geometry("900x700")
        self.resizable(True, True)
        self.grab_set()

        self._original_profile = profile
        self._result_profile = None

        if profile:
            self.name              = profile.get("name", "")
            self.description       = profile.get("description", "")
            self.scoring_rules     = profile.get("scoring_rules", [])
            self.audience_keywords = profile.get("audience_keywords", [])
            self.default_filters   = profile.get("default_filters", {})
            self.export_columns    = profile.get("export_columns", [])
            self.data_sources      = profile.get("data_sources", [])
        else:
            self.name              = ""
            self.description       = ""
            self.scoring_rules     = []
            self.audience_keywords = []
            self.default_filters   = {}
            self.export_columns    = list(AVAILABLE_EXPORT_COLUMNS[:8])
            self.data_sources      = ["overpass", "wikidata"]

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._confirm_close)

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        notebook = ttk.Notebook(frm)
        notebook.pack(fill="both", expand=True)

        self._tab_general  = ScrollableTab(notebook)
        self._tab_scoring  = ttk.Frame(notebook)
        self._tab_audience = ScrollableTab(notebook)
        self._tab_filters  = ScrollableTab(notebook)
        self._tab_export   = ScrollableTab(notebook)
        self._tab_sources  = ScrollableTab(notebook)

        notebook.add(self._tab_general,  text="General")
        notebook.add(self._tab_scoring,  text="Scoring Rules")
        notebook.add(self._tab_audience, text="Audience")
        notebook.add(self._tab_filters,  text="Filters")
        notebook.add(self._tab_export,   text="Export")
        notebook.add(self._tab_sources,  text="Sources")

        self._build_general_tab()
        self._build_scoring_tab()
        self._build_audience_tab()
        self._build_filters_tab()
        self._build_export_tab()
        self._build_sources_tab()

        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_frm, text="Save",   command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_frm, text="Cancel", command=self._confirm_close).pack(side="right")

    @staticmethod
    def _tab_body(tab):
        return getattr(tab, "content", tab)

    # ── General ─────────────────────────────────────────────────────────────

    def _build_general_tab(self):
        body = self._tab_body(self._tab_general)

        banner = _section_banner(body,
            "A profile stores your scoring rules, filters, and export settings. "
            "Switch between profiles instantly from the top bar to target different types of businesses."
        )
        banner.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12), padx=4)

        # Name
        name_row = ttk.Frame(body)
        name_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=4, padx=4)
        ttk.Label(name_row, text="Name:").pack(side="left")
        _info_icon(name_row,
            "The profile name shown in the profile selector dropdown.\n"
            "Keep it short and descriptive, e.g. 'Car Meet Sponsors' or 'Restaurant Outreach'."
        ).pack(side="left", padx=(4, 8))
        self.name_var = tk.StringVar(value=self.name)
        ttk.Entry(name_row, textvariable=self.name_var, width=55).pack(side="left", fill="x", expand=True)

        # Description
        desc_row = ttk.Frame(body)
        desc_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 2), padx=4)
        ttk.Label(desc_row, text="Description:").pack(side="left")
        _info_icon(desc_row,
            "Used directly in AI prompts when generating insights and scores.\n\n"
            "The more specific you are, the better the AI explanations.\n\n"
            "Good:  'Find local independent businesses to sponsor a weekend car meet in Flower Mound, TX'\n"
            "Weak:  'Business outreach'"
        ).pack(side="left", padx=(4, 0))

        self.desc_text = tk.Text(body, height=6, width=60)
        self.desc_text.insert("1.0", self.description)
        self.desc_text.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=4, padx=4)

        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

    # ── Scoring Rules ────────────────────────────────────────────────────────

    def _build_scoring_tab(self):
        outer = self._tab_scoring  # plain ttk.Frame added to notebook

        # ── Right panel: fixed "Field Reference" column ───────────────────────
        right = tk.Frame(outer, background="#f5f5f5", width=240)
        right.pack(side="right", fill="y", padx=(4, 6), pady=6)
        right.pack_propagate(False)

        tk.Label(
            right, text="Field Reference", font=("Segoe UI", 9, "bold"),
            background="#f5f5f5", foreground="#333",
        ).pack(anchor="w", padx=8, pady=(8, 4))

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=8, pady=(0, 6))

        hint_var = tk.StringVar(value="Select a field in any rule to see\nvalid values and examples here.")
        hint_label = tk.Label(
            right, textvariable=hint_var,
            background="#f5f5f5", foreground="#555",
            font=("Segoe UI", 8), justify="left", wraplength=210, anchor="nw",
        )
        hint_label.pack(anchor="nw", padx=8, fill="x")

        # ── Left panel: scrollable rules area ────────────────────────────────
        left = ScrollableTab(outer)
        left.pack(side="left", fill="both", expand=True)
        body = left.content

        banner = _section_banner(body,
            "Rules add points to each business's score (max 100). "
            "All matching rules stack. "
            "For distance rules, only the highest-tier match scores — "
            "so you can safely add < 2 mi, < 5 mi, and < 10 mi rules without double-counting."
        )
        banner.pack(fill="x", pady=(0, 10), padx=4)

        self.rules_widget = RuleBuilderWidget(body, hint_var=hint_var)
        self.rules_widget.pack(fill="both", expand=True, padx=4)
        self.rules_widget.set_rules(self.scoring_rules)

    # ── Audience ─────────────────────────────────────────────────────────────

    def _build_audience_tab(self):
        body = self._tab_body(self._tab_audience)

        banner = _section_banner(body,
            "Keywords that describe your target audience or event theme. "
            "Used in AI prompts and to populate the 'Audience Overlap' field on each business. "
            "A business whose inferred audience matches a keyword scores higher."
        )
        banner.pack(fill="x", pady=(0, 10), padx=4)

        hint_frm = ttk.Frame(body)
        hint_frm.pack(fill="x", padx=4, pady=(0, 8))
        ttk.Label(hint_frm, text="Examples:", font=("Segoe UI", 9, "italic"),
                  foreground="#555").pack(side="left")
        ttk.Label(hint_frm,
                  text="  car · automotive · performance · enthusiast · racing · mechanic",
                  font=("Segoe UI", 9), foreground="#888").pack(side="left")

        self.audience_widget = AudienceKeywordsWidget(body)
        self.audience_widget.pack(fill="both", expand=True, padx=4)
        self.audience_widget.set_keywords(self.audience_keywords)

    # ── Filters ──────────────────────────────────────────────────────────────

    def _build_filters_tab(self):
        body = self._tab_body(self._tab_filters)

        banner = _section_banner(body,
            "Default filter values applied when this profile is activated. "
            "You can always override them in the sidebar during a session — "
            "these are just the starting point."
        )
        banner.pack(fill="x", pady=(0, 12), padx=4)

        frm = ttk.Frame(body, padding=(10, 0))
        frm.pack(fill="both", expand=True)

        # Hide chains
        chains_row = ttk.Frame(frm)
        chains_row.pack(anchor="w", pady=4)
        self.hide_chains_var = tk.BooleanVar(value=self.default_filters.get("hide_chains", True))
        ttk.Checkbutton(chains_row, text="Hide chains by default",
                        variable=self.hide_chains_var).pack(side="left")
        _info_icon(chains_row,
            "When checked, businesses with chain confidence ≥ 60% are hidden by default.\n\n"
            "Local independents are far more likely to sponsor local events than\n"
            "corporate chains, so this is on by default."
        ).pack(side="left", padx=(6, 0))

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=8)

        # Min score
        score_row = ttk.Frame(frm)
        score_row.pack(anchor="w", pady=4)
        ttk.Label(score_row, text="Default minimum score:").pack(side="left")
        _info_icon(score_row,
            "Only businesses scoring at or above this threshold are shown.\n\n"
            "0 = show everything\n"
            "30 = show businesses with at least some matching signals\n"
            "50 = show only reasonably strong matches\n\n"
            "Scores are 0–100, set by your Scoring Rules."
        ).pack(side="left", padx=(6, 12))
        self.min_score_var = tk.StringVar(value=str(self.default_filters.get("min_score", 0)))
        ttk.Spinbox(score_row, textvariable=self.min_score_var, from_=0, to=100, width=8).pack(side="left")

        ttk.Separator(frm, orient="horizontal").pack(fill="x", pady=8)

        # Max distance
        dist_row = ttk.Frame(frm)
        dist_row.pack(anchor="w", pady=4)
        ttk.Label(dist_row, text="Default maximum distance (miles):").pack(side="left")
        _info_icon(dist_row,
            "Hides businesses farther than this from your search center.\n\n"
            "This trims the results list — it does not limit what the Overpass\n"
            "search fetches (that's controlled by the radius slider in the top bar).\n\n"
            "Typical values: 5–15 miles for a local event."
        ).pack(side="left", padx=(6, 12))
        self.max_distance_var = tk.StringVar(value=str(self.default_filters.get("max_distance_mi", 25)))
        ttk.Spinbox(dist_row, textvariable=self.max_distance_var, from_=0.5, to=100, width=8).pack(side="left")

    # ── Export ───────────────────────────────────────────────────────────────

    def _build_export_tab(self):
        body = self._tab_body(self._tab_export)

        banner = _section_banner(body,
            "Choose which fields appear in exported CSVs and in what order. "
            "Select a column in the right list, then use ↑/↓ to reorder. "
            "Only shortlisted businesses are exported unless you choose 'Export ALL' from the File menu."
        )
        banner.pack(fill="x", pady=(0, 10), padx=4)

        self.export_widget = ExportColumnsWidget(body)
        self.export_widget.pack(fill="both", expand=True, padx=4)
        self.export_widget.set_columns(self.export_columns)

    # ── Sources ──────────────────────────────────────────────────────────────

    def _build_sources_tab(self):
        body = self._tab_body(self._tab_sources)

        banner = _section_banner(body,
            "Data sources to enable for this profile. "
            "Overpass is always on and provides the core business data. "
            "Wikidata is free and improves chain detection. "
            "Google Places and Yelp add richer data but require API keys."
        )
        banner.pack(fill="x", pady=(0, 10), padx=4)

        self.sources_widget = SourceCheckboxesWidget(body)
        self.sources_widget.pack(anchor="w", padx=4)
        self.sources_widget.set_sources(self.data_sources)

    # ── Close guard ──────────────────────────────────────────────────────────

    def _current_state(self) -> dict:
        """Snapshot the current widget state as a comparable dict."""
        return {
            "name":        self.name_var.get().strip(),
            "description": self.desc_text.get("1.0", "end-1c").strip(),
            "scoring_rules": self.rules_widget.get_rules(),
            "audience_keywords": self.audience_widget.get_keywords(),
            "default_filters": {
                "hide_chains":     self.hide_chains_var.get(),
                "min_score":       int(self.min_score_var.get() or 0),
                "max_distance_mi": float(self.max_distance_var.get() or 25),
            },
            "export_columns": self.export_widget.get_columns(),
            "data_sources":   self.sources_widget.get_sources(),
        }

    def _has_unsaved_changes(self) -> bool:
        current = self._current_state()

        if self._original_profile is None:
            # New profile — any meaningful input counts as unsaved work
            return bool(
                current["name"]
                or current["description"]
                or current["scoring_rules"]
                or current["audience_keywords"]
            )

        # Edit mode — compare field by field against what was loaded
        orig = self._original_profile
        orig_filters = orig.get("default_filters", {})
        return (
            current["name"]              != orig.get("name", "")
            or current["description"]    != orig.get("description", "")
            or current["scoring_rules"]  != orig.get("scoring_rules", [])
            or current["audience_keywords"] != orig.get("audience_keywords", [])
            or current["default_filters"]["hide_chains"]
                != orig_filters.get("hide_chains", True)
            or current["default_filters"]["min_score"]
                != orig_filters.get("min_score", 0)
            or current["default_filters"]["max_distance_mi"]
                != orig_filters.get("max_distance_mi", 25)
            or current["export_columns"] != orig.get("export_columns", [])
            or current["data_sources"]   != orig.get("data_sources", [])
        )

    def _confirm_close(self):
        """Close the dialog, prompting if there are unsaved changes."""
        if self._has_unsaved_changes():
            if not messagebox.askyesno(
                "Discard changes?",
                "You have unsaved changes.\n\nDiscard and close anyway?",
                icon="warning",
                parent=self,
            ):
                return
        self.destroy()

    # ── Save ─────────────────────────────────────────────────────────────────

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Validation Error", "Profile name is required.")
            return

        description = self.desc_text.get("1.0", "end-1c").strip()

        profile = {
            "name":            name,
            "description":     description,
            "scoring_rules":   self.rules_widget.get_rules(),
            "audience_keywords": self.audience_widget.get_keywords(),
            "default_filters": {
                "hide_chains":    self.hide_chains_var.get(),
                "min_score":      int(self.min_score_var.get() or 0),
                "max_distance_mi": float(self.max_distance_var.get() or 25),
            },
            "export_columns":  self.export_widget.get_columns(),
            "data_sources":    self.sources_widget.get_sources(),
        }

        self._result_profile = profile
        self.destroy()

    def result(self) -> Optional[dict]:
        """Return the saved profile, or None if cancelled."""
        self.wait_window()
        return self._result_profile


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def parse_value(field_type: str, value_str: str):
    """Convert string value to the appropriate Python type for storage."""
    if field_type == "numeric":
        try:
            return float(value_str) if "." in value_str else int(value_str)
        except ValueError:
            return 0
    elif field_type == "bool":
        return value_str.lower() in ("true", "1", "yes")
    return str(value_str)
