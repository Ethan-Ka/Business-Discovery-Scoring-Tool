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


# Field types for matching operators
FIELD_TYPES = {
    # String fields
    "industry": "string",
    "category": "string",
    "audience_overlap": "string",
    "parent_company": "string",
    "entity_type": "string",
    "wikidata_description": "string",
    # Boolean fields
    "is_chain": "bool",
    "has_website": "bool",
    "has_email": "bool",
    "has_phone": "bool",
    "has_opening_hours": "bool",
    # Numeric fields
    "chain_confidence": "numeric",
    "num_locations": "numeric",
    "osm_completeness": "numeric",
    "distance_mi": "numeric",
    "founded_year": "numeric",
}

AVAILABLE_FIELDS = list(FIELD_TYPES.keys())

STRING_OPERATORS = ["=", "!=", "contains", "not contains", "is empty", "is not empty"]
NUMERIC_OPERATORS = [">", "<", ">=", "<=", "=", "!=", "is empty", "is not empty"]
BOOL_OPERATORS = ["=", "!="]

ALL_SOURCES = ["overpass", "wikidata", "google_places", "yelp"]
SOURCES_REQUIRE_KEY = {"google_places", "yelp"}

AVAILABLE_EXPORT_COLUMNS = [
    "Name", "Score", "Industry", "Entity Type", "Chain", "Distance", "Phone",
    "Email", "Website", "Address", "Category", "Audience", "OSM Completeness",
    "Chain Confidence", "Num Locations", "Founded Year", "AI Insight", "Notes"
]


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


class RuleBuilderWidget(ttk.Frame):
    """
    Table-like widget for editing scoring rules.
    Each rule: Field | Operator | Value (adapted by field type) | Points | Delete button
    Plus drag handle for reordering (shown as ⋮)
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.rules = []
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        # Headers
        header = ttk.Frame(self)
        header.pack(fill="x", pady=(0, 4))
        ttk.Label(header, text="Field", width=18, relief="solid", borderwidth=1).pack(side="left", padx=1)
        ttk.Label(header, text="Operator", width=12, relief="solid", borderwidth=1).pack(side="left", padx=1)
        ttk.Label(header, text="Value", width=20, relief="solid", borderwidth=1).pack(side="left", padx=1)
        ttk.Label(header, text="Pts", width=4, relief="solid", borderwidth=1).pack(side="left", padx=1)
        ttk.Label(header, text="", width=2, relief="solid", borderwidth=1).pack(side="left", padx=1)

        # Rules container
        self.rules_container = ttk.Frame(self)
        self.rules_container.pack(fill="both", expand=True)

        # Add rule button
        btn_frm = ttk.Frame(self)
        btn_frm.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_frm, text="+ Add Rule", command=self._add_rule).pack(side="left")

    def set_rules(self, rules: list[dict]):
        """Load rules from profile."""
        self.rules = [dict(r) for r in rules]
        self._refresh()

    def get_rules(self) -> list[dict]:
        """Return current rule list."""
        return [dict(r) for r in self.rules]

    def _add_rule(self):
        self.rules.append({
            "field": "industry",
            "operator": "=",
            "value": "",
            "points": 10
        })
        self._refresh()

    def _remove_rule(self, idx: int):
        del self.rules[idx]
        self._refresh()

    def _refresh(self):
        for w in self.rules_container.winfo_children():
            w.destroy()

        for idx, rule in enumerate(self.rules):
            row = ttk.Frame(self.rules_container)
            row.pack(fill="x", pady=1)

            # Field dropdown
            field_var = tk.StringVar(value=rule.get("field", "industry"))
            field_combo = ttk.Combobox(row, textvariable=field_var, values=AVAILABLE_FIELDS,
                                       width=16, state="readonly")
            field_combo.pack(side="left", padx=1)

            # Operator and Value depend on field type — bind to field changes
            op_var = tk.StringVar(value=rule.get("operator", "="))
            val_var = tk.StringVar(value=str(rule.get("value", "")))
            pts_var = tk.StringVar(value=str(rule.get("points", 10)))

            # Operator combobox (will update on field_var change)
            op_combo = ttk.Combobox(row, textvariable=op_var, state="readonly", width=10)
            op_combo.pack(side="left", padx=1)

            # Value widget (type-specific)
            val_widget = ttk.Entry(row, textvariable=val_var, width=18)
            val_widget.pack(side="left", padx=1)

            # Points spinner
            pts_spin = ttk.Spinbox(row, textvariable=pts_var, from_=0, to=100, width=3)
            pts_spin.pack(side="left", padx=1)

            # Delete button
            del_btn = ttk.Button(row, text="✕", width=2,
                                command=lambda i=idx: self._remove_rule(i))
            del_btn.pack(side="left", padx=1)

            # Update operators and value widget when field changes
            def make_updater(i, fv, ov, vv, pv, val_w, op_c):
                def _upd(*_):
                    field = fv.get()
                    ftype = FIELD_TYPES.get(field, "string")

                    # Update operators
                    if ftype == "string":
                        ops = STRING_OPERATORS
                    elif ftype == "numeric":
                        ops = NUMERIC_OPERATORS
                    elif ftype == "bool":
                        ops = BOOL_OPERATORS
                    else:
                        ops = STRING_OPERATORS
                    op_c["values"] = ops
                    if ov.get() not in ops:
                        ov.set(ops[0])

                    # Update value widget (bool -> checkbox, numeric -> spinbox, etc.)
                    # For now keep as entry, but could adapt
                    self.rules[i] = {
                        "field": fv.get(),
                        "operator": ov.get(),
                        "value": parse_value(ftype, vv.get()),
                        "points": int(pv.get() or 10)
                    }
                return _upd

            updater = make_updater(idx, field_var, op_var, val_var, pts_var, val_widget, op_combo)
            field_var.trace_add("write", updater)
            op_var.trace_add("write", lambda *_: self._sync_rule(idx, field_var, op_var, val_var, pts_var))
            val_var.trace_add("write", lambda *_: self._sync_rule(idx, field_var, op_var, val_var, pts_var))
            pts_var.trace_add("write", lambda *_: self._sync_rule(idx, field_var, op_var, val_var, pts_var))

            # Initial operator update
            field = field_var.get()
            ftype = FIELD_TYPES.get(field, "string")
            ops = STRING_OPERATORS if ftype == "string" else (
                NUMERIC_OPERATORS if ftype == "numeric" else (
                    BOOL_OPERATORS if ftype == "bool" else STRING_OPERATORS
                )
            )
            op_combo["values"] = ops

    def _sync_rule(self, idx: int, fv: tk.StringVar, ov: tk.StringVar,
                   vv: tk.StringVar, pv: tk.StringVar):
        """Update rule dict from widgets."""
        if idx < len(self.rules):
            ftype = FIELD_TYPES.get(fv.get(), "string")
            self.rules[idx] = {
                "field": fv.get(),
                "operator": ov.get(),
                "value": parse_value(ftype, vv.get()),
                "points": int(pv.get() or 10)
            }


class AudienceKeywordsWidget(ttk.Frame):
    """
    Keyword chip input: type + Enter to add, click chip to remove.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.keywords = []
        self._build_ui()

    def _build_ui(self):
        # Input row
        input_frm = ttk.Frame(self)
        input_frm.pack(fill="x", pady=(0, 8))
        ttk.Label(input_frm, text="Type keyword + Enter:").pack(side="left")
        self.input_var = tk.StringVar()
        self.input_entry = ttk.Entry(input_frm, textvariable=self.input_var, width=30)
        self.input_entry.pack(side="left", padx=4)
        self.input_entry.bind("<Return>", self._add_keyword)

        # Chips container
        self.chips_frame = ttk.Frame(self)
        self.chips_frame.pack(fill="both", expand=True)

    def set_keywords(self, keywords: list[str]):
        """Load keywords from profile."""
        self.keywords = list(keywords)
        self._refresh()

    def get_keywords(self) -> list[str]:
        """Return current keyword list."""
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
        for w in self.chips_frame.winfo_children():
            w.destroy()

        chips_row = ttk.Frame(self.chips_frame)
        chips_row.pack(fill="x")

        for kw in self.keywords:
            chip = ttk.Frame(chips_row, relief="solid", borderwidth=1)
            chip.pack(side="left", padx=2, pady=2)
            ttk.Label(chip, text=f"  {kw}  ").pack(side="left", padx=2)
            ttk.Button(chip, text="✕", width=1,
                      command=lambda k=kw: self._remove_keyword(k)).pack(side="left", padx=(0, 2))


class ExportColumnsWidget(ttk.Frame):
    """
    Column picker with checkboxes and drag-to-reorder (simulated via up/down buttons).
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.selected_columns = []
        self._build_ui()

    def _build_ui(self):
        # Two-column layout
        left_frame = ttk.Frame(self)
        left_frame.pack(side="left", fill="both", expand=True)

        right_frame = ttk.Frame(self)
        right_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

        # Available columns
        ttk.Label(left_frame, text="Available:").pack(anchor="w")
        self.available_listbox = tk.Listbox(left_frame, height=12)
        self.available_listbox.pack(fill="both", expand=True)

        # Selected columns (with reorder buttons)
        ttk.Label(right_frame, text="Selected (exported in order):").pack(anchor="w")
        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(anchor="e", pady=(0, 4))
        ttk.Button(btn_frame, text="↑", width=3, command=self._move_up).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="↓", width=3, command=self._move_down).pack(side="left", padx=2)

        self.selected_listbox = tk.Listbox(right_frame, height=12)
        self.selected_listbox.pack(fill="both", expand=True)

        # Buttons
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Add >>", command=self._add_column).pack(side="left", padx=2)
        ttk.Button(btn_row, text="<< Remove", command=self._remove_column).pack(side="left", padx=2)

    def set_columns(self, columns: list[str]):
        """Load export columns from profile."""
        self.selected_columns = list(columns)
        self._refresh()

    def get_columns(self) -> list[str]:
        """Return current column list."""
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
            col = self.available_listbox.get(sel[0])
            self.selected_columns.append(col)
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
            self.selected_columns[idx], self.selected_columns[idx-1] = \
                self.selected_columns[idx-1], self.selected_columns[idx]
            self._refresh()
            self.selected_listbox.selection_set(idx - 1)

    def _move_down(self):
        sel = self.selected_listbox.curselection()
        if sel and sel[0] < len(self.selected_columns) - 1:
            idx = sel[0]
            self.selected_columns[idx], self.selected_columns[idx+1] = \
                self.selected_columns[idx+1], self.selected_columns[idx]
            self._refresh()
            self.selected_listbox.selection_set(idx + 1)


class SourceCheckboxesWidget(ttk.Frame):
    """
    Checkboxes for each available data source.
    Shows "(API Key required)" for sources that need one.
    """
    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.enabled_sources = []
        self._build_ui()

    def _build_ui(self):
        for source in ALL_SOURCES:
            var = tk.BooleanVar()
            label_text = source
            if source in SOURCES_REQUIRE_KEY:
                label_text += " (API Key required)"

            cb = ttk.Checkbutton(self, text=label_text, variable=var,
                                command=lambda s=source, v=var: self._update_sources(s, v))
            cb.pack(anchor="w", pady=4)
            setattr(self, f"{source}_var", var)

    def set_sources(self, sources: list[str]):
        """Load sources from profile."""
        self.enabled_sources = list(sources)
        for source in ALL_SOURCES:
            var = getattr(self, f"{source}_var")
            var.set(source in self.enabled_sources)

    def get_sources(self) -> list[str]:
        """Return currently enabled sources."""
        return [s for s in ALL_SOURCES if getattr(self, f"{s}_var").get()]

    def _update_sources(self, source: str, var: tk.BooleanVar):
        """Sync enabled sources when checkbox changes."""
        if var.get():
            if source not in self.enabled_sources:
                self.enabled_sources.append(source)
        else:
            if source in self.enabled_sources:
                self.enabled_sources.remove(source)


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

        # Load profile data or defaults
        if profile:
            self.name = profile.get("name", "")
            self.description = profile.get("description", "")
            self.scoring_rules = profile.get("scoring_rules", [])
            self.audience_keywords = profile.get("audience_keywords", [])
            self.default_filters = profile.get("default_filters", {})
            self.export_columns = profile.get("export_columns", [])
            self.data_sources = profile.get("data_sources", [])
        else:
            self.name = ""
            self.description = ""
            self.scoring_rules = []
            self.audience_keywords = []
            self.default_filters = {}
            self.export_columns = list(AVAILABLE_EXPORT_COLUMNS[:8])  # Default subset
            self.data_sources = ["overpass", "wikidata"]

        self._build_ui()

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        # Tabs
        notebook = ttk.Notebook(frm)
        notebook.pack(fill="both", expand=True)

        self._tab_general = ScrollableTab(notebook)
        self._tab_scoring = ScrollableTab(notebook)
        self._tab_audience = ScrollableTab(notebook)
        self._tab_filters = ScrollableTab(notebook)
        self._tab_export = ScrollableTab(notebook)
        self._tab_sources = ScrollableTab(notebook)

        notebook.add(self._tab_general, text="General")
        notebook.add(self._tab_scoring, text="Scoring Rules")
        notebook.add(self._tab_audience, text="Audience")
        notebook.add(self._tab_filters, text="Filters")
        notebook.add(self._tab_export, text="Export")
        notebook.add(self._tab_sources, text="Sources")

        self._build_general_tab()
        self._build_scoring_tab()
        self._build_audience_tab()
        self._build_filters_tab()
        self._build_export_tab()
        self._build_sources_tab()

        # Action buttons
        btn_frm = ttk.Frame(frm)
        btn_frm.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_frm, text="Save", command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_frm, text="Cancel", command=self.destroy).pack(side="right")

    @staticmethod
    def _tab_body(tab):
        return getattr(tab, "content", tab)

    def _build_general_tab(self):
        body = self._tab_body(self._tab_general)

        ttk.Label(body, text="Name:").grid(row=0, column=0, sticky="w", pady=4)
        self.name_var = tk.StringVar(value=self.name)
        ttk.Entry(body, textvariable=self.name_var, width=60).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(body, text="Description:").grid(row=1, column=0, sticky="nw", pady=4)
        self.desc_var = tk.StringVar(value=self.description)
        desc_text = tk.Text(body, height=6, width=60)
        desc_text.insert("1.0", self.description)
        desc_text.grid(row=1, column=1, sticky="nsew", pady=4)
        self.desc_text = desc_text

        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

    def _build_scoring_tab(self):
        body = self._tab_body(self._tab_scoring)
        ttk.Label(body, text="Scoring Rules (rules are additive, max score 100):").pack(anchor="w", pady=(0, 8))
        self.rules_widget = RuleBuilderWidget(body)
        self.rules_widget.pack(fill="both", expand=True)
        self.rules_widget.set_rules(self.scoring_rules)

    def _build_audience_tab(self):
        body = self._tab_body(self._tab_audience)
        ttk.Label(body, text="Audience Keywords:").pack(anchor="w", pady=(0, 8))
        self.audience_widget = AudienceKeywordsWidget(body)
        self.audience_widget.pack(fill="both", expand=True)
        self.audience_widget.set_keywords(self.audience_keywords)

    def _build_filters_tab(self):
        body = self._tab_body(self._tab_filters)
        frm = ttk.Frame(body, padding=10)
        frm.pack(fill="both", expand=True)

        # Hide chains
        self.hide_chains_var = tk.BooleanVar(value=self.default_filters.get("hide_chains", True))
        ttk.Checkbutton(frm, text="Hide chains by default", variable=self.hide_chains_var).pack(anchor="w", pady=4)

        # Min score
        ttk.Label(frm, text="Default minimum score:").pack(anchor="w", pady=(8, 0))
        self.min_score_var = tk.StringVar(value=str(self.default_filters.get("min_score", 0)))
        ttk.Spinbox(frm, textvariable=self.min_score_var, from_=0, to=100, width=10).pack(anchor="w")

        # Max distance
        ttk.Label(frm, text="Default maximum distance (miles):").pack(anchor="w", pady=(8, 0))
        self.max_distance_var = tk.StringVar(value=str(self.default_filters.get("max_distance_mi", 25)))
        ttk.Spinbox(frm, textvariable=self.max_distance_var, from_=0.5, to=100, width=10).pack(anchor="w")

    def _build_export_tab(self):
        body = self._tab_body(self._tab_export)
        ttk.Label(body, text="Select columns to include in CSV export:").pack(anchor="w", pady=(0, 8))
        self.export_widget = ExportColumnsWidget(body)
        self.export_widget.pack(fill="both", expand=True)
        self.export_widget.set_columns(self.export_columns)

    def _build_sources_tab(self):
        body = self._tab_body(self._tab_sources)
        ttk.Label(body, text="Enable data sources:").pack(anchor="w", pady=(0, 8))
        self.sources_widget = SourceCheckboxesWidget(body)
        self.sources_widget.pack(anchor="w")
        self.sources_widget.set_sources(self.data_sources)

    def _save(self):
        """Validate and save profile."""
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Validation Error", "Profile name is required.")
            return

        description = self.desc_text.get("1.0", "end-1c").strip()

        profile = {
            "name": name,
            "description": description,
            "scoring_rules": self.rules_widget.get_rules(),
            "audience_keywords": self.audience_widget.get_keywords(),
            "default_filters": {
                "hide_chains": self.hide_chains_var.get(),
                "min_score": int(self.min_score_var.get() or 0),
                "max_distance_mi": float(self.max_distance_var.get() or 25),
            },
            "export_columns": self.export_widget.get_columns(),
            "data_sources": self.sources_widget.get_sources(),
        }

        self._result_profile = profile
        self.destroy()

    def result(self) -> Optional[dict]:
        """Return the saved profile, or None if cancelled."""
        self.wait_window()
        return self._result_profile


def parse_value(field_type: str, value_str: str):
    """Convert string value to appropriate type."""
    if field_type == "numeric":
        try:
            if "." in value_str:
                return float(value_str)
            return int(value_str)
        except ValueError:
            return 0
    elif field_type == "bool":
        return value_str.lower() in ("true", "1", "yes")
    return str(value_str)
