import sys
import os

# Allow running from the sponsor_finder/ directory directly
sys.path.insert(0, os.path.dirname(__file__))

import threading
import queue
from cancellation import CancellationToken
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from ui.profile_editor import ProfileEditorDialog
from ui.menu_bar import build_menu_bar

from icon import apply_icon
from search import fetch_businesses, MAX_RESULTS
from enrichment import enrich
from scoring import compute_score, score_color
from chains import build_frequency_chain_set
from filters import apply_standard_filters, apply_custom_filter, sort_businesses, get_categories
from export import (
    load_notes, save_notes,
    load_config, save_config,
    load_shortlist, save_shortlist,
    ensure_data_files_exist,
    export_shortlist_csv, default_export_filename,
    load_history, save_history, append_history_entry,
    load_saved_searches, save_saved_searches,
    load_collections, save_collections,
    export_json,
)
from profiles import load_profiles, save_profiles, get_profile, upsert_profile, delete_profile
from paths import get_data_dir, get_tile_cache_path
import ai_scoring
import applog
import theme as _theme


def is_windows() -> bool:
    return os.name == "nt"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_TITLE  = "Business Discovery & Scoring Tool"
MIN_WIDTH  = 1100
MIN_HEIGHT = 700
SIDEBAR_W  = 220
DETAIL_W   = 280

TREE_COLUMNS = ("score", "name", "category", "industry", "chain", "distance", "phone", "website")
TREE_HEADINGS = {
    "score":    "Score",
    "name":     "Name",
    "category": "Category",
    "industry": "Industry",
    "chain":    "Chain?",
    "distance": "Dist (mi)",
    "phone":    "Phone",
    "website":  "Website",
}
COL_WIDTHS = {
    "score": 55, "name": 200, "category": 110, "industry": 110,
    "chain": 55, "distance": 70, "phone": 120, "website": 160,
}


# AI features are optional — check status on startup
# If a model is not loaded, app works fine without AI explanations and scoring.

class CustomFilterDialog(tk.Toplevel):
    from filters import CUSTOM_FIELDS as FIELDS, CUSTOM_OPERATORS as OPERATORS

    def __init__(self, parent, existing_rules=None, existing_combine="AND"):
        super().__init__(parent)
        self.title("Build Custom Filter")
        self.geometry("600x380")
        self.resizable(True, True)
        self.grab_set()

        self.rules: list[dict] = list(existing_rules or [])
        self.combine_var = tk.StringVar(value=existing_combine)
        self.result_rules = None
        self.result_combine = None

        self._build_ui()
        self._refresh_rules()

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        # Combine toggle
        top = ttk.Frame(frm)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Combine rules with:").pack(side="left")
        for val in ("AND", "OR"):
            ttk.Radiobutton(top, text=val, variable=self.combine_var,
                            value=val).pack(side="left", padx=4)

        # Scrollable rules container
        rules_outer = ttk.Frame(frm)
        rules_outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(rules_outer, highlightthickness=0, bd=0, height=220)
        vsb = ttk.Scrollbar(rules_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.rules_frame = ttk.Frame(canvas)
        self._rules_win = canvas.create_window((0, 0), window=self.rules_frame, anchor="nw")
        self._rules_canvas = canvas

        def _on_inner(*_):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas(e):
            canvas.itemconfigure(self._rules_win, width=e.width)
        self.rules_frame.bind("<Configure>", _on_inner)
        canvas.bind("<Configure>", _on_canvas)

        def _mwheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _mwheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        # Add rule button
        ttk.Button(frm, text="+ Add Rule", command=self._add_rule).pack(pady=6)

        # Action buttons
        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Apply", command=self._apply).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right")

    def _add_rule(self):
        self.rules.append({"field": "Score", "operator": ">=", "value": "50"})
        self._refresh_rules()

    def _refresh_rules(self):
        for w in self.rules_frame.winfo_children():
            w.destroy()

        for i, rule in enumerate(self.rules):
            row = ttk.Frame(self.rules_frame)
            row.pack(fill="x", pady=2)

            field_var = tk.StringVar(value=rule["field"])
            op_var    = tk.StringVar(value=rule["operator"])
            val_var   = tk.StringVar(value=rule["value"])

            def make_updater(idx, fv, ov, vv):
                def _upd(*_):
                    self.rules[idx] = {"field": fv.get(), "operator": ov.get(), "value": vv.get()}
                return _upd

            upd = make_updater(i, field_var, op_var, val_var)
            field_var.trace_add("write", upd)
            op_var.trace_add("write", upd)
            val_var.trace_add("write", upd)

            ttk.Combobox(row, textvariable=field_var, values=self.FIELDS,
                         width=20, state="readonly").pack(side="left", padx=2)
            ttk.Combobox(row, textvariable=op_var, values=self.OPERATORS,
                         width=13, state="readonly").pack(side="left", padx=2)
            ttk.Entry(row, textvariable=val_var, width=14).pack(side="left", padx=2)

            idx = i
            ttk.Button(row, text="✕", width=2,
                       command=lambda i=idx: self._remove_rule(i)).pack(side="left", padx=2)

    def _remove_rule(self, idx):
        del self.rules[idx]
        self._refresh_rules()

    def _apply(self):
        self.result_rules   = list(self.rules)
        self.result_combine = self.combine_var.get()
        self.destroy()


# ---------------------------------------------------------------------------
# AI Settings Dialog
# ---------------------------------------------------------------------------

class AISettingsDialog(tk.Toplevel):
    def __init__(self, parent, current_model: str, current_weight: float,
                 explain_enabled: bool, score_enabled: bool, max_score: int,
                 disable_max_limit: bool = True, debug_mode: bool = False):
        super().__init__(parent)
        self.title("AI Settings — Local LLM Models")
        self.geometry("480x540")
        self.resizable(True, False)
        self.minsize(420, 500)
        self.grab_set()

        self.result_model    = current_model
        self.result_weight   = current_weight
        self.result_explain  = explain_enabled
        self.result_scoring  = score_enabled
        self.result_max      = max_score
        self.result_disable_max_limit = disable_max_limit
        self.result_debug    = debug_mode
        self.confirmed       = False

        self._model_var    = tk.StringVar(value=current_model)
        self._weight_var   = tk.DoubleVar(value=current_weight)
        self._explain_var  = tk.BooleanVar(value=explain_enabled)
        self._score_var    = tk.BooleanVar(value=score_enabled)
        self._max_var      = tk.IntVar(value=max_score)
        self._disable_max_limit_var = tk.BooleanVar(value=disable_max_limit)
        self._debug_var    = tk.BooleanVar(value=debug_mode)
        self._dl_model_var = tk.StringVar()
        self._pulling      = False
        self._pull_cancellation_token = None

        self._build_ui()
        self._async_refresh_status()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        self._build_tab_settings(nb)
        self._build_tab_download(nb)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_row, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right")

    def _build_tab_settings(self, nb):
        frm = ttk.Frame(nb, padding=12)
        nb.add(frm, text="Settings")

        # AI status
        status_row = ttk.Frame(frm)
        status_row.pack(fill="x", pady=(0, 6))
        ttk.Label(status_row, text="AI:").pack(side="left")
        self._status_dot = tk.Label(status_row, text="●", font=("", 12), fg="#95a5a6")
        self._status_dot.pack(side="left", padx=4)
        self._status_lbl = ttk.Label(status_row, text="Checking…", foreground="gray")
        self._status_lbl.pack(side="left")
        ttk.Button(status_row, text="Recheck", width=8,
                   command=self._async_refresh_status).pack(side="right")

        ttk.Separator(frm).pack(fill="x", pady=6)

        # Active model
        ttk.Label(frm, text="Active model:").pack(anchor="w")
        model_row = ttk.Frame(frm)
        model_row.pack(fill="x", pady=2)
        self._model_combo = ttk.Combobox(model_row, textvariable=self._model_var,
                                          state="readonly", values=[self._model_var.get()])
        self._model_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(model_row, text="Refresh", width=8,
                   command=self._refresh_models).pack(side="left", padx=4)

        ttk.Separator(frm).pack(fill="x", pady=6)

        # Score blend
        ttk.Label(frm, text="Score blend  (Rule ←——→ AI):").pack(anchor="w")
        self._weight_label = ttk.Label(frm, foreground="#555")
        self._weight_label.pack(anchor="e")
        ttk.Scale(frm, from_=0.0, to=1.0, variable=self._weight_var,
                  orient="horizontal", command=self._on_weight_change).pack(fill="x")
        self._on_weight_change(self._weight_var.get())

        ttk.Separator(frm).pack(fill="x", pady=6)

        # Feature toggles
        ttk.Checkbutton(frm, text="Auto-generate AI explanation on row select",
                        variable=self._explain_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(frm, text="Enable AI batch scoring mode  (slower)",
                        variable=self._score_var).pack(anchor="w", pady=2)

        ttk.Checkbutton(
            frm,
            text="Score all results (disable max limit)",
            variable=self._disable_max_limit_var,
            command=self._sync_max_limit_state,
        ).pack(anchor="w", pady=(2, 0))

        max_row = ttk.Frame(frm)
        max_row.pack(fill="x", pady=(4, 0))
        ttk.Label(max_row, text="Max businesses to AI score:").pack(side="left")
        self._max_spinbox = ttk.Spinbox(
            max_row,
            from_=10,
            to=2000,
            increment=10,
            textvariable=self._max_var,
            width=6,
        )
        self._max_spinbox.pack(side="left", padx=6)
        self._sync_max_limit_state()

        ttk.Separator(frm).pack(fill="x", pady=(10, 6))
        ttk.Label(frm, text="Developer", font=("Segoe UI", 9, "bold"),
                  foreground="#555").pack(anchor="w")
        ttk.Checkbutton(frm, text="Debug mode  (verbose AI logs in console)",
                        variable=self._debug_var).pack(anchor="w", pady=2)

    def _sync_max_limit_state(self):
        state = "disabled" if self._disable_max_limit_var.get() else "normal"
        self._max_spinbox.config(state=state)

    def _build_tab_download(self, nb):
        frm = ttk.Frame(nb, padding=12)
        nb.add(frm, text="Download Models")

        ttk.Label(frm, text="Download an AI model to enable AI features.",
                  foreground="gray").pack(anchor="w")
        ttk.Label(frm,
                  text="Models are cached locally — download once, use offline.\n"
                       "Models persist after download — no re-download needed.",
                  foreground="gray", font=("Segoe UI", 8),
                  justify="left").pack(anchor="w", pady=(0, 8))

        ttk.Separator(frm).pack(fill="x", pady=4)

        # Recommended models list
        ttk.Label(frm, text="Recommended models:").pack(anchor="w")
        cols = ("model", "description", "size")
        self._rec_tree = ttk.Treeview(frm, columns=cols, show="headings",
                                      height=6, selectmode="browse")
        self._rec_tree.heading("model",       text="Model ID")
        self._rec_tree.heading("description", text="Description")
        self._rec_tree.heading("size",        text="Size")
        self._rec_tree.column("model",       width=110, stretch=False)
        self._rec_tree.column("description", width=220)
        self._rec_tree.column("size",        width=65,  stretch=False)

        for model_id, desc, size in ai_scoring.RECOMMENDED_MODELS:
            self._rec_tree.insert("", "end", values=(model_id, desc, size))

        self._rec_tree.pack(fill="x", pady=4)
        self._rec_tree.bind("<<TreeviewSelect>>", self._on_rec_select)

        ttk.Separator(frm).pack(fill="x", pady=4)

        # Manual entry + pull button
        dl_row = ttk.Frame(frm)
        dl_row.pack(fill="x")
        ttk.Label(dl_row, text="Model ID:").pack(side="left")
        ttk.Entry(dl_row, textvariable=self._dl_model_var, width=22).pack(
            side="left", padx=6)
        self._pull_btn = ttk.Button(dl_row, text="Pull / Download",
                                    command=self._start_pull)
        self._pull_btn.pack(side="left")
        
        # Cancel Download button (hidden by default)
        self._cancel_pull_btn = ttk.Button(dl_row, text="Cancel Download", command=self._on_cancel_pull, state="disabled")
        self._cancel_pull_btn.pack(side="left", padx=2)

        # Progress area
        self._pull_status_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self._pull_status_var,
                  foreground="#2980b9", wraplength=380,
                  font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))
        self._pull_bar = ttk.Progressbar(frm, mode="determinate", length=380)
        self._pull_bar.pack(fill="x", pady=2)

    # ── Status / model refresh ────────────────────────────────────────────

    def _async_refresh_status(self):
        import threading
        import queue
        self._status_lbl.config(text="Checking…", foreground="gray")
        self._status_dot.config(fg="#95a5a6")

        q = queue.Queue()

        def _run():
            ready = ai_scoring.is_ai_ready()
            if not ready:
                # Not loaded in memory — check if a model file exists on disk
                # and try to load it (same logic as main window startup check).
                models = ai_scoring.list_models()
                if models:
                    preferred = self._model_var.get()
                    candidates = [preferred, ai_scoring.DEFAULT_MODEL] + models
                    seen: set = set()
                    for candidate in candidates:
                        if not candidate or candidate in seen:
                            continue
                        seen.add(candidate)
                        if ai_scoring.load_default_model(candidate):
                            ready = True
                            break
            q.put(ready)

        def _process():
            try:
                ready = q.get_nowait()
                if not self.winfo_exists():
                    return
                self._apply_status(ready)
            except queue.Empty:
                if self.winfo_exists():
                    try:
                        self.after(100, _process)
                    except tk.TclError:
                        pass
            except tk.TclError:
                pass

        threading.Thread(target=_run, daemon=True).start()
        _process()

    def _apply_status(self, ready: bool):
        if not self.winfo_exists():
            return
        if ready:
            self._status_dot.config(fg="#27ae60")
            self._status_lbl.config(text="Ready", foreground="#27ae60")
            self._refresh_models()
        else:
            self._status_dot.config(fg="#e74c3c")
            self._status_lbl.config(
                text="No model loaded. Download a model to enable AI features.",
                foreground="#e74c3c",
            )

    def _refresh_models(self):
        import threading
        import queue

        q = queue.Queue()

        def _run():
            models = ai_scoring.list_models()
            q.put(models)

        def _process():
            try:
                models = q.get_nowait()
                if not self.winfo_exists():
                    return
                self._apply_models(models)
            except queue.Empty:
                if self.winfo_exists():
                    try:
                        self.after(100, _process)
                    except tk.TclError:
                        pass
            except tk.TclError:
                pass

        threading.Thread(target=_run, daemon=True).start()
        _process()

    def _apply_models(self, models: list[str]):
        if not self.winfo_exists():
            return
        if models:
            self._model_combo["values"] = models
            if self._model_var.get() not in models:
                self._model_var.set(ai_scoring.pick_best_model(models))
            # Mark installed models in the rec_tree
            try:
                from sponsor_finder.model_manager import resolve_model_filename
            except ImportError:
                from model_manager import resolve_model_filename
            for iid in self._rec_tree.get_children():
                mid = self._rec_tree.item(iid, "values")[0]
                expected_filename = resolve_model_filename(mid)
                tag = "installed" if expected_filename in models else ""
                self._rec_tree.item(iid, tags=(tag,))
            self._rec_tree.tag_configure("installed", foreground="#27ae60")

    # ── Recommended model selection ───────────────────────────────────────

    def _on_rec_select(self, _event):
        sel = self._rec_tree.selection()
        if sel:
            mid = self._rec_tree.item(sel[0], "values")[0]
            self._dl_model_var.set(mid)

    # ── Pull / download ───────────────────────────────────────────────────

    def _start_pull(self):
        name = self._dl_model_var.get().strip()
        if not name:
            messagebox.showwarning("No model", "Enter or select a model ID first.",
                                   parent=self)
            return
        if self._pulling:
            return

        self._pulling = True
        self._pull_btn.config(state="disabled")
        self._pull_bar["value"] = 0
        self._pull_status_var.set(f"Starting download of '{name}'…")

        import queue
        q = queue.Queue()

        def _on_progress(status: str, pct):
            if not self.winfo_exists():
                return
            label = status if len(status) < 60 else status[:57] + "…"
            q.put(("progress", label, pct))

        def _on_done():
            if not self.winfo_exists():
                return
            self._pulling = False
            loaded = ai_scoring.load_default_model(name)
            q.put(("done", loaded, None))

        def _on_error(msg: str):
            if not self.winfo_exists():
                return
            self._pulling = False
            q.put(("error", msg, None))

        def _process_pull_queue():
            try:
                while True:
                    try:
                        msg = q.get_nowait()
                    except queue.Empty:
                        break

                    if msg[0] == "progress":
                        _, label, pct = msg
                        if not self.winfo_exists():
                            return
                        self._pull_status_var.set(label)
                        if pct is not None:
                            self._pull_bar.config(value=round(pct * 100))
                    elif msg[0] == "done":
                        _, loaded, _ = msg
                        if not self.winfo_exists():
                            return
                        self._pull_btn.config(state="normal")
                        self._cancel_pull_btn.config(state="disabled")
                        self._pull_bar["value"] = 100
                        if loaded:
                            self._pull_status_var.set(f"✓ '{name}' downloaded and loaded successfully.")
                            self._status_dot.config(fg="#27ae60")
                            self._status_lbl.config(text="Ready", foreground="#27ae60")
                        else:
                            self._pull_status_var.set(f"✓ '{name}' downloaded successfully.")
                        self._refresh_models()
                        return
                    elif msg[0] == "error":
                        _, err_msg, _ = msg
                        if not self.winfo_exists():
                            return
                        self._pull_btn.config(state="normal")
                        self._cancel_pull_btn.config(state="disabled")
                        self._pull_bar["value"] = 0
                        self._pull_status_var.set(f"Error: {err_msg}")
                        messagebox.showerror("Download failed", err_msg, parent=self)
                        return
            except tk.TclError:
                pass

            # Keep polling
            if self.winfo_exists():
                try:
                    self.after(100, _process_pull_queue)
                except tk.TclError:
                    pass

        self._pull_cancellation_token = CancellationToken()
        self._cancel_pull_btn.config(state="normal")
        ai_scoring.pull_model(name, _on_progress, _on_done, _on_error, cancellation_token=self._pull_cancellation_token)
        _process_pull_queue()

    # ── Cancel model download ─────────────────────────────────────────────

    def _on_cancel_pull(self):
        """Handle cancel button for model download."""
        if not self._pulling:
            return
        
        # Signal cancellation
        if self._pull_cancellation_token:
            self._pull_cancellation_token.cancel()
        
        # Disable cancel button
        self._cancel_pull_btn.config(state="disabled")
        
        # Get the model name that was being downloaded
        dl_model = self._dl_model_var.get()
        if dl_model:
            # Clean up partial model files
            ai_scoring.delete_model(dl_model)
        
        self._pull_status_var.set("Download cancelled.")
        self._pulling = False

    # ── Weight slider ─────────────────────────────────────────────────────

    def _on_weight_change(self, val):
        ai_pct   = round(float(val) * 100)
        rule_pct = 100 - ai_pct
        self._weight_label.config(text=f"Rule {rule_pct}%  /  AI {ai_pct}%")

    # ── OK ────────────────────────────────────────────────────────────────

    def _ok(self):
        self.result_model   = self._model_var.get()
        self.result_weight  = round(self._weight_var.get(), 2)
        self.result_explain = self._explain_var.get()
        self.result_scoring = self._score_var.get()
        self.result_max     = int(self._max_var.get())
        self.result_disable_max_limit = self._disable_max_limit_var.get()
        self.result_debug   = self._debug_var.get()
        self.confirmed      = True
        self.destroy()


# ---------------------------------------------------------------------------
# Detail Pane
# ---------------------------------------------------------------------------

class DetailPane(ttk.Frame):
    def __init__(self, parent, notes: dict, on_note_saved):
        super().__init__(parent, width=DETAIL_W)
        self.notes = notes
        self.on_note_saved = on_note_saved
        self._current_id = None
        self._build_ui()

    def _build_ui(self):
        ttk.Label(self, text="Business Detail", font=("", 11, "bold")).pack(
            anchor="w", padx=10, pady=(10, 4))
        self.text = tk.Text(self, wrap="word", state="disabled",
                            font=("Consolas", 9), relief="flat",
                            bg="#f8f8f8")
        self.text.pack(fill="both", expand=True, padx=8, pady=4)

        # AI Insight section
        ai_frame = ttk.LabelFrame(self, text="AI Insight", padding=4)
        ai_frame.pack(fill="x", padx=8, pady=(0, 4))
        self._ai_text = tk.Text(ai_frame, wrap="word", state="disabled",
                                font=("Segoe UI", 8), relief="flat",
                                bg="#f0f4ff", height=4)
        self._ai_text.pack(fill="x")

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_row, text="Add / Edit Note",
                   command=self._edit_note).pack(fill="x")

    def show(self, business: dict):
        self._current_id = business.get("osm_id", "")
        tags = business.get("tags", {})
        score = business.get("score", 0)

        # Score bar (ASCII, max 20 chars wide)
        filled = round(score / 5)
        bar = "█" * filled + "░" * (20 - filled)

        lines = [
            f"{'═' * 32}",
            f"  {business.get('name', '')}",
            f"{'═' * 32}",
            "",
            f"Score:    {score}/100",
            f"          [{bar}]",
            "",
            f"Industry: {business.get('industry', '—')}",
            f"Category: {business.get('category', '—')}",
            f"Chain:    {'Yes' if business.get('is_chain') else 'No — Local Business'}",
            f"Status:   {business.get('establishment_status', '—')}",
            "",
            f"Address:  {business.get('address', '—') or '—'}",
            f"Phone:    {business.get('phone') or tags.get('phone', '—') or '—'}",
            f"Website:  {business.get('website') or tags.get('website', '—') or '—'}",
            f"Hours:    {business.get('opening_hours', '—') or '—'}",
            f"Distance: {business.get('distance_miles', '—')} mi",
            "",
            f"Audience:",
            f"  {business.get('target_audience', '—')}",
            "",
            f"── Score Breakdown ────────────────",
        ]

        breakdown = business.get("score_breakdown", {})

        # Handle profile rules mode breakdown
        if breakdown.get("mode") == "profile_rules":
            matched_rules = breakdown.get("matched_rules", [])
            for rule in matched_rules:
                label = rule.get("label", "")
                awarded = rule.get("awarded", 0)
                base = rule.get("base", awarded)
                scaled = rule.get("scaled", False)
                if scaled and base != awarded:
                    lines.append(f"  {label:<30} +{awarded} pts (scaled from {base})")
                else:
                    lines.append(f"  {label:<30} +{awarded} pts")
            priority_bonus = breakdown.get("priority_bonus", 0)
            if priority_bonus > 0:
                lines.append(f"  {'Priority bonus':<30} +{priority_bonus} pts")
            if breakdown.get("relevance_matched") is False and breakdown.get("generic_scale_without_relevance", 1.0) < 1.0:
                scale_pct = round(float(breakdown.get("generic_scale_without_relevance", 1.0)) * 100)
                lines.append(f"  {'Relevance gate':<30} Generic rules at {scale_pct}% (no sponsor match)")
        else:
            # Handle legacy mode breakdown with (pts, max_pts) tuples
            for label, value in breakdown.items():
                if isinstance(value, tuple) and len(value) == 2:
                    pts, max_pts = value
                    pct = round(pts / max_pts * 8) if max_pts else 0
                    mini_bar = "▮" * pct + "▯" * (8 - pct)
                    lines.append(f"  {label:<18} [{mini_bar}] {pts}/{max_pts}")

        # Show AI / combined scores if available
        ai_score = business.get("ai_score")
        if ai_score is not None:
            combined = business.get("combined_score", score)
            ai_reason = business.get("ai_reason", "")
            lines += [
                "",
                "── AI Score ───────────────────────",
                f"  AI score:    {ai_score}/100",
                f"  Combined:    {combined}/100",
            ]
            if ai_reason:
                lines.append(f"  Reason: {ai_reason}")

        note = self.notes.get(self._current_id, "")
        if note:
            lines += ["", "── Notes ──────────────────────────", f"  {note}"]

        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "\n".join(lines))
        self.text.config(state="disabled")

    def _edit_note(self):
        if not self._current_id:
            return
        current = self.notes.get(self._current_id, "")
        note = simpledialog.askstring(
            "Add Note",
            "Enter a note for this business:",
            initialvalue=current,
            parent=self,
        )
        if note is not None:
            self.notes[self._current_id] = note
            self.on_note_saved()

    def update_ai_insight(self, text: str):
        """Update the AI Insight section with the given text."""
        self._ai_text.config(state="normal")
        self._ai_text.delete("1.0", "end")
        self._ai_text.insert("end", text)
        self._ai_text.config(state="disabled")

    def clear(self):
        self._current_id = None
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        self._ai_text.config(state="normal")
        self._ai_text.delete("1.0", "end")
        self._ai_text.config(state="disabled")


# ---------------------------------------------------------------------------
# Sidebar Filter Panel
# ---------------------------------------------------------------------------

class FilterSidebar(ttk.Frame):
    def __init__(self, parent, on_change,
                 on_profile_load=None, on_profile_save=None, on_profile_delete=None,
                 on_profile_new=None, on_profile_edit=None,
                 on_ai_settings=None,
                 on_save_search=None, on_delete_search=None, on_load_search=None):
        super().__init__(parent, width=SIDEBAR_W)
        self.on_change = on_change
        self._on_profile_load = on_profile_load
        self._on_profile_save = on_profile_save
        self._on_profile_delete = on_profile_delete
        self._on_profile_new = on_profile_new
        self._on_profile_edit = on_profile_edit
        self._on_ai_settings = on_ai_settings
        self._on_save_search = on_save_search
        self._on_delete_search = on_delete_search
        self._on_load_search = on_load_search
        self._saved_searches: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        # ── Scrollable container ──────────────────────────────────────────
        self._canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(self, orient="vertical",
                                        command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = ttk.Frame(self._canvas)
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<Enter>", lambda _: self._bind_mousewheel())
        self._canvas.bind("<Leave>", lambda _: self._unbind_mousewheel())

        f = self._inner   # shorthand — all widgets parented here
        pad = {"padx": 8, "pady": 3}

        # ── Profiles section ─────────────────────────────────────────────
        ttk.Label(f, text="Profiles", font=("", 10, "bold")).pack(
            anchor="w", **pad)
        ttk.Separator(f).pack(fill="x", padx=8, pady=2)

        self.profile_var = tk.StringVar(value="")
        self.profile_combo = ttk.Combobox(f, textvariable=self.profile_var,
                                          state="readonly", values=[])
        self.profile_combo.pack(fill="x", **pad)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_load_click())

        prof_btns = ttk.Frame(f)
        prof_btns.pack(fill="x", **pad)
        ttk.Button(prof_btns, text="New",
                   command=self._on_new_profile).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(prof_btns, text="Edit",
                   command=self._on_edit_profile).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(prof_btns, text="Delete",
                   command=self._on_delete_click).pack(side="left", expand=True, fill="x", padx=1)

        ttk.Separator(f).pack(fill="x", padx=8, pady=6)

        # ── AI Scoring section ────────────────────────────────────────────
        ttk.Label(f, text="AI Scoring (Local LLM)", font=("", 10, "bold")).pack(
            anchor="w", **pad)
        ttk.Separator(f).pack(fill="x", padx=8, pady=2)

        ai_status_row = ttk.Frame(f)
        ai_status_row.pack(fill="x", **pad)
        self._ai_dot = tk.Label(ai_status_row, text="●", font=("", 10), fg="#95a5a6")
        self._ai_dot.pack(side="left")
        self._ai_status_lbl = ttk.Label(ai_status_row, text="AI offline", foreground="gray",
                                         font=("Segoe UI", 8))
        self._ai_status_lbl.pack(side="left", padx=4)

        self.ai_scoring_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Enable AI Scoring",
                        variable=self.ai_scoring_var).pack(anchor="w", **pad)

        if self._on_ai_settings:
            ttk.Button(f, text="AI Settings…",
                       command=self._on_ai_settings).pack(fill="x", **pad)

        ttk.Separator(f).pack(fill="x", padx=8, pady=6)

        # ── Filter & Sort section ────────────────────────────────────────
        ttk.Label(f, text="Filter & Sort", font=("", 10, "bold")).pack(
            anchor="w", **pad)
        ttk.Separator(f).pack(fill="x", padx=8, pady=2)

        # Name search
        ttk.Label(f, text="Name search:").pack(anchor="w", **pad)
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *_: self.on_change())
        ttk.Entry(f, textvariable=self.name_var).pack(fill="x", **pad)

        # Category dropdown
        ttk.Label(f, text="Category:").pack(anchor="w", **pad)
        self.cat_var = tk.StringVar(value="All")
        self.cat_var.trace_add("write", lambda *_: self.on_change())
        self.cat_combo = ttk.Combobox(f, textvariable=self.cat_var,
                                      state="readonly", values=["All"])
        self.cat_combo.pack(fill="x", **pad)

        # Hide chains
        self.hide_chains_var = tk.BooleanVar(value=False)
        self.hide_chains_var.trace_add("write", lambda *_: self.on_change())
        ttk.Checkbutton(f, text="Hide chains",
                        variable=self.hide_chains_var).pack(anchor="w", **pad)

        # Min score
        ttk.Label(f, text="Min score:").pack(anchor="w", **pad)
        self.min_score_var = tk.IntVar(value=0)
        self.min_score_label = ttk.Label(f, text="0")
        self.min_score_label.pack(anchor="e", padx=8)
        self.score_slider = ttk.Scale(
            f, from_=0, to=100,
            variable=self.min_score_var,
            command=self._on_score_slide,
        )
        self.score_slider.pack(fill="x", **pad)

        ttk.Separator(f).pack(fill="x", padx=8, pady=6)

        # ── Operating Status section ──────────────────────────────────────
        ttk.Label(f, text="Operating Status", font=("", 9, "bold")).pack(
            anchor="w", **pad)
        self.open_now_var = tk.BooleanVar(value=False)
        self.open_now_var.trace_add("write", lambda *_: self.on_change())
        ttk.Checkbutton(f, text="Open now",
                        variable=self.open_now_var).pack(anchor="w", **pad)

        ttk.Separator(f).pack(fill="x", padx=8, pady=6)

        # ── Attributes section ────────────────────────────────────────────
        ttk.Label(f, text="Attributes", font=("", 9, "bold")).pack(
            anchor="w", **pad)
        self.wheelchair_var = tk.BooleanVar(value=False)
        self.wheelchair_var.trace_add("write", lambda *_: self.on_change())
        ttk.Checkbutton(f, text="Wheelchair accessible",
                        variable=self.wheelchair_var).pack(anchor="w", **pad)

        self.outdoor_seating_var = tk.BooleanVar(value=False)
        self.outdoor_seating_var.trace_add("write", lambda *_: self.on_change())
        ttk.Checkbutton(f, text="Outdoor seating",
                        variable=self.outdoor_seating_var).pack(anchor="w", **pad)

        self.delivery_var = tk.BooleanVar(value=False)
        self.delivery_var.trace_add("write", lambda *_: self.on_change())
        ttk.Checkbutton(f, text="Delivery",
                        variable=self.delivery_var).pack(anchor="w", **pad)

        self.takeout_var = tk.BooleanVar(value=False)
        self.takeout_var.trace_add("write", lambda *_: self.on_change())
        ttk.Checkbutton(f, text="Takeout / takeaway",
                        variable=self.takeout_var).pack(anchor="w", **pad)

        # ── AI Attribute Filter ───────────────────────────────────────────
        ttk.Separator(f).pack(fill="x", padx=8, pady=4)
        ttk.Label(f, text="AI: custom attribute", font=("Segoe UI", 8, "italic"),
                  foreground="#555").pack(anchor="w", padx=8)
        self._ai_attr_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._ai_attr_var).pack(fill="x", **pad)
        ai_attr_row = ttk.Frame(f)
        ai_attr_row.pack(fill="x", **pad)
        ttk.Button(ai_attr_row, text="Apply",
                   command=self._apply_ai_attr).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(ai_attr_row, text="Clear",
                   command=self._clear_ai_attr).pack(side="left", expand=True, fill="x", padx=1)
        self._ai_attr_status = ttk.Label(f, text="", foreground="#7f8c8d",
                                         font=("Segoe UI", 7), wraplength=SIDEBAR_W - 20)
        self._ai_attr_status.pack(anchor="w", padx=8)
        # Runtime state
        self._ai_attr_matches: set | None = None   # None = inactive
        self._on_ai_attr_filter = None             # set by App after init

        ttk.Separator(f).pack(fill="x", padx=8, pady=6)

        # Sort
        ttk.Label(f, text="Sort by:").pack(anchor="w", **pad)
        self.sort_var = tk.StringVar(value="Score")
        self.sort_var.trace_add("write", lambda *_: self.on_change())
        ttk.Combobox(
            f, textvariable=self.sort_var, state="readonly",
            values=["Score", "Distance", "Name", "Category",
                    "Completeness", "Has Phone", "Has Website", "AI Score"],
        ).pack(fill="x", **pad)

        self.sort_desc_var = tk.BooleanVar(value=True)
        self.sort_desc_var.trace_add("write", lambda *_: self.on_change())
        ttk.Checkbutton(f, text="Descending",
                        variable=self.sort_desc_var).pack(anchor="w", padx=8, pady=1)

        ttk.Separator(f).pack(fill="x", padx=8, pady=6)

        # ── Saved Searches section ────────────────────────────────────────
        ttk.Label(f, text="Saved Searches", font=("", 9, "bold")).pack(
            anchor="w", **pad)
        self._saved_search_var = tk.StringVar()
        self._saved_search_combo = ttk.Combobox(
            f, textvariable=self._saved_search_var, state="readonly", values=[])
        self._saved_search_combo.pack(fill="x", **pad)
        self._saved_search_combo.bind("<<ComboboxSelected>>", self._load_search)

        ss_btns = ttk.Frame(f)
        ss_btns.pack(fill="x", **pad)
        ttk.Button(ss_btns, text="Save Search",
                   command=self._save_search).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(ss_btns, text="Delete",
                   command=self._delete_search).pack(side="left", expand=True, fill="x", padx=1)

        ttk.Separator(f).pack(fill="x", padx=8, pady=6)

        # Custom filter button
        self.custom_filter_btn = ttk.Button(f, text="Build Custom Filter",
                                            command=self._open_custom_filter)
        self.custom_filter_btn.pack(fill="x", **pad)
        self.custom_filter_label = ttk.Label(f, text="", foreground="#e67e22",
                                             wraplength=SIDEBAR_W - 20)
        self.custom_filter_label.pack(anchor="w", **pad)
        ttk.Button(f, text="Clear Custom Filter",
                   command=self._clear_custom_filter).pack(fill="x", **pad)

        ttk.Separator(f).pack(fill="x", padx=8, pady=6)

        # Reset
        ttk.Button(f, text="Reset All Filters",
                   command=self._reset).pack(fill="x", **pad)

        # Store custom filter state
        self._custom_rules = []
        self._custom_combine = "AND"

    def _on_inner_configure(self, event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event=None):
        self._canvas.itemconfig(self._canvas_win, width=event.width)

    def _bind_mousewheel(self):
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self):
        self._canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── Profile button handlers ───────────────────────────────────────────

    def _on_new_profile(self):
        if self._on_profile_new:
            self._on_profile_new()

    def _on_edit_profile(self):
        name = self.profile_var.get()
        if name and self._on_profile_edit:
            self._on_profile_edit(name)

    def _on_load_click(self):
        name = self.profile_var.get()
        if self._on_profile_load:
            self._on_profile_load(name)

    def _on_save_click(self):
        if self._on_profile_save:
            self._on_profile_save()

    def _on_delete_click(self):
        name = self.profile_var.get()
        if name and self._on_profile_delete:
            self._on_profile_delete(name)

    # ── Saved search handlers ─────────────────────────────────────────────

    def _save_search(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("Save Search", "Name for this search:", parent=self)
        if name and name.strip():
            if self._on_save_search:
                self._on_save_search(name.strip(), self.get_state())

    def _delete_search(self):
        name = self._saved_search_var.get()
        if name and self._on_delete_search:
            self._on_delete_search(name)

    def _load_search(self, event=None):
        name = self._saved_search_var.get()
        if name and self._on_load_search:
            self._on_load_search(name)

    def refresh_saved_searches(self, searches: list[dict]):
        self._saved_searches = searches
        names = [s["name"] for s in searches]
        self._saved_search_combo["values"] = names

    def set_ai_status(self, running: bool):
        """Update the AI status dot and label."""
        if running:
            self._ai_dot.config(fg="#27ae60")
            self._ai_status_lbl.config(text="AI ready", foreground="#27ae60")
        else:
            self._ai_dot.config(fg="#95a5a6")
            self._ai_status_lbl.config(text="AI offline", foreground="gray")

    def update_profiles(self, names: list[str]):
        """Refresh the profile dropdown with the given list of names."""
        values = ["No profile"] + [n for n in names if n != "No profile"]
        self.profile_combo["values"] = values
        if self.profile_var.get() not in values:
            self.profile_var.set(values[0] if values else "")

    def set_state(self, state: dict):
        """Restore filter/sort controls from a state dict (e.g. loaded from a profile)."""
        if "name_query" in state:
            self.name_var.set(state["name_query"])
        if "category" in state:
            cat = state.get("category", "All")
            available = list(self.cat_combo["values"])
            self.cat_var.set(cat if cat in available else "All")
        if "hide_chains" in state:
            self.hide_chains_var.set(state["hide_chains"])
        if "min_score" in state:
            v = int(state["min_score"])
            self.min_score_var.set(v)
            self.min_score_label.config(text=str(v))
        if "sort_by" in state:
            self.sort_var.set(state.get("sort_by", "Score"))
        if "sort_descending" in state:
            self.sort_desc_var.set(bool(state["sort_descending"]))
        if "custom_rules" in state:
            self._custom_rules = list(state["custom_rules"])
        if "custom_combine" in state:
            self._custom_combine = state["custom_combine"]
            n = len(self._custom_rules)
            self.custom_filter_label.config(
                text=f"{n} rule{'s' if n != 1 else ''} active ({self._custom_combine})"
                if n else ""
            )
        if "open_now" in state:
            self.open_now_var.set(bool(state["open_now"]))
        if "has_wheelchair" in state:
            self.wheelchair_var.set(bool(state["has_wheelchair"]))
        if "has_outdoor_seating" in state:
            self.outdoor_seating_var.set(bool(state["has_outdoor_seating"]))
        if "has_delivery" in state:
            self.delivery_var.set(bool(state["has_delivery"]))
        if "has_takeout" in state:
            self.takeout_var.set(bool(state["has_takeout"]))
        # AI attr filter is session-only; intentionally not restored from saved state

    # ── Score slider ──────────────────────────────────────────────────────

    def _on_score_slide(self, val):
        self.min_score_label.config(text=str(int(float(val))))
        self.on_change()

    def _open_custom_filter(self):
        dlg = CustomFilterDialog(self, self._custom_rules, self._custom_combine)
        self.wait_window(dlg)
        if dlg.result_rules is not None:
            self._custom_rules   = dlg.result_rules
            self._custom_combine = dlg.result_combine
            n = len(self._custom_rules)
            self.custom_filter_label.config(
                text=f"{n} rule{'s' if n != 1 else ''} active ({self._custom_combine})"
                if n else ""
            )
            self.on_change()

    def _clear_custom_filter(self):
        self._custom_rules = []
        self._custom_combine = "AND"
        self.custom_filter_label.config(text="")
        self.on_change()

    # ── AI attribute filter handlers ──────────────────────────────────────

    def _apply_ai_attr(self):
        query = self._ai_attr_var.get().strip()
        if not query:
            return
        if self._on_ai_attr_filter:
            self._on_ai_attr_filter(query)

    def _clear_ai_attr(self):
        self._ai_attr_matches = None
        self._ai_attr_var.set("")
        self._ai_attr_status.config(text="")
        self.on_change()

    def set_ai_attr_status(self, text: str):
        self._ai_attr_status.config(text=text)

    def set_ai_attr_matches(self, matches: set | None):
        self._ai_attr_matches = matches
        self.on_change()

    def _reset(self):
        self.name_var.set("")
        self.cat_var.set("All")
        self.hide_chains_var.set(False)
        self.min_score_var.set(0)
        self.min_score_label.config(text="0")
        self.sort_var.set("Score")
        self.sort_desc_var.set(True)
        self.open_now_var.set(False)
        self.wheelchair_var.set(False)
        self.outdoor_seating_var.set(False)
        self.delivery_var.set(False)
        self.takeout_var.set(False)
        self._clear_ai_attr()
        self._clear_custom_filter()

    def update_categories(self, categories: list[str]):
        current = self.cat_var.get()
        self.cat_combo["values"] = categories
        if current not in categories:
            self.cat_var.set("All")

    def get_state(self) -> dict:
        return {
            "name_query":          self.name_var.get(),
            "category":            self.cat_var.get(),
            "hide_chains":         self.hide_chains_var.get(),
            "min_score":           int(self.min_score_var.get()),
            "sort_by":             self.sort_var.get(),
            "sort_descending":     self.sort_desc_var.get(),
            "custom_rules":        self._custom_rules,
            "custom_combine":      self._custom_combine,
            "open_now":            self.open_now_var.get(),
            "has_wheelchair":      self.wheelchair_var.get(),
            "has_outdoor_seating": self.outdoor_seating_var.get(),
            "has_delivery":        self.delivery_var.get(),
            "has_takeout":         self.takeout_var.get(),
            "ai_attr_active":      self._ai_attr_matches is not None,
            "ai_attr_matches":     self._ai_attr_matches or set(),
        }


# ---------------------------------------------------------------------------
# Comparison View
# ---------------------------------------------------------------------------

class CompareDialog(tk.Toplevel):
    """Side-by-side comparison of up to 6 businesses."""

    _ROWS = [
        ("Score",           lambda b, _: f"{b.get('score', 0)}/100"),
        ("Industry",        lambda b, _: b.get("industry", "")),
        ("Entity Type",     lambda b, _: b.get("entity_type", "")),
        ("Chain?",          lambda b, _: "Yes" if b.get("is_chain") else "No"),
        ("Distance",        lambda b, _: f"{b.get('distance_miles', 0):.1f} mi"),
        ("Phone",           lambda b, _: b.get("phone") or b.get("tags", {}).get("phone", "") or "—"),
        ("Website",         lambda b, _: b.get("website") or b.get("tags", {}).get("website", "") or "—"),
        ("Address",         lambda b, _: b.get("address", "") or "—"),
        ("Target Audience", lambda b, _: b.get("target_audience", b.get("audience_overlap", "")) or "—"),
        ("OSM Completeness",lambda b, _: f"{b.get('osm_completeness', 0)}%"),
        ("Notes",           lambda b, notes: notes.get(b.get("osm_id", ""), "") or "—"),
    ]

    def __init__(self, parent, businesses: list[dict], notes: dict):
        super().__init__(parent)
        self.title("Compare Businesses")
        n = len(businesses)
        width = min(1400, max(700, n * 230))
        self.geometry(f"{width}x520")
        self.minsize(500, 400)
        self.resizable(True, True)

        # Pack button FIRST so it always gets its space before the canvas expands.
        ttk.Button(self, text="Close", command=self.destroy).pack(side="bottom", pady=8)

        # Outer canvas + horizontal scrollbar for overflow when many columns
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0, bd=0)
        hsb = ttk.Scrollbar(outer, orient="horizontal", command=canvas.xview)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner(*_):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas(e):
            canvas.itemconfigure(win, height=max(e.height, inner.winfo_reqheight()))
        inner.bind("<Configure>", _on_inner)
        canvas.bind("<Configure>", _on_canvas)

        def _mwheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _mwheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        # Row-label column
        ttk.Label(inner, text="", width=18).grid(row=0, column=0, padx=4, pady=4, sticky="nw")
        for row_idx, (label, _) in enumerate(self._ROWS, start=1):
            ttk.Label(inner, text=label, font=("", 9, "bold"), anchor="w").grid(
                row=row_idx, column=0, padx=(8, 4), pady=3, sticky="nw"
            )

        # One column per business
        for col_idx, biz in enumerate(businesses, start=1):
            frm = ttk.LabelFrame(inner, text=biz.get("name", f"Business {col_idx}"),
                                 padding=(6, 4))
            frm.grid(row=0, column=col_idx, padx=4, pady=(6, 2), sticky="nsew")
            inner.columnconfigure(col_idx, weight=1, minsize=200)

            for row_idx, (_, extractor) in enumerate(self._ROWS, start=1):
                value = extractor(biz, notes)
                lbl = ttk.Label(inner, text=value, wraplength=190, justify="left",
                                anchor="nw", foreground="#2c3e50")
                lbl.grid(row=row_idx, column=col_idx, padx=(8, 4), pady=3, sticky="nw")




# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        apply_icon(self)

        # Ensure data folder exists before loading any data files
        get_data_dir()
        ensure_data_files_exist()

        # Legacy external-runtime installer flow was removed; keep startup non-blocking.
        # AI features remain optional and are enabled only if local models exist.
        if is_windows() and not ai_scoring.list_models():
            pass

        self._config = load_config()
        debug_cfg = self._config.get("debug_settings", {})
        ai_cfg_boot = self._config.get("ai_settings", {})
        applog.setup(
            debug=bool(ai_cfg_boot.get("debug_mode", False)),
            file_logging=bool(debug_cfg.get("store_logs", True)),
        )
        self._notes  = load_notes()
        self._all_businesses: list[dict] = []
        self._shortlist: set[str] = load_shortlist()  # persisted OSM IDs
        self._history: list[dict] = load_history()
        self._saved_searches: list[dict] = load_saved_searches()
        self._collections: dict = load_collections()
        self._search_lat  = None
        self._search_lon  = None
        self._search_cancellation_token: CancellationToken | None = None
        self._search_radius = self._config.get("last_radius_miles", 5.0)
        self._max_results_limit = int(self._config.get("last_max_results", MAX_RESULTS))
        self._max_results_limit = max(50, min(MAX_RESULTS, self._max_results_limit))
        self._profiles: list[dict] = load_profiles()

        # AI state
        ai_cfg = self._config.get("ai_settings", {})
        self._ai_model          = ai_cfg.get("model", ai_scoring.DEFAULT_MODEL)
        self._ai_weight         = max(0.0, min(1.0, float(ai_cfg.get("weight", 0.5))))
        self._ai_explain_on     = bool(ai_cfg.get("explain_on", True))
        self._ai_scoring_on     = bool(ai_cfg.get("scoring_on", False))
        self._ai_max_score      = max(10, int(ai_cfg.get("max_score", 500)))
        self._ai_disable_max_limit = bool(ai_cfg.get("disable_max_limit", True))
        self._ai_debug          = bool(ai_cfg.get("debug_mode", False))
        if self._ai_debug:
            os.environ["DEBUG"] = "1"
        else:
            os.environ.pop("DEBUG", None)
        self._ai_running        = False   # is local AI model loaded?
        self._ai_prompt_active  = False

        self._dark_mode: bool = bool(self._config.get("dark_mode", False))

        self._apply_window_geometry()
        self._build_ui()
        # Apply the saved theme after UI is constructed
        self._apply_theme(self._dark_mode)
        self._sidebar.ai_scoring_var.set(self._ai_scoring_on)
        self._sidebar.ai_scoring_var.trace_add(
            "write", lambda *_: self._update_score_column_heading()
        )
        # Populate profile dropdown after sidebar is built
        profile_names = [p["name"] for p in self._profiles]
        self._sidebar.update_profiles(profile_names)
        if "Car Meet Sponsor" in profile_names:
            self._sidebar.profile_var.set("Car Meet Sponsor")
            self._on_profile_load("Car Meet Sponsor")
        elif profile_names:
            first_profile = profile_names[0]
            self._sidebar.profile_var.set(first_profile)
            self._on_profile_load(first_profile)
        else:
            self._sidebar.profile_var.set("No profile")
        # Async AI model status check
        self._check_ai_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _open_ai_setup(self):
        """Legacy compatibility hook; no installer dialog is available in this build."""
        messagebox.showinfo(
            "AI Setup",
            "AI uses local models. Download a model from AI Settings (Download Models tab).",
        )

    # Backward compatibility alias
    def _run_ollama_setup(self):
        self._open_ai_setup()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_theme(self, dark: bool) -> None:
        """Apply light or dark theme and persist the preference."""
        self._dark_mode = dark
        self._config["dark_mode"] = dark
        save_config(self._config)

        _theme.apply_theme(self, dark)
        p = _theme.get_palette(dark)

        # Update treeview row-color tags
        if hasattr(self, "_tree"):
            self._tree.tag_configure("green", background=p["tree_green"])
            self._tree.tag_configure("red",   background=p["tree_red"])
            self._tree.tag_configure("odd",   background=p["tree_odd"])
            self._tree.tag_configure("even",  background=p["tree_even"])

        # Update detail pane text widget backgrounds
        if hasattr(self, "_detail"):
            try:
                self._detail.text.configure(bg=p["detail_bg"], fg=p["fg"],
                                            insertbackground=p["fg"])
                self._detail._ai_text.configure(bg=p["ai_bg"], fg=p["fg"],
                                                insertbackground=p["fg"])
            except Exception:
                pass

        # Sync menu checkbutton if already created
        if hasattr(self, "_dark_mode_var"):
            self._dark_mode_var.set(dark)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _apply_window_geometry(self):
        w = self._config["window"]
        width  = max(w["width"],  MIN_WIDTH)
        height = max(w["height"], MIN_HEIGHT)
        self.geometry(f"{width}x{height}+{w['x']}+{w['y']}")

    def _save_window_geometry(self):
        self._config["window"] = {
            "width":  self.winfo_width(),
            "height": self.winfo_height(),
            "x":      self.winfo_x(),
            "y":      self.winfo_y(),
        }

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        build_menu_bar(self, self)
        self._build_top_bar()
        self._build_bottom_bar()   # must come before main area — pack(expand=True) steals space
        self._build_main_area()

    def _build_top_bar(self):
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x", side="top")

        # ── Location section ──────────────────────────────────────────────
        # No mode-switching radio buttons. One combobox handles everything:
        # type an address directly, or pick from the saved locations dropdown.
        loc_frame = ttk.Frame(bar)
        loc_frame.pack(side="left")

        loc_row = ttk.Frame(loc_frame)
        loc_row.pack(fill="x")

        ttk.Label(loc_row, text="📍").pack(side="left", padx=(2, 1))

        self._addr_var = tk.StringVar()
        self._loc_combo = ttk.Combobox(loc_row, textvariable=self._addr_var, width=30)
        self._loc_combo.pack(side="left", padx=(0, 4))
        self._loc_combo.bind("<Return>", lambda _: self._trigger_search())
        self._loc_combo.bind("<<ComboboxSelected>>", self._on_saved_location_selected)
        self._loc_combo.bind("<Key>", self._on_loc_field_edited)

        self._hw_loc_btn = ttk.Button(loc_row, text="◉ My Location",
                                      command=self._request_topbar_location, width=13)
        self._hw_loc_btn.pack(side="left", padx=2)

        ttk.Button(loc_row, text="🗺 Map",
                   command=self._open_pin_dialog, width=7).pack(side="left", padx=2)

        ttk.Button(loc_row, text="💾 Save",
                   command=self._save_current_location, width=7).pack(side="left", padx=2)

        # Small resolved-coords readout — hidden until a location is set
        self._coord_label = ttk.Label(
            loc_frame, text="", foreground="#7f8c8d",
            font=("Segoe UI", 7, "italic"),
        )
        self._coord_label.pack(anchor="w", padx=(20, 0))

        # Flag used to suppress coord-clearing when we set the field from code
        self._setting_location_programmatically = False

        # Populate dropdown and restore last location from config
        self._refresh_saved_locations_dropdown()
        self._restore_last_location()

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        # Radius slider
        ttk.Label(bar, text="Radius:").pack(side="left")
        self._radius_var = tk.DoubleVar(value=self._search_radius)
        self._radius_label = ttk.Label(bar, text=f"{self._search_radius:.1f} mi", width=7)
        self._radius_label.pack(side="left")
        ttk.Scale(bar, from_=0.5, to=25.0, variable=self._radius_var,
                  orient="horizontal", length=140,
                  command=self._on_radius_change).pack(side="left", padx=4)

        ttk.Label(bar, text="Max businesses:").pack(side="left", padx=(8, 0))
        self._max_results_var = tk.IntVar(value=self._max_results_limit)
        self._max_results_label = ttk.Label(bar, text=str(self._max_results_limit), width=4)
        self._max_results_label.pack(side="left")
        ttk.Scale(
            bar,
            from_=50,
            to=MAX_RESULTS,
            variable=self._max_results_var,
            orient="horizontal",
            length=120,
            command=self._on_max_results_change,
        ).pack(side="left", padx=4)

        # Search button
        self._search_btn = ttk.Button(bar, text="Search", command=self._trigger_search)
        self._search_btn.pack(side="left", padx=8)

    def _build_main_area(self):
        outer_paned = ttk.PanedWindow(self, orient="horizontal")
        outer_paned.pack(fill="both", expand=True, padx=4, pady=4)

        # --- Sidebar ---
        self._sidebar = FilterSidebar(
            outer_paned,
            on_change=self._apply_filters,
            on_profile_load=self._on_profile_load,
            on_profile_save=self._on_profile_save,
            on_profile_delete=self._on_profile_delete,
            on_profile_new=self._on_profile_new,
            on_profile_edit=self._on_profile_edit,
            on_ai_settings=self._open_ai_settings,
            on_save_search=self._save_search,
            on_delete_search=self._delete_search,
            on_load_search=self._load_search,
        )
        self._sidebar._on_ai_attr_filter = self._run_ai_attr_filter
        self._sidebar.refresh_saved_searches(self._saved_searches)
        outer_paned.add(self._sidebar, weight=0)

        # --- Results | Detail (ttk.PanedWindow — matches the left sidebar sash) ---
        inner_paned = ttk.PanedWindow(outer_paned, orient="horizontal")
        outer_paned.add(inner_paned, weight=1)

        results_frame = ttk.Frame(inner_paned)
        self._build_treeview(results_frame)
        inner_paned.add(results_frame, weight=1)

        self._detail = DetailPane(inner_paned, self._notes, on_note_saved=self._on_note_saved)
        inner_paned.add(self._detail, weight=0)

    def _build_treeview(self, parent):
        # Columns include a hidden checkbox-equivalent: managed via selection + shortlist set
        cols = ("shortlist",) + TREE_COLUMNS
        self._tree = ttk.Treeview(parent, columns=cols, show="headings",
                                  selectmode="extended")

        # Shortlist column
        self._tree.heading("shortlist", text="★")
        self._tree.column("shortlist", width=28, stretch=False, anchor="center")

        for col in TREE_COLUMNS:
            self._tree.heading(
                col, text=TREE_HEADINGS[col],
                command=lambda c=col: self._sort_by_column(c),
            )
            self._tree.column(col, width=COL_WIDTHS[col], stretch=(col == "name"))

        # Scrollbars
        vsb = ttk.Scrollbar(parent, orient="vertical", command=self._tree.yview)
        hsb = ttk.Scrollbar(parent, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        # Row color tags — green ≥70, red <40, alternating odd/even for 40–69
        # (re-configured by _apply_theme whenever the mode changes)
        p = _theme.get_palette(getattr(self, "_dark_mode", False))
        self._tree.tag_configure("green", background=p["tree_green"])
        self._tree.tag_configure("red",   background=p["tree_red"])
        self._tree.tag_configure("odd",   background=p["tree_odd"])
        self._tree.tag_configure("even",  background=p["tree_even"])
        self._tree.tag_configure("shortlisted", foreground="#1a5276", font=("", 9, "bold"))

        self._tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self._tree.bind("<Double-1>",         self._on_row_double_click)
        self._tree.bind("<space>",            self._on_row_space)
        self._tree.bind("<Button-3>",         self._on_row_right_click)

        # Map iid → business dict
        self._iid_map: dict[str, dict] = {}

    def _build_bottom_bar(self):
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(fill="x", side="bottom")

        # Right-side items must be packed before left-side expand=True items,
        # otherwise pack has already given all space to the expanding widget.
        ttk.Button(bar, text="Export Shortlist CSV",
                   command=self._export_csv).pack(side="right", padx=4)
        ttk.Button(bar, text="Export JSON",
                   command=self._export_json).pack(side="right", padx=2)
        ttk.Button(bar, text="History",
                   command=self._show_history).pack(side="right", padx=2)

        self._count_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self._count_var).pack(side="right", padx=8)

        # Progress + Cancel live in a sub-frame so the cancel button always
        # appears immediately to the left of the progress bar.
        prog_frame = ttk.Frame(bar)
        prog_frame.pack(side="right", padx=4)

        self._progress = ttk.Progressbar(prog_frame, mode="indeterminate", length=120)
        self._progress.pack(side="right")

        self._cancel_btn = ttk.Button(prog_frame, text="Cancel",
                                      command=self._on_cancel_search)
        # Hidden until a search is active

        self._status_var = tk.StringVar(value="Ready. Enter a location and click Search.")
        ttk.Label(bar, textvariable=self._status_var, anchor="w").pack(side="left", fill="x",
                                                                        expand=True)

    @staticmethod
    def _get_device_location(timeout: float = 8.0):
        """
        Try to get the user's current position from OS/hardware location services.
        Returns (lat, lon) on success, or None if no provider is available.
        Raises PermissionError if the OS explicitly denies location access.
        Never contacts any IP geolocation service.

        Windows priority:
          1. WinRT  (Windows.Devices.Geolocation — GPS/WiFi/cell, requires winrt pkg)
          2. PowerShell + System.Device.Location  (no extra packages, same OS service)
        macOS:
          3. CoreLocation via pyobjc-framework-CoreLocation (if installed)
        Linux:
          4. GeoClue2 via dbus-python (if installed)
        """
        import sys

        # ── Windows ────────────────────────────────────────────────────────────
        if sys.platform == "win32":

            # 1 — WinRT (modern Windows 10/11, accurate GPS/WiFi triangulation)
            try:
                import asyncio
                import winrt.windows.devices.geolocation as wdg  # type: ignore

                async def _winrt_get():
                    locator = wdg.Geolocator()
                    pos = await locator.get_geoposition_async()
                    c = pos.coordinate
                    return c.latitude, c.longitude

                # Use a dedicated event loop — avoids "already running" conflicts
                # when called from a background thread.
                loop = asyncio.new_event_loop()
                try:
                    coro = asyncio.wait_for(_winrt_get(), timeout=timeout)
                    return loop.run_until_complete(coro)
                finally:
                    loop.close()

            except ImportError:
                pass  # winrt not installed — try PowerShell fallback
            except asyncio.TimeoutError:
                pass  # location service too slow — try PowerShell fallback
            except Exception as e:
                err = str(e).lower()
                if any(k in err for k in ("access", "denied", "80070005", "permission")):
                    raise PermissionError(
                        "Location access denied.\n"
                        "Enable it in Windows Settings → Privacy & Security → Location."
                    )
                # Other WinRT failures — fall through to PowerShell

            # 2 — PowerShell + .NET System.Device.Location (no extra packages)
            try:
                import subprocess
                ps = (
                    "Add-Type -AssemblyName System.Device; "
                    "$w = [System.Device.Location.GeoCoordinateWatcher]::new(); "
                    "$w.Start(); "
                    "$deadline = [DateTime]::UtcNow.AddSeconds(6); "
                    "while ($w.Position.Location.IsUnknown -and "
                    "       [DateTime]::UtcNow -lt $deadline) "
                    "{ Start-Sleep -Milliseconds 300 }; "
                    "if ($w.Position.Location.IsUnknown) { exit 1 }; "
                    "$c = $w.Position.Location; "
                    "Write-Output \"$($c.Latitude),$($c.Longitude)\""
                )
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    capture_output=True, text=True, timeout=int(timeout) + 4,
                )
                if r.returncode == 0:
                    parts = r.stdout.strip().split(",", 1)
                    if len(parts) == 2:
                        return float(parts[0]), float(parts[1])
            except Exception:
                pass

        # ── macOS ──────────────────────────────────────────────────────────────
        elif sys.platform == "darwin":
            try:
                import time
                from CoreLocation import CLLocationManager  # type: ignore  (pyobjc)
                mgr = CLLocationManager.alloc().init()
                mgr.startUpdatingLocation()
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    loc = mgr.location()
                    if loc is not None:
                        c = loc.coordinate()
                        return c.latitude, c.longitude
                    time.sleep(0.3)
            except ImportError:
                pass  # pyobjc-framework-CoreLocation not installed
            except Exception as e:
                if "denied" in str(e).lower() or "restricted" in str(e).lower():
                    raise PermissionError(
                        "Location access denied.\n"
                        "Allow it in System Settings → Privacy & Security → Location Services."
                    )

        # ── Linux ──────────────────────────────────────────────────────────────
        elif sys.platform.startswith("linux"):
            try:
                import time
                import dbus  # type: ignore  (dbus-python)
                bus = dbus.SystemBus()
                mgr_iface = dbus.Interface(
                    bus.get_object("org.freedesktop.GeoClue2",
                                   "/org/freedesktop/GeoClue2/Manager"),
                    "org.freedesktop.GeoClue2.Manager",
                )
                client_path = str(mgr_iface.GetClient())
                client_obj = bus.get_object("org.freedesktop.GeoClue2", client_path)
                dbus.Interface(client_obj, "org.freedesktop.GeoClue2.Client").Start()
                props = dbus.Interface(client_obj, "org.freedesktop.DBus.Properties")
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    loc_path = str(props.Get("org.freedesktop.GeoClue2.Client", "Location"))
                    if loc_path != "/":
                        loc_props = dbus.Interface(
                            bus.get_object("org.freedesktop.GeoClue2", loc_path),
                            "org.freedesktop.DBus.Properties",
                        )
                        lat = float(loc_props.Get("org.freedesktop.GeoClue2.Location", "Latitude"))
                        lon = float(loc_props.Get("org.freedesktop.GeoClue2.Location", "Longitude"))
                        return lat, lon
                    time.sleep(0.4)
            except ImportError:
                pass  # dbus-python not installed
            except Exception as e:
                if "denied" in str(e).lower():
                    raise PermissionError("Location access denied by GeoClue2.")

        return None

    def _open_pin_dialog(self):
        # Try to use tkintermapview for an interactive map; fall back to text entry.
        try:
            import tkintermapview as tmv
            _HAS_MAP = True
        except ImportError:
            _HAS_MAP = False

        if not _HAS_MAP:
            self._open_pin_dialog_text()
            return

        import threading

        dlg = tk.Toplevel(self)
        dlg.title("Drop a Pin — click the map to place your pin")
        dlg.grab_set()
        dlg.resizable(True, True)
        dlg.minsize(640, 520)

        # coordinate readout bar
        info_bar = ttk.Frame(dlg)
        info_bar.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(info_bar, text="Pinned location:").pack(side="left")
        coord_var = tk.StringVar(value="Click the map to drop a pin")
        ttk.Label(info_bar, textvariable=coord_var, foreground="#c0392b",
                  font=("Consolas", 9, "bold")).pack(side="left", padx=6)

        # location status label (shown while locating)
        loc_status_var = tk.StringVar(value="")
        loc_status_lbl = ttk.Label(info_bar, textvariable=loc_status_var,
                                   foreground="gray", font=("Segoe UI", 8, "italic"))
        loc_status_lbl.pack(side="right", padx=8)

        # map widget — use a persistent tile cache so tiles are only downloaded once.
        # Set the initial view before pack so the first render loads the right tiles.
        map_widget = tmv.TkinterMapView(dlg, width=640, height=420, corner_radius=0,
                                        database_path=get_tile_cache_path())
        if self._search_lat and self._search_lon:
            map_widget.set_position(self._search_lat, self._search_lon)
            map_widget.set_zoom(13)
        else:
            # Continental US center — a reasonable starting view
            map_widget.set_position(39.5, -98.35)
            map_widget.set_zoom(4)
        map_widget.pack(fill="both", expand=True, padx=8, pady=6)

        # manually_pinned: True once the user has clicked the map themselves,
        # so an auto-located marker doesn't overwrite an intentional pin.
        # use_loc_btn: stored here so _request_device_location can reference it
        # before the widget is constructed (populated right after btn creation).
        _state = {
            "marker": None, "lat": None, "lon": None,
            "located": False, "manually_pinned": False,
            "use_loc_btn": None,
        }

        def _fly_to(lat, lon, zoom=13):
            map_widget.set_position(lat, lon)
            map_widget.set_zoom(zoom)

        def _request_device_location():
            """Kick off a background hardware-location request and update the map."""
            if not dlg.winfo_exists():
                return
            loc_status_var.set("Requesting location from system…")
            btn = _state.get("use_loc_btn")
            if btn:
                btn.config(state="disabled")

            def _locate():
                try:
                    result = self._get_device_location()
                    err = None
                except PermissionError as exc:
                    result = None
                    err = str(exc)
                except Exception:
                    result = None
                    err = None

                if not dlg.winfo_exists():
                    return
                if result:
                    lat, lon = result
                    dlg.after(0, lambda: _on_located(lat, lon))
                elif err:
                    dlg.after(0, lambda: _on_location_denied(err))
                else:
                    dlg.after(0, _on_location_unavailable)

            def _on_located(lat, lon):
                if not dlg.winfo_exists():
                    return
                loc_status_var.set("Location found — adjust the pin if needed")
                btn = _state.get("use_loc_btn")
                if btn:
                    btn.config(state="normal")
                _fly_to(lat, lon)
                # Only auto-place the marker when the user hasn't manually dropped one
                if not _state["manually_pinned"]:
                    if _state["marker"]:
                        _state["marker"].delete()
                    _state["marker"] = map_widget.set_marker(lat, lon, text="You are here")
                    _state["lat"] = lat
                    _state["lon"] = lon
                    _state["located"] = True
                    coord_var.set(f"{lat:.6f}, {lon:.6f}")

            def _on_location_denied(msg: str):
                if not dlg.winfo_exists():
                    return
                loc_status_var.set("Location denied — " + msg.split("\n")[0])
                btn = _state.get("use_loc_btn")
                if btn:
                    btn.config(state="normal")

            def _on_location_unavailable():
                if not dlg.winfo_exists():
                    return
                loc_status_var.set("Hardware location unavailable — click the map to pin manually")
                btn = _state.get("use_loc_btn")
                if btn:
                    btn.config(state="normal")

            threading.Thread(target=_locate, daemon=True).start()

        def _on_map_click(coords):
            lat, lon = coords
            _state["lat"], _state["lon"] = lat, lon
            _state["located"] = True
            _state["manually_pinned"] = True
            coord_var.set(f"{lat:.6f}, {lon:.6f}")
            loc_status_var.set("")
            if _state["marker"]:
                _state["marker"].delete()
            _state["marker"] = map_widget.set_marker(lat, lon, text="Pin")

        map_widget.add_left_click_map_command(_on_map_click)

        # If a pin was already set previously, restore it immediately;
        # otherwise kick off a hardware location request automatically.
        if self._search_lat and self._search_lon:
            # Position was already set before pack; just place the marker.
            _state["marker"] = map_widget.set_marker(
                self._search_lat, self._search_lon, text="Pin"
            )
            _state["lat"] = self._search_lat
            _state["lon"] = self._search_lon
            _state["located"] = True
            _state["manually_pinned"] = True
            coord_var.set(f"{self._search_lat:.6f}, {self._search_lon:.6f}")
        else:
            # Auto-request on open — will be called after use_loc_btn is created
            dlg.after(50, _request_device_location)

        # bottom button bar
        btn_bar = ttk.Frame(dlg)
        btn_bar.pack(fill="x", padx=8, pady=(0, 8))

        # "Use my location" lets the user re-request hardware location any time,
        # e.g. after granting permission in system settings mid-session.
        use_loc_btn = ttk.Button(btn_bar, text="Use my location",
                                 command=_request_device_location)
        use_loc_btn.pack(side="left", padx=4)
        _state["use_loc_btn"] = use_loc_btn  # hand the reference back to the closure

        def _confirm():
            if _state["lat"] is None:
                messagebox.showwarning("No pin", "Click the map first to drop a pin.",
                                       parent=dlg)
                return
            self._search_lat = _state["lat"]
            self._search_lon = _state["lon"]
            self._set_resolved_location(
                f"{self._search_lat:.5f}, {self._search_lon:.5f}",
                self._search_lat,
                self._search_lon,
            )
            # Persist the pin so it survives app restarts
            self._config["saved_pin"] = {"lat": self._search_lat, "lon": self._search_lon}
            save_config(self._config)
            dlg.destroy()

        ttk.Button(btn_bar, text="Confirm Pin", command=_confirm).pack(side="right", padx=4)
        ttk.Button(btn_bar, text="Cancel", command=dlg.destroy).pack(side="right")

    def _open_pin_dialog_text(self):
        """Fallback plain lat/lon dialog when tkintermapview is not installed."""
        import threading

        dlg = tk.Toplevel(self)
        dlg.title("Set Location Manually")
        dlg.grab_set()
        dlg.resizable(False, False)

        frm = ttk.Frame(dlg, padding=16)
        frm.pack()

        ttk.Label(frm, text="Install tkintermapview for an interactive map.", foreground="gray",
                  font=("Segoe UI", 8)).grid(row=0, column=0, columnspan=3, pady=(0, 8))

        lat_var = tk.StringVar(value=str(self._search_lat or ""))
        lon_var = tk.StringVar(value=str(self._search_lon or ""))
        status_var = tk.StringVar(value="")

        ttk.Label(frm, text="Latitude:").grid(row=1, column=0, sticky="e", pady=4, padx=4)
        ttk.Entry(frm, textvariable=lat_var, width=18).grid(row=1, column=1, pady=4)
        ttk.Label(frm, text="Longitude:").grid(row=2, column=0, sticky="e", pady=4, padx=4)
        ttk.Entry(frm, textvariable=lon_var, width=18).grid(row=2, column=1, pady=4)

        ttk.Label(frm, textvariable=status_var, foreground="gray",
                  font=("Segoe UI", 8, "italic")).grid(row=3, column=0, columnspan=3, pady=(2, 0))

        def _use_my_location():
            status_var.set("Requesting location from system…")
            loc_btn.config(state="disabled")

            def _locate():
                try:
                    result = self._get_device_location()
                    err = None
                except PermissionError as exc:
                    result = None
                    err = str(exc)
                except Exception:
                    result = None
                    err = None

                if not dlg.winfo_exists():
                    return
                if result:
                    lat, lon = result
                    def _apply():
                        lat_var.set(f"{lat:.6f}")
                        lon_var.set(f"{lon:.6f}")
                        status_var.set("Location found")
                        loc_btn.config(state="normal")
                    dlg.after(0, _apply)
                elif err:
                    dlg.after(0, lambda: status_var.set("Denied — " + err.split("\n")[0]))
                    dlg.after(0, lambda: loc_btn.config(state="normal"))
                else:
                    dlg.after(0, lambda: status_var.set("Hardware location unavailable"))
                    dlg.after(0, lambda: loc_btn.config(state="normal"))

            threading.Thread(target=_locate, daemon=True).start()

        loc_btn = ttk.Button(frm, text="Use my location", command=_use_my_location)
        loc_btn.grid(row=1, column=2, rowspan=2, padx=(8, 0), sticky="ns")

        def _confirm():
            try:
                self._search_lat = float(lat_var.get())
                self._search_lon = float(lon_var.get())
                self._set_resolved_location(
                    f"{self._search_lat:.5f}, {self._search_lon:.5f}",
                    self._search_lat,
                    self._search_lon,
                )
                # Persist the pin so it survives app restarts
                self._config["saved_pin"] = {"lat": self._search_lat, "lon": self._search_lon}
                save_config(self._config)
                dlg.destroy()
            except ValueError:
                messagebox.showerror("Invalid", "Please enter valid decimal coordinates.",
                                     parent=dlg)

        ttk.Button(frm, text="OK", command=_confirm).grid(row=4, column=0, columnspan=3, pady=8)

    # ------------------------------------------------------------------
    # Location helpers (redesigned)
    # ------------------------------------------------------------------

    def _get_saved_locations(self) -> list[dict]:
        """Return the saved locations list from config.
        Migrates the old single saved_location dict if needed."""
        locs = self._config.get("saved_locations", [])
        if isinstance(locs, list) and locs:
            return locs
        # One-time migration from old single-location format
        old = self._config.get("saved_location", {})
        if old.get("lat") and old.get("lon"):
            label = (old.get("address") or "Saved Location").strip() or "Saved Location"
            migrated = [{"label": label, "lat": old["lat"], "lon": old["lon"]}]
            self._config["saved_locations"] = migrated
            return migrated
        return []

    def _refresh_saved_locations_dropdown(self):
        """Rebuild the combobox values list from config."""
        locs = self._get_saved_locations()
        self._loc_combo["values"] = [loc["label"] for loc in locs]

    def _update_coord_label(self):
        """Show or clear the small resolved-coords label."""
        if self._search_lat and self._search_lon:
            self._coord_label.config(
                text=f"{self._search_lat:.5f}, {self._search_lon:.5f}"
            )
        else:
            self._coord_label.config(text="")

    def _set_resolved_location(self, label: str, lat: float, lon: float):
        """Set both the display field and the resolved coordinates atomically."""
        self._setting_location_programmatically = True
        self._addr_var.set(label)
        self._search_lat = lat
        self._search_lon = lon
        self._setting_location_programmatically = False
        self._update_coord_label()

    def _restore_last_location(self):
        """Restore the last used location from config on startup."""
        # Prefer last pin, then first saved location
        pin = self._config.get("saved_pin", {})
        if pin.get("lat") and pin.get("lon"):
            lat, lon = pin["lat"], pin["lon"]
            self._set_resolved_location(f"{lat:.5f}, {lon:.5f}", lat, lon)
            return
        locs = self._get_saved_locations()
        if locs:
            loc = locs[0]
            self._set_resolved_location(loc["label"], loc["lat"], loc["lon"])

    def _on_loc_field_edited(self, event=None):
        """Clear resolved coords when the user types a new address manually."""
        if self._setting_location_programmatically:
            return
        # Only react to printable keystrokes, not navigation keys
        if event and (len(getattr(event, "char", "")) > 0):
            self._search_lat = None
            self._search_lon = None
            self._update_coord_label()

    def _on_saved_location_selected(self, event=None):
        """Apply a saved location when selected from the combobox dropdown."""
        label = self._addr_var.get()
        for loc in self._get_saved_locations():
            if loc["label"] == label:
                self._set_resolved_location(label, loc["lat"], loc["lon"])
                break

    def _request_topbar_location(self):
        """Hardware location request triggered from the top-bar button."""
        import threading
        self._hw_loc_btn.config(state="disabled", text="Locating…")

        def _locate():
            try:
                result = self._get_device_location()
                err_msg = None
            except PermissionError as exc:
                result = None
                err_msg = str(exc)
            except Exception:
                result = None
                err_msg = None

            if result:
                lat, lon = result
                label = f"My Location ({lat:.4f}, {lon:.4f})"
                self.after(0, lambda: self._set_resolved_location(label, lat, lon))
                self.after(0, lambda: self._hw_loc_btn.config(
                    state="normal", text="◉ My Location"))
            elif err_msg:
                self.after(0, lambda: messagebox.showwarning(
                    "Location Denied", err_msg, parent=self))
                self.after(0, lambda: self._hw_loc_btn.config(
                    state="normal", text="◉ My Location"))
            else:
                self.after(0, lambda: self._set_status(
                    "Hardware location unavailable — enter an address or use the Map"))
                self.after(0, lambda: self._hw_loc_btn.config(
                    state="normal", text="◉ My Location"))

        threading.Thread(target=_locate, daemon=True).start()

    def _save_current_location(self):
        """Save the current resolved location with a user-provided name."""
        if not (self._search_lat and self._search_lon):
            messagebox.showinfo(
                "No Location",
                "Set a location first — search an address, use Map, or use My Location.",
                parent=self,
            )
            return

        from tkinter import simpledialog
        default_name = self._addr_var.get()[:50] if self._addr_var.get() else ""
        name = simpledialog.askstring(
            "Save Location",
            "Enter a name for this location:",
            initialvalue=default_name,
            parent=self,
        )
        if not name or not name.strip():
            return
        name = name.strip()

        locs = self._get_saved_locations()
        for loc in locs:
            if loc["label"] == name:
                loc["lat"] = self._search_lat
                loc["lon"] = self._search_lon
                break
        else:
            locs.append({"label": name, "lat": self._search_lat, "lon": self._search_lon})

        self._config["saved_locations"] = locs
        save_config(self._config)
        self._refresh_saved_locations_dropdown()
        self._set_resolved_location(name, self._search_lat, self._search_lon)
        self._set_status(f"Saved '{name}'")

    # ------------------------------------------------------------------
    # Radius
    # ------------------------------------------------------------------

    def _on_radius_change(self, val):
        v = float(val)
        self._search_radius = v
        self._radius_label.config(text=f"{v:.1f} mi")

    def _on_max_results_change(self, val):
        v = int(float(val))
        # Snap to 50-step increments for a stable and readable limit.
        snapped = int(round(v / 50) * 50)
        snapped = max(50, min(MAX_RESULTS, snapped))
        self._max_results_limit = snapped
        self._max_results_var.set(snapped)
        self._max_results_label.config(text=str(snapped))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _trigger_search(self):
        if self._search_lat and self._search_lon:
            # Coordinates already resolved (pin, hardware, saved, or previous geocode)
            self._run_search(self._search_lat, self._search_lon)
        else:
            addr = self._addr_var.get().strip()
            if not addr:
                messagebox.showwarning(
                    "No Location",
                    "Enter an address, or use 'My Location' / 'Map' to set a location.",
                    parent=self,
                )
                return
            self._geocode_then_search(addr)

    def _geocode_then_search(self, address: str):
        self._set_status("Geocoding address…")
        self._search_cancellation_token = CancellationToken()
        self._start_progress()
        self._search_btn.config(state="disabled")

        import threading
        import queue

        q = queue.Queue()

        def _run():
            try:
                from geopy.geocoders import Nominatim
                geo = Nominatim(user_agent="RedlineSponsorFinder/1.0")
                location = geo.geocode(address, timeout=10)
                if location:
                    q.put(("success", location.latitude, location.longitude))
                else:
                    q.put(("error", "Address not found. Try a more specific address.", None))
            except Exception as e:
                q.put(("error", f"Geocoding error: {e}", None))

        def _process():
            try:
                msg = q.get_nowait()
                # If cancelled during geocoding, discard the result silently
                if (self._search_cancellation_token
                        and self._search_cancellation_token.is_cancelled()):
                    return
                msg_type = msg[0]
                if msg_type == "success":
                    _, lat, lon = msg
                    self._run_search(lat, lon)
                elif msg_type == "error":
                    _, error_msg, _ = msg
                    self._on_search_error(error_msg)
            except queue.Empty:
                self.after(100, _process)
            except tk.TclError:
                pass

        threading.Thread(target=_run, daemon=True).start()
        _process()

    def _run_search(self, lat: float, lon: float):
        self._search_lat = lat
        self._search_lon = lon
        self._update_coord_label()
        self._set_status("Searching…")
        self._search_cancellation_token = CancellationToken()
        self._start_progress()
        self._search_btn.config(state="disabled")

        fetch_businesses(
            lat=lat,
            lon=lon,
            radius_miles=self._search_radius,
            max_results=self._max_results_limit,
            on_success=lambda results: self.after(0, lambda: self._on_search_success(results)),
            on_error=lambda msg: self.after(0, lambda: self._on_search_error(msg)),
            on_progress=lambda msg: self.after(0, lambda: self._set_status(msg)),
            cancellation_token=self._search_cancellation_token,
        )

    def _on_search_success(self, raw_results: list[dict]):
        self._stop_progress()
        self._search_btn.config(state="normal")

        if not raw_results:
            self._set_status("No businesses found.")
            return

        self._start_parse_progress(raw_results)

    def _start_parse_progress(self, raw_results: list[dict]):
        import threading

        total = len(raw_results)

        # Busy cursor on the whole application
        self.config(cursor="watch")

        # ── progress popup ──────────────────────────────────────────────
        dlg = tk.Toplevel(self)
        dlg.title("Processing Results")
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)   # block accidental close
        dlg.transient(self)

        # Centre over the main window
        self.update_idletasks()
        mx, my = self.winfo_rootx(), self.winfo_rooty()
        mw, mh = self.winfo_width(), self.winfo_height()
        dlg.geometry(f"420x160+{mx + mw // 2 - 210}+{my + mh // 2 - 80}")

        frm = ttk.Frame(dlg, padding=20)
        frm.pack()

        ttk.Label(frm, text="Enriching & scoring businesses…",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")

        name_var = tk.StringVar(value="Starting…")
        ttk.Label(frm, textvariable=name_var, foreground="gray",
                  font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 8))

        progress_var = tk.IntVar(value=0)
        bar = ttk.Progressbar(frm, variable=progress_var, maximum=total,
                              mode="determinate", length=360)
        bar.pack(fill="x")

        count_var = tk.StringVar(value=f"0 / {total}")
        ttk.Label(frm, textvariable=count_var,
                  font=("Consolas", 8)).pack(pady=(4, 0), anchor="e")

        dlg.grab_set()

        # ── background worker ────────────────────────────────────────────
        freq_chains = build_frequency_chain_set(raw_results)
        enriched: list[dict] = []
        active_profile = self._get_active_profile()
        active_rules = active_profile.get("scoring_rules", []) if active_profile else []

        def _update(i: int, name: str):
            progress_var.set(i + 1)
            count_var.set(f"{i + 1} / {total}")
            name_var.set(name[:55] if name else "…")

        def _worker():
            for i, b in enumerate(raw_results):
                enrich(b, frequency_chain_set=freq_chains)
                compute_score(
                    b,
                    search_radius_miles=self._search_radius,
                    rules=active_rules,
                    profile=active_profile,
                )
                enriched.append(b)
                self.after(0, _update, i, b.get("name", ""))

            self.after(0, _done)

        def _done():
            dlg.destroy()
            self.config(cursor="")
            self._all_businesses = enriched
            ai_scoring.clear_session_cache()
            self._sidebar.update_categories(get_categories(enriched))
            self._apply_filters()
            self._set_status(f"Found {len(enriched)} businesses.")
            # Kick off AI batch scoring if enabled
            if self._sidebar.ai_scoring_var.get():
                self._run_ai_batch_scoring(enriched)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_search_error(self, message: str):
        self._stop_progress()
        self._search_btn.config(state="normal")
        self._set_status(f"Error: {message}")
        messagebox.showerror("Search Error", message)

    # ------------------------------------------------------------------
    # Filtering & display
    # ------------------------------------------------------------------

    def _apply_filters(self):
        state = self._sidebar.get_state()

        filtered = apply_standard_filters(
            self._all_businesses,
            name_query=state["name_query"],
            category=state["category"],
            hide_chains=state["hide_chains"],
            min_score=state["min_score"],
            open_now=state.get("open_now", False),
            has_wheelchair=state.get("has_wheelchair", False),
            has_outdoor_seating=state.get("has_outdoor_seating", False),
            has_delivery=state.get("has_delivery", False),
            has_takeout=state.get("has_takeout", False),
        )
        filtered = apply_custom_filter(
            filtered,
            rules=state["custom_rules"],
            combine=state["custom_combine"],
        )
        # AI attribute filter: only keep businesses in the AI-evaluated match set
        if state.get("ai_attr_active") and state.get("ai_attr_matches") is not None:
            match_set = state["ai_attr_matches"]
            filtered = [b for b in filtered if b.get("osm_id", "") in match_set]

        filtered = sort_businesses(
            filtered,
            sort_by=state["sort_by"],
            descending=state.get("sort_descending"),
        )

        self._populate_tree(filtered)
        total = len(self._all_businesses)
        shown = len(filtered)
        self._count_var.set(f"Showing {shown} of {total} businesses")

    def _populate_tree(self, businesses: list[dict]):
        self._tree.delete(*self._tree.get_children())
        self._iid_map.clear()
        self._detail.clear()

        ai_on = self._sidebar.ai_scoring_var.get()

        for i, b in enumerate(businesses):
            rule_score = b.get("score", 0)
            score      = b.get("ai_score", rule_score) if ai_on else rule_score
            tags    = b.get("tags", {})
            phone   = b.get("phone") or tags.get("phone", "")
            website = b.get("website") or tags.get("website", "")
            osm_id  = b.get("osm_id", "")

            has_note = bool(self._notes.get(osm_id, ""))
            star = ("★✎" if has_note else "★") if osm_id in self._shortlist else ("✎" if has_note else "")

            values = (
                star,
                score,
                b.get("name", ""),
                b.get("category", ""),    # OSM primary key label: Shop, Amenity…
                b.get("industry", ""),    # human-readable: Auto Parts, Bar…
                "Yes" if b.get("is_chain") else "No",
                f"{b.get('distance_miles', 0):.2f}",
                phone,
                website,
            )

            # Row color: green tint ≥70, red tint <40, alternating for middle range
            if score >= 70:
                row_tags = ["green"]
            elif score < 40:
                row_tags = ["red"]
            else:
                row_tags = ["odd" if i % 2 else "even"]
            if osm_id in self._shortlist:
                row_tags.append("shortlisted")
            tags_list = tuple(row_tags)

            iid = self._tree.insert("", "end", values=values, tags=tags_list)
            self._iid_map[iid] = b

    # ------------------------------------------------------------------
    # Treeview interactions
    # ------------------------------------------------------------------

    def _toggle_shortlist(self, osm_id: str):
        """Add or remove osm_id from shortlist, then refresh."""
        if osm_id in self._shortlist:
            self._shortlist.discard(osm_id)
        else:
            self._shortlist.add(osm_id)
        self._apply_filters()

    def _on_row_select(self, _event):
        sel = self._tree.selection()
        if sel:
            b = self._iid_map.get(sel[0])
            if b:
                self._detail.show(b)
                self._fetch_ai_explanation(b)
                self._history = append_history_entry(self._history, b)
                save_history(self._history)

    def _on_row_double_click(self, event):
        """Double-click toggles shortlist."""
        try:
            if self._tree.identify_region(event.x, event.y) != "cell":
                return

            # Use the row under the cursor (not the current selection),
            # since selection can be stale during rapid UI updates.
            iid = self._tree.identify_row(event.y)
            if not iid:
                return

            self._tree.selection_set(iid)
            b = self._iid_map.get(iid)
            if not b:
                return

            osm_id = b.get("osm_id")
            if not osm_id:
                return

            self._toggle_shortlist(str(osm_id))
        except tk.TclError:
            # Ignore transient widget state errors during redraw.
            return

    def _on_row_space(self, _event):
        """Space bar toggles shortlist for selected row."""
        sel = self._tree.selection()
        if sel:
            b = self._iid_map.get(sel[0])
            if b:
                self._toggle_shortlist(b.get("osm_id", ""))

    def _on_row_right_click(self, event):
        """Right-click context menu: shortlist toggle + add note. Bulk actions if multiple selected."""
        iid = self._tree.identify_row(event.y)
        if not iid:
            return

        # If the clicked row is not in the current selection, replace selection with it.
        current_sel = self._tree.selection()
        if iid not in current_sel:
            self._tree.selection_set(iid)
            current_sel = (iid,)

        selected_iids = self._tree.selection()
        menu = tk.Menu(self, tearoff=0)

        if len(selected_iids) > 1:
            # Bulk menu
            menu.add_command(
                label=f"Add all {len(selected_iids)} selected to Shortlist",
                command=lambda iids=selected_iids: self._bulk_shortlist_add(iids),
            )
            menu.add_command(
                label=f"Remove all {len(selected_iids)} selected from Shortlist",
                command=lambda iids=selected_iids: self._bulk_shortlist_remove(iids),
            )
            menu.add_separator()
            menu.add_command(
                label="Copy all selected names",
                command=lambda iids=selected_iids: self._bulk_copy_names(iids),
            )
            menu.add_command(
                label="Export selected to CSV",
                command=lambda iids=selected_iids: self._export_selected_csv(iids),
            )
            if 2 <= len(selected_iids) <= 6:
                menu.add_separator()
                menu.add_command(
                    label=f"Compare {len(selected_iids)} selected side-by-side",
                    command=lambda iids=selected_iids: self._open_compare(iids),
                )
        else:
            b = self._iid_map.get(iid)
            if not b:
                return
            osm_id = b.get("osm_id", "")
            self._detail.show(b)

            if osm_id in self._shortlist:
                menu.add_command(label="★ Remove from Shortlist",
                                 command=lambda: self._toggle_shortlist(osm_id))
            else:
                menu.add_command(label="☆ Add to Shortlist",
                                 command=lambda: self._toggle_shortlist(osm_id))
            menu.add_separator()
            menu.add_command(label="✎ Add / Edit Note",
                             command=self._detail._edit_note)

        menu.tk_popup(event.x_root, event.y_root)

    def _bulk_shortlist_add(self, iids):
        """Add all selected rows to the shortlist."""
        for iid in iids:
            b = self._iid_map.get(iid)
            if b:
                osm_id = b.get("osm_id", "")
                if osm_id:
                    self._shortlist.add(osm_id)
        self._apply_filters()

    def _bulk_shortlist_remove(self, iids):
        """Remove all selected rows from the shortlist."""
        for iid in iids:
            b = self._iid_map.get(iid)
            if b:
                osm_id = b.get("osm_id", "")
                if osm_id:
                    self._shortlist.discard(osm_id)
        self._apply_filters()

    def _bulk_copy_names(self, iids):
        """Copy all selected business names to clipboard, newline-separated."""
        names = []
        for iid in iids:
            b = self._iid_map.get(iid)
            if b:
                names.append(b.get("name", ""))
        self.clipboard_clear()
        self.clipboard_append("\n".join(names))
        self._set_status(f"Copied {len(names)} business names to clipboard.")

    def _open_compare(self, iids):
        """Open side-by-side comparison for 2–6 selected businesses."""
        businesses = [self._iid_map[iid] for iid in iids if iid in self._iid_map]
        if len(businesses) < 2:
            return
        CompareDialog(self, businesses, self._notes)

    def _export_selected_csv(self, iids):
        """Export the selected businesses to CSV."""
        businesses = [self._iid_map[iid] for iid in iids if iid in self._iid_map]
        if not businesses:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_export_filename(),
            title="Export Selected to CSV",
        )
        if not path:
            return
        try:
            count = export_shortlist_csv(businesses, self._notes, path)
            self._set_status(f"Exported {count} businesses to {os.path.basename(path)}.")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def _sort_by_column(self, col: str):
        """Sort treeview by column header click."""
        ai_on = self._sidebar.ai_scoring_var.get()
        col_to_sort = {
            "score": "AI Score" if ai_on else "Score",
            "name": "Name",
            "category": "Category",
            "industry": "Category",
            "distance": "Distance",
        }
        sort_key = col_to_sort.get(col)
        if sort_key:
            self._sidebar.sort_var.set(sort_key)

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------

    def _get_active_profile(self) -> dict | None:
        selected = (self._sidebar.profile_var.get() or "").strip()
        if not selected or selected.lower() == "no profile":
            return None
        return get_profile(self._profiles, selected)

    def _rescore_all_businesses(self):
        if not self._all_businesses:
            return

        profile = self._get_active_profile()
        rules = profile.get("scoring_rules", []) if profile else []
        for business in self._all_businesses:
            compute_score(
                business,
                search_radius_miles=self._search_radius,
                rules=rules,
                profile=profile,
            )

        self._apply_filters()

    def _on_profile_load(self, name: str):
        """Load a saved profile: restores location, radius, and filter state."""
        try:
            if not name or name.lower() == "no profile":
                self._sidebar.profile_var.set("No profile")
                self._rescore_all_businesses()
                self._set_status("Neutral mode active (no profile scoring rules).")
                return

            profile = get_profile(self._profiles, name)
            if not profile:
                messagebox.showwarning("Profile Not Found",
                                       f"Profile '{name}' was not found.")
                return

            loc = profile.get("location", {})
            lat = loc.get("lat")
            lon = loc.get("lon")
            # Use explicit None check — lat=0.0 or lon=0.0 are valid coordinates
            if lat is not None and lon is not None:
                address = loc.get("address", "")
                self._set_resolved_location(address, float(lat), float(lon))

            radius = float(profile.get("radius_miles", self._search_radius))
            self._search_radius = radius
            self._radius_var.set(radius)
            self._radius_label.config(text=f"{radius:.1f} mi")

            max_limit = int(profile.get("max_results", self._max_results_limit))
            self._max_results_limit = max(50, min(MAX_RESULTS, max_limit))
            self._max_results_var.set(self._max_results_limit)
            self._max_results_label.config(text=str(self._max_results_limit))

            # Restore filter state — temporarily block on_change to avoid
            # thrashing _apply_filters once per variable write
            filters = profile.get("filters", {})
            old_on_change = self._sidebar.on_change
            self._sidebar.on_change = lambda: None
            try:
                self._sidebar.set_state(filters)
            finally:
                self._sidebar.on_change = old_on_change

            self._rescore_all_businesses()
            self._set_status(f"Profile '{name}' loaded. Click Search to find businesses.")

        except Exception as exc:
            messagebox.showerror("Profile Load Error",
                                 f"Could not load profile '{name}':\n{exc}")

    def _on_profile_save(self):
        """Capture current state and save it as a named profile."""
        name = simpledialog.askstring(
            "Save Profile",
            "Enter a name for this profile:",
            parent=self,
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return

        filter_state = self._sidebar.get_state()
        existing = get_profile(self._profiles, name) or {}
        profile = {
            **existing,
            "name": name,
            "location": {
                "address": self._addr_var.get(),
                "lat": self._search_lat,
                "lon": self._search_lon,
            },
            "radius_miles": self._search_radius,
            "max_results": self._max_results_limit,
            "filters": filter_state,
        }

        self._profiles = upsert_profile(self._profiles, profile)
        save_profiles(self._profiles)
        self._sidebar.update_profiles([p["name"] for p in self._profiles])
        self._sidebar.profile_var.set(name)
        self._set_status(f"Profile '{name}' saved.")

    def _on_profile_delete(self, name: str):
        """Delete the selected profile after confirmation."""
        if not messagebox.askyesno("Delete Profile",
                                   f"Delete profile '{name}'? This cannot be undone.",
                                   parent=self):
            return
        self._profiles = delete_profile(self._profiles, name)
        save_profiles(self._profiles)
        self._sidebar.update_profiles([p["name"] for p in self._profiles])
        if self._sidebar.profile_var.get() == name:
            self._sidebar.profile_var.set("No profile")
            self._rescore_all_businesses()
        self._set_status(f"Profile '{name}' deleted.")

    def _on_profile_new(self):
        """Create a new scoring profile."""
        dlg = ProfileEditorDialog(self, profile=None)
        result = dlg.result()
        if result:
            self._profiles = upsert_profile(self._profiles, result)
            save_profiles(self._profiles)
            self._sidebar.update_profiles([p["name"] for p in self._profiles])
            self._sidebar.profile_var.set(result["name"])
            self._on_profile_load(result["name"])
            self._set_status(f"Profile '{result['name']}' created.")

    def _on_profile_edit(self, name: str):
        """Edit an existing scoring profile."""
        profile = get_profile(self._profiles, name)
        if not profile:
            messagebox.showerror("Profile Not Found", f"Profile '{name}' not found.")
            return

        dlg = ProfileEditorDialog(self, profile=profile)
        result = dlg.result()
        if result:
            self._profiles = upsert_profile(self._profiles, result)
            save_profiles(self._profiles)
            self._sidebar.update_profiles([p["name"] for p in self._profiles])
            self._sidebar.profile_var.set(result["name"])
            self._on_profile_load(result["name"])
            self._set_status(f"Profile '{result['name']}' updated.")

    # ------------------------------------------------------------------
    # Saved Searches
    # ------------------------------------------------------------------

    def _save_search(self, name: str, state: dict):
        self._saved_searches = [s for s in self._saved_searches if s["name"] != name]
        self._saved_searches.insert(0, {"name": name, "state": state})
        save_saved_searches(self._saved_searches)
        self._sidebar.refresh_saved_searches(self._saved_searches)
        self._set_status(f"Saved search '{name}'.")

    def _delete_search(self, name: str):
        self._saved_searches = [s for s in self._saved_searches if s["name"] != name]
        save_saved_searches(self._saved_searches)
        self._sidebar.refresh_saved_searches(self._saved_searches)

    def _load_search(self, name: str):
        for s in self._saved_searches:
            if s["name"] == name:
                self._sidebar.set_state(s["state"])
                self._apply_filters()
                break

    # ------------------------------------------------------------------
    # AI attribute filter
    # ------------------------------------------------------------------

    def _run_ai_attr_filter(self, query: str):
        """Evaluate the AI attribute query against the currently visible businesses."""
        if not self._ai_running:
            messagebox.showinfo(
                "AI Not Ready",
                "Load an AI model first (AI Settings).",
                parent=self,
            )
            return

        # Build the candidate list from the current standard filters (no attr filter)
        state = self._sidebar.get_state()
        candidates = apply_standard_filters(
            self._all_businesses,
            name_query=state["name_query"],
            category=state["category"],
            hide_chains=state["hide_chains"],
            min_score=state["min_score"],
            open_now=state.get("open_now", False),
            has_wheelchair=state.get("has_wheelchair", False),
            has_outdoor_seating=state.get("has_outdoor_seating", False),
            has_delivery=state.get("has_delivery", False),
            has_takeout=state.get("has_takeout", False),
        )
        candidates = apply_custom_filter(
            candidates,
            rules=state["custom_rules"],
            combine=state["custom_combine"],
        )

        MAX_AI_ATTR = 150
        to_check = candidates[:MAX_AI_ATTR]
        total = len(to_check)
        if not to_check:
            messagebox.showinfo("No Results", "No businesses to evaluate.", parent=self)
            return

        self._sidebar.set_ai_attr_status(f"Evaluating 0/{total}…")

        q = queue.Queue()

        def _run():
            matches: set[str] = set()
            for i, b in enumerate(to_check):
                result = ai_scoring.check_attribute(b, query)
                if result:
                    matches.add(b.get("osm_id", ""))
                q.put(("progress", i + 1, total, matches))
            q.put(("done", matches))

        def _process():
            try:
                while True:
                    try:
                        msg = q.get_nowait()
                    except queue.Empty:
                        break
                    if msg[0] == "progress":
                        _, done, tot, _ = msg
                        self._sidebar.set_ai_attr_status(f"Evaluating {done}/{tot}…")
                    elif msg[0] == "done":
                        _, match_set = msg
                        label = f"{len(match_set)} of {total} match"
                        self._sidebar.set_ai_attr_status(label)
                        self._sidebar.set_ai_attr_matches(match_set)
                        return
            except tk.TclError:
                return
            self.after(200, _process)

        threading.Thread(target=_run, daemon=True).start()
        _process()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _show_history(self):
        dlg = tk.Toplevel(self)
        dlg.title("View History")
        dlg.geometry("500x400")
        dlg.grab_set()
        ttk.Label(dlg, text="Recently viewed businesses:", font=("", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 4))
        frame = ttk.Frame(dlg)
        frame.pack(fill="both", expand=True, padx=8, pady=4)
        cols = ("name", "industry", "score", "viewed_at")
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        tree.heading("name",      text="Name")
        tree.heading("industry",  text="Industry")
        tree.heading("score",     text="Score")
        tree.heading("viewed_at", text="Viewed")
        tree.column("name",      width=180)
        tree.column("industry",  width=120)
        tree.column("score",     width=50)
        tree.column("viewed_at", width=130)
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for entry in self._history:
            tree.insert("", "end", values=(
                entry.get("name", ""),
                entry.get("industry", ""),
                entry.get("score", ""),
                entry.get("viewed_at", ""),
            ))
        btn_row = ttk.Frame(dlg)
        btn_row.pack(fill="x", padx=8, pady=8)

        def _clear():
            if messagebox.askyesno("Clear History", "Clear all view history?", parent=dlg):
                self._history = []
                save_history(self._history)
                tree.delete(*tree.get_children())

        ttk.Button(btn_row, text="Clear History", command=_clear).pack(side="left")
        ttk.Button(btn_row, text="Close", command=dlg.destroy).pack(side="right")

    # ------------------------------------------------------------------
    # JSON Export
    # ------------------------------------------------------------------

    def _export_json(self):
        shortlisted = [b for b in self._all_businesses if b.get("osm_id", "") in self._shortlist]
        if not shortlisted:
            messagebox.showinfo("No Shortlist", "Add businesses to your shortlist first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile=default_export_filename().replace(".csv", ".json"),
            title="Export Shortlist as JSON",
        )
        if not path:
            return
        try:
            count = export_json(shortlisted, self._notes, path)
            self._set_status(f"Exported {count} businesses to {os.path.basename(path)}.")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    # ------------------------------------------------------------------
    # AI Scoring
    # ------------------------------------------------------------------

    def _check_ai_status(self):
        """
        Check if a model is loaded and ready for AI features.
        Load default model on startup if one exists locally.
        """
        import threading

        def _run():
            # List available models
            models = ai_scoring.list_models()
            if not models:
                # No models cached locally — show info prompt
                self.after(500, self._prompt_download_model)
                return

            # Prefer configured model; then default; then first available cached file.
            preferred_models = [self._ai_model, ai_scoring.DEFAULT_MODEL] + models
            success = False
            loaded_name = None
            seen = set()
            for candidate in preferred_models:
                if not candidate or candidate in seen:
                    continue
                seen.add(candidate)
                if ai_scoring.load_default_model(candidate):
                    success = True
                    loaded_name = candidate
                    break

            if success and loaded_name:
                self._ai_model = loaded_name
            self.after(0, _on_model_loaded, success)

        def _on_model_loaded(success):
            self._ai_running = success
            self._sidebar.set_ai_status(success)
            if not success and ai_scoring.list_models():
                # Model file exists but failed to load
                self.after(500, self._prompt_download_model)

        self._ai_running = False
        self._sidebar.set_ai_status(False)
        threading.Thread(target=_run, daemon=True).start()

    # Backward compatibility alias
    def _check_ollama_status(self):
        self._check_ai_status()

    def _prompt_download_model(self):
        """
        Show a prompt when no models are available.
        Offers to open AI Settings to download one.
        """
        if self._ai_prompt_active:
            return

        self._ai_prompt_active = True
        models = ai_scoring.list_models()
        if models:
            # Model exists but failed to load — might be corrupted
            msg = "Model file exists but failed to load. Try deleting it and downloading again.\n\nOpen AI Settings?"
        else:
            msg = (
                "No AI model downloaded on this computer.\n\n"
                "AI features (score explanations, batch scoring) require a model.\n\n"
                "Would you like to open AI Settings to download one now?\n"
                "(Recommended: llama3 — ~4 GB, one-time download per machine)"
            )

        try:
            answer = messagebox.askyesno(
                "AI Model Required",
                msg,
                parent=self,
            )
            if answer:
                self._open_ai_settings()
        finally:
            self._ai_prompt_active = False

    def _open_settings(self, start_tab: int = 0):
        """Open the unified Settings dialog (File > Settings)."""
        try:
            from ui.settings_dialog import SettingsDialog
        except ImportError:
            from settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, app=self, start_tab=start_tab)
        self.wait_window(dlg)

    def _open_ai_settings(self):
        """Open Settings dialog pre-selected on the AI tab."""
        self._open_settings(start_tab=1)

    def _save_ai_settings_to_config(self):
        self._config["ai_settings"] = {
            "model": self._ai_model,
            "weight": self._ai_weight,
            "explain_on": self._ai_explain_on,
            "scoring_on": self._ai_scoring_on,
            "max_score": self._ai_max_score,
            "disable_max_limit": self._ai_disable_max_limit,
            "debug_mode": self._ai_debug,
        }

    def _fetch_ai_explanation(self, business: dict):
        """
        Fetch an AI explanation for the selected business in the background.
        Shows "Generating insight…" immediately, then updates when the model responds.
        """
        if not self._ai_running or not self._ai_explain_on:
            return

        osm_id = business.get("osm_id", "")
        # Check session cache first — no network call needed
        cached = ai_scoring.get_cached_explanation(osm_id)
        if cached:
            self._detail.update_ai_insight(cached)
            return

        self._detail.update_ai_insight("Generating insight…")
        active_profile = self._get_active_profile()
        profile_desc = (
            active_profile.get("description", "general local business outreach")
            if active_profile else
            "general local business outreach"
        )

        import threading
        import queue

        q = queue.Queue()

        def _run():
            result = ai_scoring.get_explanation(
                business,
                profile_desc,
                profile=active_profile,
            )
            q.put(result)

        def _process():
            try:
                result = q.get_nowait()
                # Only update if the same row is still selected
                if self._detail._current_id == osm_id:
                    self._detail.update_ai_insight(result)
            except queue.Empty:
                self.after(100, _process)
            except tk.TclError:
                pass

        threading.Thread(target=_run, daemon=True).start()
        _process()

    def _run_ai_batch_scoring(self, businesses: list[dict]):
        """
        Batch-score businesses with AI in the background.
        Runs sequentially in batches of BATCH_SIZE.
        """
        import threading
        import queue
        import ai_scoring as _ai

        if not self._ai_running or not self._sidebar.ai_scoring_var.get():
            return

        if self._ai_disable_max_limit:
            candidates = businesses
        else:
            candidates = businesses[:self._ai_max_score]
        total_batches = (len(candidates) + _ai.BATCH_SIZE - 1) // _ai.BATCH_SIZE
        active_profile = self._get_active_profile()
        profile_desc = (
            active_profile.get("description", "general local business outreach")
            if active_profile else
            "general local business outreach"
        )

        q = queue.Queue()

        def _run():
            for i in range(0, len(candidates), _ai.BATCH_SIZE):
                batch = candidates[i:i + _ai.BATCH_SIZE]
                batch_num = i // _ai.BATCH_SIZE + 1
                q.put(("status", f"AI scoring batch {batch_num}/{total_batches}…"))
                _ai.score_batch(batch, profile_desc, profile=active_profile)

            # After all batches, apply combined scores and refresh
            q.put(("done", f"AI scoring complete for {len(candidates)} businesses."))

        def _process():
            try:
                while True:
                    try:
                        msg = q.get_nowait()
                    except queue.Empty:
                        break

                    if msg[0] == "status":
                        _, status_msg = msg
                        self._set_status(status_msg)
                    elif msg[0] == "done":
                        _, final_msg = msg
                        self._apply_ai_scores()
                        self._set_status(final_msg)
                        return
            except tk.TclError:
                pass

            # Keep polling
            self.after(100, _process)

        threading.Thread(target=_run, daemon=True).start()
        _process()

    def _update_score_column_heading(self):
        """Update the Score column heading to reflect AI scoring mode."""
        ai_on = self._sidebar.ai_scoring_var.get()
        heading = "Score (AI)" if ai_on else "Score"
        self._tree.heading("score", text=heading)
        self._apply_filters()

    def _apply_ai_scores(self):
        """
        Merge AI scores into business dicts and re-populate the tree.
        Combined score = weighted average of rule score and AI score.
        """
        for b in self._all_businesses:
            osm_id = b.get("osm_id", "")
            entry  = ai_scoring.get_cached_ai_score(osm_id)
            if entry:
                b["ai_score"] = entry["ai_score"]
                b["ai_reason"] = entry.get("reason", "")
                b["combined_score"] = ai_scoring.compute_combined_score(
                    b.get("score", 0), entry["ai_score"], self._ai_weight
                )
        self._update_score_column_heading()

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def _on_note_saved(self):
        save_notes(self._notes)
        self._apply_filters()   # refresh to show note indicator

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_csv(self):
        shortlisted = [b for b in self._all_businesses
                       if b.get("osm_id", "") in self._shortlist]
        if not shortlisted:
            messagebox.showinfo("No Shortlist",
                                "Double-click rows to add businesses to your shortlist first.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=default_export_filename(),
            title="Export Shortlist",
        )
        if not path:
            return

        try:
            count = export_shortlist_csv(shortlisted, self._notes, path)
            self._set_status(f"Exported {count} businesses to {os.path.basename(path)}.")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    # ------------------------------------------------------------------
    # Status / progress helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str):
        self._status_var.set(msg)
        self.update_idletasks()

    def _start_progress(self):
        self._progress.start(10)
        self._cancel_btn.pack(side="right", padx=(0, 6))

    def _stop_progress(self):
        self._progress.stop()
        self._cancel_btn.pack_forget()

    def _on_cancel_search(self):
        """Cancel the active search/geocode operation."""
        if self._search_cancellation_token:
            self._search_cancellation_token.cancel()
        self._stop_progress()
        self._search_btn.config(state="normal")
        self._set_status("Search cancelled.")

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _on_close(self):
        self._save_window_geometry()
        self._config["last_radius_miles"] = self._search_radius
        self._config["last_max_results"] = self._max_results_limit
        self._save_ai_settings_to_config()
        save_config(self._config)
        save_notes(self._notes)
        save_shortlist(self._shortlist)
        save_history(self._history)
        save_collections(self._collections)
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
