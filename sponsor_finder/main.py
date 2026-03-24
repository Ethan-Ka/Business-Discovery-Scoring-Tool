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
)
from profiles import load_profiles, save_profiles, get_profile, upsert_profile, delete_profile
from paths import get_data_dir
import ai_scoring


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
    FIELDS    = ["Score", "Category", "Chain", "Has Website", "Has Phone",
                 "Distance", "Target Audience"]
    OPERATORS = [">", "<", "=", "contains", "is not"]

    def __init__(self, parent, existing_rules=None, existing_combine="AND"):
        super().__init__(parent)
        self.title("Build Custom Filter")
        self.resizable(True, False)
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

        # Rules container
        self.rules_frame = ttk.Frame(frm)
        self.rules_frame.pack(fill="x")

        # Add rule button
        ttk.Button(frm, text="+ Add Rule", command=self._add_rule).pack(pady=6)

        # Action buttons
        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Apply", command=self._apply).pack(side="right", padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side="right")

    def _add_rule(self):
        self.rules.append({"field": "Score", "operator": ">", "value": "50"})
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
                         width=14, state="readonly").pack(side="left", padx=2)
            ttk.Combobox(row, textvariable=op_var, values=self.OPERATORS,
                         width=8, state="readonly").pack(side="left", padx=2)
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
                 disable_max_limit: bool = True):
        super().__init__(parent)
        self.title("AI Settings — Local LLM Models")
        self.resizable(True, False)
        self.minsize(420, 0)
        self.grab_set()

        self.result_model    = current_model
        self.result_weight   = current_weight
        self.result_explain  = explain_enabled
        self.result_scoring  = score_enabled
        self.result_max      = max_score
        self.result_disable_max_limit = disable_max_limit
        self.confirmed       = False

        self._model_var    = tk.StringVar(value=current_model)
        self._weight_var   = tk.DoubleVar(value=current_weight)
        self._explain_var  = tk.BooleanVar(value=explain_enabled)
        self._score_var    = tk.BooleanVar(value=score_enabled)
        self._max_var      = tk.IntVar(value=max_score)
        self._disable_max_limit_var = tk.BooleanVar(value=disable_max_limit)
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
            to=200,
            increment=10,
            textvariable=self._max_var,
            width=6,
        )
        self._max_spinbox.pack(side="left", padx=6)
        self._sync_max_limit_state()

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
                 on_ai_settings=None):
        super().__init__(parent, width=SIDEBAR_W)
        self.on_change = on_change
        self._on_profile_load = on_profile_load
        self._on_profile_save = on_profile_save
        self._on_profile_delete = on_profile_delete
        self._on_profile_new = on_profile_new
        self._on_profile_edit = on_profile_edit
        self._on_ai_settings = on_ai_settings
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 3}

        # ── Profiles section ─────────────────────────────────────────────
        ttk.Label(self, text="Profiles", font=("", 10, "bold")).pack(
            anchor="w", **pad)
        ttk.Separator(self).pack(fill="x", padx=8, pady=2)

        self.profile_var = tk.StringVar(value="")
        self.profile_combo = ttk.Combobox(self, textvariable=self.profile_var,
                                          state="readonly", values=[])
        self.profile_combo.pack(fill="x", **pad)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_load_click())

        prof_btns = ttk.Frame(self)
        prof_btns.pack(fill="x", **pad)
        ttk.Button(prof_btns, text="New",
                   command=self._on_new_profile).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(prof_btns, text="Edit",
                   command=self._on_edit_profile).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(prof_btns, text="Delete",
                   command=self._on_delete_click).pack(side="left", expand=True, fill="x", padx=1)

        ttk.Separator(self).pack(fill="x", padx=8, pady=6)

        # ── Filter & Sort section ────────────────────────────────────────
        ttk.Label(self, text="Filter & Sort", font=("", 10, "bold")).pack(
            anchor="w", **pad)
        ttk.Separator(self).pack(fill="x", padx=8, pady=2)

        # Name search
        ttk.Label(self, text="Name search:").pack(anchor="w", **pad)
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *_: self.on_change())
        ttk.Entry(self, textvariable=self.name_var).pack(fill="x", **pad)

        # Category dropdown
        ttk.Label(self, text="Category:").pack(anchor="w", **pad)
        self.cat_var = tk.StringVar(value="All")
        self.cat_var.trace_add("write", lambda *_: self.on_change())
        self.cat_combo = ttk.Combobox(self, textvariable=self.cat_var,
                                      state="readonly", values=["All"])
        self.cat_combo.pack(fill="x", **pad)

        # Hide chains
        self.hide_chains_var = tk.BooleanVar(value=False)
        self.hide_chains_var.trace_add("write", lambda *_: self.on_change())
        ttk.Checkbutton(self, text="Hide chains",
                        variable=self.hide_chains_var).pack(anchor="w", **pad)

        # Min score
        ttk.Label(self, text="Min score:").pack(anchor="w", **pad)
        self.min_score_var = tk.IntVar(value=0)
        self.min_score_label = ttk.Label(self, text="0")
        self.min_score_label.pack(anchor="e", padx=8)
        self.score_slider = ttk.Scale(
            self, from_=0, to=100,
            variable=self.min_score_var,
            command=self._on_score_slide,
        )
        self.score_slider.pack(fill="x", **pad)

        ttk.Separator(self).pack(fill="x", padx=8, pady=6)

        # Sort
        ttk.Label(self, text="Sort by:").pack(anchor="w", **pad)
        self.sort_var = tk.StringVar(value="Score")
        self.sort_var.trace_add("write", lambda *_: self.on_change())
        ttk.Combobox(self, textvariable=self.sort_var, state="readonly",
                     values=["Score", "Distance", "Name", "Category"]).pack(fill="x", **pad)

        ttk.Separator(self).pack(fill="x", padx=8, pady=6)

        # Custom filter button
        self.custom_filter_btn = ttk.Button(self, text="Build Custom Filter",
                                            command=self._open_custom_filter)
        self.custom_filter_btn.pack(fill="x", **pad)
        self.custom_filter_label = ttk.Label(self, text="", foreground="#e67e22",
                                             wraplength=SIDEBAR_W - 20)
        self.custom_filter_label.pack(anchor="w", **pad)
        ttk.Button(self, text="Clear Custom Filter",
                   command=self._clear_custom_filter).pack(fill="x", **pad)

        ttk.Separator(self).pack(fill="x", padx=8, pady=6)

        # ── AI Scoring section ────────────────────────────────────────────
        ttk.Label(self, text="AI Scoring (Local LLM)", font=("", 10, "bold")).pack(
            anchor="w", **pad)
        ttk.Separator(self).pack(fill="x", padx=8, pady=2)

        ai_status_row = ttk.Frame(self)
        ai_status_row.pack(fill="x", **pad)
        self._ai_dot = tk.Label(ai_status_row, text="●", font=("", 10), fg="#95a5a6")
        self._ai_dot.pack(side="left")
        self._ai_status_lbl = ttk.Label(ai_status_row, text="AI offline", foreground="gray",
                                         font=("Segoe UI", 8))
        self._ai_status_lbl.pack(side="left", padx=4)

        self.ai_scoring_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Enable AI Scoring",
                        variable=self.ai_scoring_var).pack(anchor="w", **pad)

        if self._on_ai_settings:
            ttk.Button(self, text="AI Settings…",
                       command=self._on_ai_settings).pack(fill="x", **pad)

        ttk.Separator(self).pack(fill="x", padx=8, pady=6)

        # Reset
        ttk.Button(self, text="Reset All Filters",
                   command=self._reset).pack(fill="x", **pad)

        # Store custom filter state
        self._custom_rules = []
        self._custom_combine = "AND"

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
        if "custom_rules" in state:
            self._custom_rules = list(state["custom_rules"])
        if "custom_combine" in state:
            self._custom_combine = state["custom_combine"]
            n = len(self._custom_rules)
            self.custom_filter_label.config(
                text=f"{n} rule{'s' if n != 1 else ''} active ({self._custom_combine})"
                if n else ""
            )

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

    def _reset(self):
        self.name_var.set("")
        self.cat_var.set("All")
        self.hide_chains_var.set(False)
        self.min_score_var.set(0)
        self.min_score_label.config(text="0")
        self.sort_var.set("Score")
        self._clear_custom_filter()

    def update_categories(self, categories: list[str]):
        current = self.cat_var.get()
        self.cat_combo["values"] = categories
        if current not in categories:
            self.cat_var.set("All")

    def get_state(self) -> dict:
        return {
            "name_query":    self.name_var.get(),
            "category":      self.cat_var.get(),
            "hide_chains":   self.hide_chains_var.get(),
            "min_score":     int(self.min_score_var.get()),
            "sort_by":       self.sort_var.get(),
            "custom_rules":  self._custom_rules,
            "custom_combine": self._custom_combine,
        }


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
        self._notes  = load_notes()
        self._all_businesses: list[dict] = []
        self._shortlist: set[str] = load_shortlist()  # persisted OSM IDs
        self._search_lat  = None
        self._search_lon  = None
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
        self._ai_max_score      = max(10, int(ai_cfg.get("max_score", 50)))
        self._ai_disable_max_limit = bool(ai_cfg.get("disable_max_limit", True))
        self._ai_running        = False   # is local AI model loaded?

        self._apply_window_geometry()
        self._build_ui()
        self._sidebar.ai_scoring_var.set(self._ai_scoring_on)
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

        # Location mode radio buttons
        self._loc_mode = tk.StringVar(value="address")
        modes = [("Address", "address"), ("Saved Location", "saved"), ("Drop a Pin", "pin")]
        for text, val in modes:
            ttk.Radiobutton(bar, text=text, variable=self._loc_mode, value=val,
                            command=self._on_loc_mode_change).pack(side="left", padx=4)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)

        # Address entry field
        self._addr_var = tk.StringVar()
        self._addr_entry = ttk.Entry(bar, textvariable=self._addr_var, width=35)
        self._addr_entry.pack(side="left", padx=4)
        self._addr_entry.bind("<Return>", lambda _: self._trigger_search())

        # Save/Load location buttons
        self._save_loc_btn = ttk.Button(bar, text="Save Location",
                                        command=self._save_location)
        self._save_loc_btn.pack(side="left", padx=2)
        self._load_loc_btn = ttk.Button(bar, text="Load Saved",
                                        command=self._load_saved_location)
        self._load_loc_btn.pack(side="left", padx=2)

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

        self._on_loc_mode_change()

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
        )
        outer_paned.add(self._sidebar, weight=0)

        # --- Results | custom sash | Detail ---
        # Placed manually inside a container so we fully control sash appearance.
        center = ttk.Frame(outer_paned)
        outer_paned.add(center, weight=1)

        results_frame = ttk.Frame(center)
        self._build_treeview(results_frame)

        # Sash: plain frame with grip dots on a Canvas
        _SASH_W = 6
        sash = tk.Frame(center, width=_SASH_W, bg="#d0d0d0",
                        cursor="sb_h_double_arrow")
        dot_cv = tk.Canvas(sash, width=_SASH_W, bg="#d0d0d0",
                           highlightthickness=0)
        dot_cv.pack(fill="both", expand=True)

        def _draw_dots(cv):
            cv.delete("all")
            cw, ch = cv.winfo_width(), cv.winfo_height()
            if cw < 2 or ch < 2:
                return
            cx, cy = cw // 2, ch // 2
            offsets = (-8, -4, 0, 4, 8)
            # Connecting line behind the dots
            cv.create_line(cx, cy + offsets[0], cx, cy + offsets[-1],
                           fill="#999999", width=2)
            # Dots on top
            for dy in offsets:
                cv.create_oval(cx - 2, cy + dy - 2, cx + 2, cy + dy + 2,
                               fill="#999999", outline="")

        dot_cv.bind("<Configure>", lambda e: _draw_dots(dot_cv))

        self._detail = DetailPane(center, self._notes, on_note_saved=self._on_note_saved)

        # _sash_x == None means "use 50% on first render"
        self._sash_x: int | None = None

        def _relayout(event=None):
            w = center.winfo_width()
            h = center.winfo_height()
            if w <= 1 or h <= 1:
                return
            if self._sash_x is None:
                self._sash_x = w // 2
            sx = max(300, min(self._sash_x, w - _SASH_W - 150))
            results_frame.place(x=0,            y=0, width=sx,               height=h)
            sash.place         (x=sx,           y=0, width=_SASH_W,          height=h)
            self._detail.place (x=sx + _SASH_W, y=0, width=w - sx - _SASH_W, height=h)

        center.bind("<Configure>", _relayout)

        _drag: dict = {}

        def _sash_press(e):
            _drag["x"]  = e.x_root
            _drag["sx"] = self._sash_x if self._sash_x is not None \
                          else center.winfo_width() // 2

        def _sash_move(e):
            self._sash_x = _drag["sx"] + (e.x_root - _drag["x"])
            _relayout()

        for widget in (sash, dot_cv):
            widget.bind("<Button-1>", _sash_press)
            widget.bind("<B1-Motion>", _sash_move)

    def _build_treeview(self, parent):
        # Columns include a hidden checkbox-equivalent: managed via selection + shortlist set
        cols = ("shortlist",) + TREE_COLUMNS
        self._tree = ttk.Treeview(parent, columns=cols, show="headings",
                                  selectmode="browse")

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
        self._tree.tag_configure("green",       background="#d4efdf")
        self._tree.tag_configure("red",         background="#fadbd8")
        self._tree.tag_configure("odd",         background="#f5f5f5")
        self._tree.tag_configure("even",        background="#ffffff")
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

        self._count_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self._count_var).pack(side="right", padx=8)

        self._progress = ttk.Progressbar(bar, mode="indeterminate", length=120)
        self._progress.pack(side="right", padx=8)

        self._status_var = tk.StringVar(value="Ready. Enter a location and click Search.")
        ttk.Label(bar, textvariable=self._status_var, anchor="w").pack(side="left", fill="x",
                                                                        expand=True)

    # ------------------------------------------------------------------
    # Location mode
    # ------------------------------------------------------------------

    def _on_loc_mode_change(self):
        mode = self._loc_mode.get()
        if mode == "address":
            self._addr_entry.config(state="normal")
            self._save_loc_btn.config(state="normal")
            self._load_loc_btn.config(state="normal")
        elif mode == "saved":
            self._addr_entry.config(state="disabled")
            saved = self._config.get("saved_location", {})
            self._search_lat = saved.get("lat")
            self._search_lon = saved.get("lon")
            addr = saved.get("address", "No saved location")
            self._addr_var.set(addr)
            self._save_loc_btn.config(state="disabled")
            self._load_loc_btn.config(state="normal")
        elif mode == "pin":
            self._addr_entry.config(state="disabled")
            self._save_loc_btn.config(state="disabled")
            self._load_loc_btn.config(state="disabled")
            # Restore last saved pin into memory so the dialog pre-fills it
            if not (self._search_lat and self._search_lon):
                saved_pin = self._config.get("saved_pin", {})
                if saved_pin.get("lat") and saved_pin.get("lon"):
                    self._search_lat = saved_pin["lat"]
                    self._search_lon = saved_pin["lon"]
                    self._addr_var.set(f"{self._search_lat:.5f}, {self._search_lon:.5f}")
            self._open_pin_dialog()

    @staticmethod
    def _get_device_location():
        """
        Try to get the user's current position from OS location services.
        Returns (lat, lon) or None.

        Priority:
          1. Windows Location API  (winrt — actual device location services)
          2. IP geolocation        (ip-api.com — no API key, free fallback)
        """
        # 1 — Windows Location API
        try:
            import asyncio
            import winrt.windows.devices.geolocation as wdg  # type: ignore

            async def _get():
                locator = wdg.Geolocator()
                pos = await locator.get_geoposition_async()
                c = pos.coordinate
                return c.latitude, c.longitude

            return asyncio.run(_get())
        except Exception:
            pass

        # 2 — IP geolocation fallback
        try:
            import requests as _req
            r = _req.get(
                "http://ip-api.com/json/?fields=status,lat,lon",
                timeout=6,
                headers={"User-Agent": "RedlineSponsorFinder/1.0"},
            )
            data = r.json()
            if data.get("status") == "success":
                return data["lat"], data["lon"]
        except Exception:
            pass

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

        # map widget — open at a wide view first; we'll fly in once located
        map_widget = tmv.TkinterMapView(dlg, width=640, height=420, corner_radius=0)
        map_widget.pack(fill="both", expand=True, padx=8, pady=6)
        map_widget.set_zoom(3)

        _state = {"marker": None, "lat": None, "lon": None, "located": False}

        def _fly_to(lat, lon, zoom=13):
            map_widget.set_position(lat, lon)
            map_widget.set_zoom(zoom)

        # If a pin was already set previously, restore it immediately
        if self._search_lat and self._search_lon:
            _fly_to(self._search_lat, self._search_lon)
            _state["marker"] = map_widget.set_marker(
                self._search_lat, self._search_lon, text="Pin"
            )
            _state["lat"] = self._search_lat
            _state["lon"] = self._search_lon
            _state["located"] = True
            coord_var.set(f"{self._search_lat:.6f}, {self._search_lon:.6f}")
        else:
            # Locate in background; show spinner-like status text
            loc_status_var.set("Locating your position…")

            def _locate():
                result = self._get_device_location()
                if not dlg.winfo_exists():
                    return
                if result:
                    lat, lon = result
                    dlg.after(0, lambda: _on_located(lat, lon))
                else:
                    dlg.after(0, lambda: loc_status_var.set("Could not determine location"))

            def _on_located(lat, lon):
                if not dlg.winfo_exists():
                    return
                loc_status_var.set("Location found")
                _fly_to(lat, lon)
                # Place a faint "You are here" marker only if the user hasn't
                # already dropped a pin of their own
                if not _state["located"]:
                    if _state["marker"]:
                        _state["marker"].delete()
                    _state["marker"] = map_widget.set_marker(lat, lon, text="You are here")
                    _state["lat"] = lat
                    _state["lon"] = lon
                    _state["located"] = True
                    coord_var.set(f"{lat:.6f}, {lon:.6f}")

            threading.Thread(target=_locate, daemon=True).start()

        def _on_map_click(coords):
            lat, lon = coords
            _state["lat"], _state["lon"] = lat, lon
            _state["located"] = True
            coord_var.set(f"{lat:.6f}, {lon:.6f}")
            loc_status_var.set("")
            if _state["marker"]:
                _state["marker"].delete()
            _state["marker"] = map_widget.set_marker(lat, lon, text="Pin")

        map_widget.add_left_click_map_command(_on_map_click)

        # bottom button bar
        btn_bar = ttk.Frame(dlg)
        btn_bar.pack(fill="x", padx=8, pady=(0, 8))

        def _confirm():
            if _state["lat"] is None:
                messagebox.showwarning("No pin", "Click the map first to drop a pin.",
                                       parent=dlg)
                return
            self._search_lat = _state["lat"]
            self._search_lon = _state["lon"]
            self._addr_var.set(f"{self._search_lat:.5f}, {self._search_lon:.5f}")
            # Persist the pin so it survives app restarts
            self._config["saved_pin"] = {"lat": self._search_lat, "lon": self._search_lon}
            save_config(self._config)
            dlg.destroy()

        ttk.Button(btn_bar, text="Confirm Pin", command=_confirm).pack(side="right", padx=4)
        ttk.Button(btn_bar, text="Cancel", command=dlg.destroy).pack(side="right")

    def _open_pin_dialog_text(self):
        """Fallback plain lat/lon dialog when tkintermapview is not installed."""
        dlg = tk.Toplevel(self)
        dlg.title("Drop a Pin Manually")
        dlg.grab_set()
        dlg.resizable(False, False)

        frm = ttk.Frame(dlg, padding=16)
        frm.pack()

        ttk.Label(frm, text="Install tkintermapview for an interactive map.", foreground="gray",
                  font=("Segoe UI", 8)).grid(row=0, column=0, columnspan=2, pady=(0, 8))

        lat_var = tk.StringVar(value=str(self._search_lat or ""))
        lon_var = tk.StringVar(value=str(self._search_lon or ""))

        ttk.Label(frm, text="Latitude:").grid(row=1, column=0, sticky="e", pady=4, padx=4)
        ttk.Entry(frm, textvariable=lat_var, width=18).grid(row=1, column=1, pady=4)
        ttk.Label(frm, text="Longitude:").grid(row=2, column=0, sticky="e", pady=4, padx=4)
        ttk.Entry(frm, textvariable=lon_var, width=18).grid(row=2, column=1, pady=4)

        def _confirm():
            try:
                self._search_lat = float(lat_var.get())
                self._search_lon = float(lon_var.get())
                self._addr_var.set(f"{self._search_lat:.5f}, {self._search_lon:.5f}")
                # Persist the pin so it survives app restarts
                self._config["saved_pin"] = {"lat": self._search_lat, "lon": self._search_lon}
                save_config(self._config)
                dlg.destroy()
            except ValueError:
                messagebox.showerror("Invalid", "Please enter valid decimal coordinates.",
                                     parent=dlg)

        ttk.Button(frm, text="OK", command=_confirm).grid(row=3, column=0, columnspan=2, pady=8)

    def _save_location(self):
        if self._search_lat and self._search_lon:
            self._config["saved_location"] = {
                "address": self._addr_var.get(),
                "lat": self._search_lat,
                "lon": self._search_lon,
            }
            save_config(self._config)
            self._set_status("Location saved.")
        else:
            messagebox.showinfo("No Location", "Search first to geocode a location, then save.")

    def _load_saved_location(self):
        saved = self._config.get("saved_location", {})
        if saved.get("lat") and saved.get("lon"):
            self._search_lat = saved["lat"]
            self._search_lon = saved["lon"]
            self._addr_var.set(saved.get("address", ""))
            self._set_status("Saved location loaded.")
        else:
            messagebox.showinfo("No Saved Location",
                                "No location saved yet. Enter an address and click Save Location.")

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
        mode = self._loc_mode.get()

        if mode == "address":
            addr = self._addr_var.get().strip()
            if not addr:
                messagebox.showwarning("No Address", "Please enter an address to search.")
                return
            self._geocode_then_search(addr)
        elif mode in ("saved", "pin"):
            if not self._search_lat or not self._search_lon:
                messagebox.showwarning("No Location",
                                       "No location set. Choose 'Address' or 'Drop a Pin'.")
                return
            self._run_search(self._search_lat, self._search_lon)

    def _geocode_then_search(self, address: str):
        self._set_status("Geocoding address…")
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
        self._set_status("Searching…")
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
        dlg.geometry(f"+{mx + mw // 2 - 200}+{my + mh // 2 - 70}")

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
        )
        filtered = apply_custom_filter(
            filtered,
            rules=state["custom_rules"],
            combine=state["custom_combine"],
        )
        filtered = sort_businesses(filtered, sort_by=state["sort_by"])

        self._populate_tree(filtered)
        total = len(self._all_businesses)
        shown = len(filtered)
        self._count_var.set(f"Showing {shown} of {total} businesses")

    def _populate_tree(self, businesses: list[dict]):
        self._tree.delete(*self._tree.get_children())
        self._iid_map.clear()
        self._detail.clear()

        for i, b in enumerate(businesses):
            score   = b.get("score", 0)
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
        """Right-click context menu: shortlist toggle + add note."""
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        self._tree.selection_set(iid)
        b = self._iid_map.get(iid)
        if not b:
            return
        osm_id = b.get("osm_id", "")
        self._detail.show(b)

        menu = tk.Menu(self, tearoff=0)
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

    def _sort_by_column(self, col: str):
        """Sort treeview by column header click."""
        # Map column id to sort key
        col_to_sort = {
            "score": "Score",
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
                self._search_lat = float(lat)
                self._search_lon = float(lon)
                self._addr_var.set(loc.get("address", ""))
                # Manually put top bar into address mode (radiobutton command
                # only fires on user click, not on programmatic set())
                self._loc_mode.set("address")
                self._addr_entry.config(state="normal")
                self._save_loc_btn.config(state="normal")
                self._load_loc_btn.config(state="normal")

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

        self.after(0, _on_model_loaded, False)  # Initially unavailable
        threading.Thread(target=_run, daemon=True).start()

    # Backward compatibility alias
    def _check_ollama_status(self):
        self._check_ai_status()

    def _prompt_download_model(self):
        """
        Show a prompt when no models are available.
        Offers to open AI Settings to download one.
        """
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

        answer = messagebox.askyesno(
            "AI Model Required",
            msg,
            parent=self,
        )
        if answer:
            self._open_ai_settings()

    def _open_ai_settings(self):
        dlg = AISettingsDialog(
            self,
            current_model=self._ai_model,
            current_weight=self._ai_weight,
            explain_enabled=self._ai_explain_on,
            score_enabled=self._ai_scoring_on,
            max_score=self._ai_max_score,
            disable_max_limit=self._ai_disable_max_limit,
        )
        self.wait_window(dlg)
        if dlg.confirmed:
            self._ai_model      = dlg.result_model
            self._ai_weight     = dlg.result_weight
            self._ai_explain_on = dlg.result_explain
            self._ai_scoring_on = dlg.result_scoring
            self._ai_max_score  = dlg.result_max
            self._ai_disable_max_limit = dlg.result_disable_max_limit

            # Apply selected model immediately (if available) so AI works without restart.
            self._ai_running = ai_scoring.load_default_model(self._ai_model)
            if not self._ai_running:
                for candidate in ai_scoring.list_models():
                    if ai_scoring.load_default_model(candidate):
                        self._ai_running = True
                        self._ai_model = candidate
                        break

            self._sidebar.set_ai_status(self._ai_running)
            self._sidebar.ai_scoring_var.set(self._ai_scoring_on)
            self._save_ai_settings_to_config()
            save_config(self._config)

    def _save_ai_settings_to_config(self):
        self._config["ai_settings"] = {
            "model": self._ai_model,
            "weight": self._ai_weight,
            "explain_on": self._ai_explain_on,
            "scoring_on": self._ai_scoring_on,
            "max_score": self._ai_max_score,
            "disable_max_limit": self._ai_disable_max_limit,
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
        self._apply_filters()

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

    def _stop_progress(self):
        self._progress.stop()

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
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()
