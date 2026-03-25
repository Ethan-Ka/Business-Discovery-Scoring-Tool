"""
Unified Settings dialog — File > Settings.

Four tabs:
  Data Sources  — built-in sources (always on) + optional API-key sources
                  with OS keychain storage, show/hide key, and test connection
  AI            — local model selector, score blend, feature toggles,
                  and the model download panel
  Search        — max results, default radius, Overpass timeout, workers
  Debug         — verbose flags, cache management, data-file shortcuts,
                  and a live diagnostics runner
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import ai_scoring
import applog
import keystore
from export import load_config, save_config
from paths import get_cache_path, get_data_dir, get_log_path, get_tile_cache_path


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------

def _section(parent, title: str) -> ttk.LabelFrame:
    frm = ttk.LabelFrame(parent, text=title, padding=(10, 6))
    frm.pack(fill="x", padx=4, pady=(0, 8))
    return frm


def _row(parent) -> ttk.Frame:
    frm = ttk.Frame(parent)
    frm.pack(fill="x", pady=2)
    return frm


def _status_dot(parent, color: str = "#95a5a6") -> tk.Label:
    lbl = tk.Label(parent, text="●", font=("", 12), fg=color)
    lbl.pack(side="left", padx=(0, 4))
    return lbl


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------

class SettingsDialog(tk.Toplevel):
    """
    Unified settings dialog.  Pass start_tab to open at a specific page:
      0 = Data Sources, 1 = AI, 2 = Search, 3 = Debug
    """

    def __init__(self, parent, app, start_tab: int = 0):
        super().__init__(parent)
        self.app = app
        self._pulling = False
        self._pull_token = None

        self.title("Settings")
        self.geometry("680x620")
        self.minsize(600, 520)
        self.resizable(True, True)
        self.grab_set()

        self._init_vars()
        self._build_ui()
        self._notebook.select(start_tab)

        # Kick off async status checks after the window is visible.
        self.after(50, self._async_refresh_ai_status)

    # ── Variable initialisation ───────────────────────────────────────────

    def _init_vars(self):
        app = self.app
        cfg = app._config

        # ── AI ──
        self._ai_model_var   = tk.StringVar(value=app._ai_model)
        self._ai_weight_var  = tk.DoubleVar(value=app._ai_weight)
        self._ai_explain_var = tk.BooleanVar(value=app._ai_explain_on)
        self._ai_score_var   = tk.BooleanVar(value=app._ai_scoring_on)
        self._ai_max_var     = tk.IntVar(value=app._ai_max_score)
        self._ai_nolimit_var = tk.BooleanVar(value=app._ai_disable_max_limit)
        self._dl_model_var   = tk.StringVar()
        self._pull_status_var = tk.StringVar()

        # ── Data sources ──
        ds = cfg.get("data_sources", {})
        self._gp_enabled_var   = tk.BooleanVar(value=ds.get("google_places_enabled", False))
        self._yelp_enabled_var = tk.BooleanVar(value=ds.get("yelp_enabled", False))
        # Key fields populated after UI is built (keystore read)
        self._gp_key_var   = tk.StringVar()
        self._yelp_key_var = tk.StringVar()
        self._gp_show_var   = tk.BooleanVar(value=False)
        self._yelp_show_var = tk.BooleanVar(value=False)

        # ── Search ──
        ss = cfg.get("search_settings", {})
        self._max_results_var = tk.IntVar(
            value=getattr(app, "_max_results_limit", 250))
        self._radius_var = tk.DoubleVar(
            value=getattr(app, "_search_radius", 5.0))
        self._timeout_var  = tk.IntVar(value=ss.get("overpass_timeout", 68))
        self._workers_var  = tk.IntVar(value=ss.get("max_enrichment_workers", 10))

        # ── Debug ──
        dbg = cfg.get("debug_settings", {})
        self._debug_var       = tk.BooleanVar(value=getattr(app, "_ai_debug", False))
        self._verbose_enrich_var    = tk.BooleanVar(
            value=dbg.get("verbose_enrichment", False))
        self._show_prompts_var = tk.BooleanVar(
            value=dbg.get("show_ai_prompts", False))
        self._store_logs_var = tk.BooleanVar(
            value=dbg.get("store_logs", True))

    # ── Top-level UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        self._build_sources_tab()
        self._build_ai_tab()
        self._build_search_tab()
        self._build_debug_tab()

        # Bottom button bar
        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_bar, text="Save", command=self._save).pack(side="right", padx=4)
        ttk.Button(btn_bar, text="Apply", command=self._apply).pack(side="right")
        ttk.Button(btn_bar, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 4))

    # ── Tab: Data Sources ─────────────────────────────────────────────────

    def _build_sources_tab(self):
        outer = ttk.Frame(self._notebook)
        self._notebook.add(outer, text="Data Sources")

        canvas = tk.Canvas(outer, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = ttk.Frame(canvas, padding=(8, 6))
        win_id = canvas.create_window((0, 0), window=body, anchor="nw")

        def _resize(e):
            canvas.itemconfigure(win_id, width=e.width)
        def _scroll(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", _resize)
        body.bind("<Configure>", _scroll)
        canvas.bind("<Enter>", lambda _: canvas.bind_all(
            "<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta/120), "units")))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        # ── Keychain status banner ──
        if keystore.has_keyring():
            banner_text = "🔒  API keys are stored in the OS keychain (secure)."
            banner_bg = "#eafaf1"
            banner_fg = "#1e8449"
        else:
            banner_text = (
                "⚠  keyring not available — API keys stored in config.json (plaintext).\n"
                "   Install the 'keyring' package for secure OS keychain storage."
            )
            banner_bg = "#fef9e7"
            banner_fg = "#7d6608"

        banner = tk.Frame(body, background=banner_bg, padx=10, pady=6)
        banner.pack(fill="x", pady=(0, 10))
        tk.Label(banner, text=banner_text, background=banner_bg, foreground=banner_fg,
                 font=("Segoe UI", 8), justify="left", anchor="w",
                 wraplength=560).pack(anchor="w")

        # ── Built-in sources ──
        sec_builtin = _section(body, "Built-in Sources  (always active)")

        self._source_card(
            sec_builtin,
            name="OpenStreetMap / Overpass",
            desc="Core business data — fetches businesses from OpenStreetMap via the Overpass API. "
                 "No account or key required.",
            always_on=True,
        )

        self._source_card(
            sec_builtin,
            name="Wikidata",
            desc="Chain detection and entity intelligence — identifies chain businesses, "
                 "parent companies, and location counts. No account or key required.",
            always_on=True,
        )

        # ── Optional sources ──
        sec_opt = _section(body, "Optional Sources  (API key required)")

        self._source_card(
            sec_opt,
            name="Google Places",
            desc="Ratings, review count, photos, and richer business data. "
                 "Requires a Google Cloud project with Places API enabled.",
            always_on=False,
            enabled_var=self._gp_enabled_var,
            key_var=self._gp_key_var,
            show_var=self._gp_show_var,
            key_name="google_places",
            test_fn=self._test_google_places,
        )

        self._source_card(
            sec_opt,
            name="Yelp Fusion",
            desc="Ratings, price level, and review snippets. "
                 "Requires a free Yelp Fusion API key.",
            always_on=False,
            enabled_var=self._yelp_enabled_var,
            key_var=self._yelp_key_var,
            show_var=self._yelp_show_var,
            key_name="yelp",
            test_fn=self._test_yelp,
        )

        # Populate key fields from keystore after UI is built.
        self._gp_key_var.set(keystore.get_key("google_places"))
        self._yelp_key_var.set(keystore.get_key("yelp"))

    def _source_card(self, parent, name, desc, always_on, enabled_var=None,
                     key_var=None, show_var=None, key_name=None, test_fn=None):
        card = ttk.Frame(parent, relief="flat")
        card.pack(fill="x", pady=(0, 8))

        # Header row
        hdr = ttk.Frame(card)
        hdr.pack(fill="x")
        if always_on:
            tk.Label(hdr, text="●", font=("", 10), fg="#27ae60").pack(side="left", padx=(0, 4))
            ttk.Label(hdr, text=name, font=("Segoe UI", 9, "bold")).pack(side="left")
            ttk.Label(hdr, text="Always active", foreground="#27ae60",
                      font=("Segoe UI", 8)).pack(side="right")
        else:
            ttk.Checkbutton(hdr, text=name, variable=enabled_var,
                            style="TCheckbutton").pack(side="left")
            ttk.Label(hdr, text="(enable when key is set)", foreground="#888",
                      font=("Segoe UI", 8)).pack(side="left", padx=6)

        # Description
        ttk.Label(card, text=desc, foreground="#555", font=("Segoe UI", 8),
                  wraplength=520, justify="left").pack(anchor="w", pady=(2, 4))

        if always_on:
            ttk.Separator(card, orient="horizontal").pack(fill="x", pady=(4, 0))
            return

        # Key entry row
        key_row = ttk.Frame(card)
        key_row.pack(fill="x")
        ttk.Label(key_row, text="API Key:", width=8).pack(side="left")
        entry = ttk.Entry(key_row, textvariable=key_var, show="*", width=36)
        entry.pack(side="left", padx=(0, 4))

        def _toggle_show():
            show_var.set(not show_var.get())
            entry.config(show="" if show_var.get() else "*")
            eye_btn.config(text="Hide" if show_var.get() else "Show")

        eye_btn = ttk.Button(key_row, text="Show", width=5, command=_toggle_show)
        eye_btn.pack(side="left", padx=2)

        # Status + action row
        action_row = ttk.Frame(card)
        action_row.pack(fill="x", pady=(4, 0))

        storage_lbl = ttk.Label(action_row,
                                text=keystore.storage_label(key_name),
                                foreground="#777", font=("Segoe UI", 8))
        storage_lbl.pack(side="left")

        def _clear_key():
            key_var.set("")
            keystore.set_key(key_name, "")
            storage_lbl.config(text=keystore.storage_label(key_name))
            test_lbl.config(text="")

        test_lbl = ttk.Label(action_row, text="", font=("Segoe UI", 8))
        test_lbl.pack(side="right", padx=(4, 0))

        ttk.Button(action_row, text="Test", width=5,
                   command=lambda: test_fn(key_var.get(), test_lbl, storage_lbl, key_name)
                   ).pack(side="right", padx=2)
        ttk.Button(action_row, text="Clear key", width=8,
                   command=_clear_key).pack(side="right", padx=2)

        ttk.Separator(card, orient="horizontal").pack(fill="x", pady=(6, 0))

    # ── API connection tests (async) ──────────────────────────────────────

    def _test_google_places(self, key, status_lbl, storage_lbl, key_name):
        if not key.strip():
            messagebox.showwarning("No Key", "Enter an API key first.", parent=self)
            return
        status_lbl.config(text="Testing…", foreground="#2980b9")
        self._run_test(
            lambda: self._do_test_google(key.strip()),
            status_lbl, storage_lbl, key_name, key.strip(),
        )

    def _test_yelp(self, key, status_lbl, storage_lbl, key_name):
        if not key.strip():
            messagebox.showwarning("No Key", "Enter an API key first.", parent=self)
            return
        status_lbl.config(text="Testing…", foreground="#2980b9")
        self._run_test(
            lambda: self._do_test_yelp(key.strip()),
            status_lbl, storage_lbl, key_name, key.strip(),
        )

    def _run_test(self, fn, status_lbl, storage_lbl, key_name, key_value):
        q = queue.Queue()

        def _run():
            try:
                ok, msg = fn()
                q.put((ok, msg))
            except Exception as exc:
                q.put((False, str(exc)))

        def _process():
            try:
                ok, msg = q.get_nowait()
                if not self.winfo_exists():
                    return
                if ok:
                    status_lbl.config(text=f"✓ {msg}", foreground="#27ae60")
                    keystore.set_key(key_name, key_value)
                    storage_lbl.config(text=keystore.storage_label(key_name))
                else:
                    status_lbl.config(text=f"✗ {msg}", foreground="#e74c3c")
            except queue.Empty:
                if self.winfo_exists():
                    self.after(100, _process)

        threading.Thread(target=_run, daemon=True).start()
        _process()

    @staticmethod
    def _do_test_google(key: str):
        import requests
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": "test", "key": key},
                timeout=8,
            ).json()
            status = r.get("status", "")
            if status in ("OK", "ZERO_RESULTS"):
                return True, "Key is valid"
            return False, f"Rejected ({status})"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _do_test_yelp(key: str):
        import requests
        try:
            r = requests.get(
                "https://api.yelp.com/v3/businesses/search",
                headers={"Authorization": f"Bearer {key}"},
                params={"location": "New York", "term": "food", "limit": 1},
                timeout=8,
            )
            if r.status_code == 200:
                return True, "Key is valid"
            return False, f"HTTP {r.status_code}"
        except Exception as exc:
            return False, str(exc)

    # ── Tab: AI ───────────────────────────────────────────────────────────

    def _build_ai_tab(self):
        outer = ttk.Frame(self._notebook)
        self._notebook.add(outer, text="AI")

        canvas = tk.Canvas(outer, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = ttk.Frame(canvas, padding=(8, 6))
        win_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win_id, width=e.width))
        body.bind("<Configure>",
                  lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Enter>", lambda _: canvas.bind_all(
            "<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta/120), "units")))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        # ── Status ──
        sec_status = _section(body, "Model Status")
        status_row = _row(sec_status)
        self._ai_dot = _status_dot(status_row)
        self._ai_status_lbl = ttk.Label(status_row, text="Checking…", foreground="gray")
        self._ai_status_lbl.pack(side="left")
        ttk.Button(status_row, text="Recheck", width=8,
                   command=self._async_refresh_ai_status).pack(side="right")

        model_row = _row(sec_status)
        ttk.Label(model_row, text="Active model:").pack(side="left")
        self._model_combo = ttk.Combobox(model_row, textvariable=self._ai_model_var,
                                          state="readonly",
                                          values=[self._ai_model_var.get()], width=28)
        self._model_combo.pack(side="left", padx=6)
        ttk.Button(model_row, text="Refresh", width=8,
                   command=self._refresh_models).pack(side="left")

        # ── Score blend ──
        sec_blend = _section(body, "Score Blend")
        ttk.Label(sec_blend, text="Rule  ◄─────────────────►  AI",
                  foreground="#555").pack(anchor="w")
        self._weight_lbl = ttk.Label(sec_blend, foreground="#555")
        self._weight_lbl.pack(anchor="e")
        ttk.Scale(sec_blend, from_=0.0, to=1.0, variable=self._ai_weight_var,
                  orient="horizontal",
                  command=self._on_weight_change).pack(fill="x", pady=2)
        self._on_weight_change(self._ai_weight_var.get())

        # ── Feature toggles ──
        sec_feat = _section(body, "Features")
        ttk.Checkbutton(sec_feat,
                        text="Auto-generate AI explanation on row select",
                        variable=self._ai_explain_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(sec_feat,
                        text="Enable AI batch scoring mode  (slower)",
                        variable=self._ai_score_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(sec_feat,
                        text="Score all results  (disable max limit)",
                        variable=self._ai_nolimit_var,
                        command=self._sync_max_limit).pack(anchor="w", pady=2)
        max_row = _row(sec_feat)
        ttk.Label(max_row, text="Max businesses to AI score:").pack(side="left")
        self._max_spinbox = ttk.Spinbox(max_row, from_=10, to=2000, increment=10,
                                         textvariable=self._ai_max_var, width=7)
        self._max_spinbox.pack(side="left", padx=6)
        self._sync_max_limit()

        # ── Model download ──
        sec_dl = _section(body, "Download Models")
        ttk.Label(sec_dl,
                  text="Models are cached locally — download once, use fully offline.\n"
                       "A green ✓ marks models already installed on this machine.",
                  foreground="#555", font=("Segoe UI", 8), justify="left").pack(
                      anchor="w", pady=(0, 6))

        cols = ("model", "description", "size")
        self._rec_tree = ttk.Treeview(sec_dl, columns=cols, show="headings",
                                       height=5, selectmode="browse")
        self._rec_tree.heading("model",       text="Model ID")
        self._rec_tree.heading("description", text="Description")
        self._rec_tree.heading("size",        text="Size")
        self._rec_tree.column("model",       width=120, stretch=False)
        self._rec_tree.column("description", width=260)
        self._rec_tree.column("size",        width=70,  stretch=False)
        for mid, desc, size in ai_scoring.RECOMMENDED_MODELS:
            self._rec_tree.insert("", "end", values=(mid, desc, size))
        self._rec_tree.pack(fill="x", pady=(0, 4))
        self._rec_tree.bind("<<TreeviewSelect>>", self._on_rec_select)

        dl_row = _row(sec_dl)
        ttk.Label(dl_row, text="Model ID:").pack(side="left")
        ttk.Entry(dl_row, textvariable=self._dl_model_var, width=24).pack(
            side="left", padx=6)
        self._pull_btn = ttk.Button(dl_row, text="Download",
                                     command=self._start_pull)
        self._pull_btn.pack(side="left")
        self._cancel_pull_btn = ttk.Button(dl_row, text="Cancel",
                                            command=self._cancel_pull,
                                            state="disabled")
        self._cancel_pull_btn.pack(side="left", padx=4)

        ttk.Label(sec_dl, textvariable=self._pull_status_var,
                  foreground="#2980b9", font=("Segoe UI", 8),
                  wraplength=500).pack(anchor="w", pady=(2, 0))
        self._pull_bar = ttk.Progressbar(sec_dl, mode="determinate", length=500)
        self._pull_bar.pack(fill="x", pady=2)

    # ── AI helpers ────────────────────────────────────────────────────────

    def _on_weight_change(self, val):
        v = float(val)
        rule_pct = round((1 - v) * 100)
        ai_pct   = round(v * 100)
        self._weight_lbl.config(text=f"Rule {rule_pct}%  /  AI {ai_pct}%")

    def _sync_max_limit(self):
        state = "disabled" if self._ai_nolimit_var.get() else "normal"
        self._max_spinbox.config(state=state)

    def _async_refresh_ai_status(self):
        if not self.winfo_exists():
            return
        self._ai_status_lbl.config(text="Checking…", foreground="gray")
        self._ai_dot.config(fg="#95a5a6")

        q = queue.Queue()

        def _run():
            ready = ai_scoring.is_ai_ready()
            if not ready:
                models = ai_scoring.list_models()
                if models:
                    preferred = self._ai_model_var.get()
                    for candidate in [preferred, ai_scoring.DEFAULT_MODEL] + models:
                        if candidate and ai_scoring.load_default_model(candidate):
                            ready = True
                            break
            q.put(ready)

        def _process():
            try:
                ready = q.get_nowait()
                if not self.winfo_exists():
                    return
                if ready:
                    self._ai_dot.config(fg="#27ae60")
                    self._ai_status_lbl.config(text="Ready", foreground="#27ae60")
                    self._refresh_models()
                else:
                    self._ai_dot.config(fg="#e74c3c")
                    self._ai_status_lbl.config(
                        text="No model loaded — download one below.",
                        foreground="#e74c3c")
            except queue.Empty:
                if self.winfo_exists():
                    self.after(100, _process)

        threading.Thread(target=_run, daemon=True).start()
        _process()

    def _refresh_models(self):
        q = queue.Queue()

        def _run():
            q.put(ai_scoring.list_models())

        def _process():
            try:
                models = q.get_nowait()
                if not self.winfo_exists():
                    return
                if models:
                    self._model_combo["values"] = models
                    if self._ai_model_var.get() not in models:
                        self._ai_model_var.set(ai_scoring.pick_best_model(models))
                    try:
                        from model_manager import resolve_model_filename
                    except ImportError:
                        resolve_model_filename = lambda x: x
                    for iid in self._rec_tree.get_children():
                        mid = self._rec_tree.item(iid, "values")[0]
                        tag = "installed" if resolve_model_filename(mid) in models else ""
                        self._rec_tree.item(iid, tags=(tag,))
                    self._rec_tree.tag_configure("installed", foreground="#27ae60")
            except queue.Empty:
                if self.winfo_exists():
                    self.after(100, _process)

        threading.Thread(target=_run, daemon=True).start()
        _process()

    def _on_rec_select(self, _event):
        sel = self._rec_tree.selection()
        if sel:
            self._dl_model_var.set(self._rec_tree.item(sel[0], "values")[0])

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
        self._cancel_pull_btn.config(state="normal")
        self._pull_bar["value"] = 0
        self._pull_status_var.set(f"Starting download of '{name}'…")

        q = queue.Queue()

        def _on_progress(status, pct):
            label = status if len(status) < 70 else status[:67] + "…"
            q.put(("progress", label, pct))

        def _on_done():
            self._pulling = False
            loaded = ai_scoring.load_default_model(name)
            q.put(("done", loaded, None))

        def _on_error(msg):
            self._pulling = False
            q.put(("error", msg, None))

        import ai_scoring as _ai
        from cancellation import CancellationToken
        self._pull_token = CancellationToken()
        threading.Thread(
            target=lambda: _ai.pull_model(
                name, _on_progress, _on_done, _on_error,
                cancellation_token=self._pull_token,
            ),
            daemon=True,
        ).start()

        def _process():
            try:
                while True:
                    try:
                        msg = q.get_nowait()
                    except queue.Empty:
                        break

                    if not self.winfo_exists():
                        return

                    kind = msg[0]
                    if kind == "progress":
                        _, label, pct = msg
                        self._pull_status_var.set(label)
                        if pct is not None:
                            self._pull_bar["value"] = pct * 100
                    elif kind == "done":
                        _, loaded, _ = msg
                        self._pull_btn.config(state="normal")
                        self._cancel_pull_btn.config(state="disabled")
                        if loaded:
                            self._pull_status_var.set(f"✓ '{name}' downloaded and loaded.")
                            self._pull_bar["value"] = 100
                            self._async_refresh_ai_status()
                        else:
                            self._pull_status_var.set(
                                f"Downloaded but could not load '{name}'.")
                        return
                    elif kind == "error":
                        _, err_msg, _ = msg
                        self._pull_btn.config(state="normal")
                        self._cancel_pull_btn.config(state="disabled")
                        self._pull_status_var.set(f"Error: {err_msg}")
                        return

            except tk.TclError:
                return

            if self.winfo_exists():
                self.after(100, _process)

        _process()

    def _cancel_pull(self):
        if self._pull_token:
            self._pull_token.cancel()
        self._pulling = False
        self._pull_btn.config(state="normal")
        self._cancel_pull_btn.config(state="disabled")
        self._pull_status_var.set("Download cancelled.")

    # ── Tab: Search ───────────────────────────────────────────────────────

    def _build_search_tab(self):
        outer = ttk.Frame(self._notebook, padding=12)
        self._notebook.add(outer, text="Search")

        sec_results = _section(outer, "Result Limits")

        r = _row(sec_results)
        ttk.Label(r, text="Max businesses per search:", width=30).pack(side="left")
        ttk.Spinbox(r, from_=50, to=2000, increment=50,
                    textvariable=self._max_results_var, width=7).pack(side="left", padx=6)
        ttk.Label(r, text="(50 – 2000)", foreground="#888",
                  font=("Segoe UI", 8)).pack(side="left")

        r = _row(sec_results)
        ttk.Label(r, text="Default search radius (miles):", width=30).pack(side="left")
        ttk.Spinbox(r, from_=0.5, to=25.0, increment=0.5, format="%.1f",
                    textvariable=self._radius_var, width=7).pack(side="left", padx=6)
        ttk.Label(r, text="(0.5 – 25 mi)", foreground="#888",
                  font=("Segoe UI", 8)).pack(side="left")

        sec_fetch = _section(outer, "Fetch & Enrichment")

        r = _row(sec_fetch)
        ttk.Label(r, text="Overpass request timeout (seconds):", width=30).pack(side="left")
        ttk.Spinbox(r, from_=10, to=180, increment=5,
                    textvariable=self._timeout_var, width=7).pack(side="left", padx=6)
        ttk.Label(r, text="(10 – 180 s)", foreground="#888",
                  font=("Segoe UI", 8)).pack(side="left")

        r = _row(sec_fetch)
        ttk.Label(r, text="Max enrichment workers:", width=30).pack(side="left")
        ttk.Spinbox(r, from_=1, to=20, increment=1,
                    textvariable=self._workers_var, width=7).pack(side="left", padx=6)
        ttk.Label(r, text="(1 – 20 threads)", foreground="#888",
                  font=("Segoe UI", 8)).pack(side="left")

        ttk.Label(outer,
                  text="Changes take effect on the next search.",
                  foreground="#888", font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

    # ── Tab: Debug & Advanced ─────────────────────────────────────────────

    def _build_debug_tab(self):
        outer = ttk.Frame(self._notebook, padding=12)
        self._notebook.add(outer, text="Debug & Advanced")

        # ── Logging toggles ──
        sec_log = _section(outer, "Verbose Logging")
        ttk.Checkbutton(sec_log, text="Debug mode  (verbose AI logs in console)",
                        variable=self._debug_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(sec_log,
                        text="Verbose enrichment logging  (Wikidata / industry inference steps)",
                        variable=self._verbose_enrich_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(sec_log,
                        text="Show AI prompts in console  (full prompt text before each LLM call)",
                        variable=self._show_prompts_var).pack(anchor="w", pady=2)

        # ── Log file ──
        sec_logs = _section(outer, "Logs")
        ttk.Checkbutton(
            sec_logs,
            text="Store logs to file (data/logs/app.log)",
            variable=self._store_logs_var,
        ).pack(anchor="w", pady=2)

        r = _row(sec_logs)
        ttk.Button(r, text="Open log file", width=20,
                   command=lambda: _open_file(get_log_path())).pack(side="left")
        ttk.Button(r, text="Clear log file", width=20,
                   command=self._clear_log_file).pack(side="left", padx=6)
        self._log_size_lbl = ttk.Label(r, text="", foreground="#777",
                                       font=("Segoe UI", 8))
        self._log_size_lbl.pack(side="left", padx=8)
        self._refresh_log_label()

        # ── Cache management ──
        sec_cache = _section(outer, "Cache Management")

        def _clear_entity_cache():
            path = get_cache_path()
            count = 0
            if os.path.exists(path):
                try:
                    import json
                    with open(path, encoding="utf-8") as f:
                        count = len(json.load(f))
                except Exception:
                    pass
                os.remove(path)
            messagebox.showinfo("Cache Cleared",
                                f"Entity cache cleared ({count} entries removed).",
                                parent=self)
            self._refresh_cache_labels()

        def _clear_tile_cache():
            path = get_tile_cache_path()
            size_mb = 0.0
            if os.path.exists(path):
                size_mb = os.path.getsize(path) / (1024 * 1024)
                os.remove(path)
            messagebox.showinfo("Cache Cleared",
                                f"Map tile cache cleared ({size_mb:.1f} MB freed).",
                                parent=self)
            self._refresh_cache_labels()

        def _clear_ai_cache():
            ai_scoring.clear_session_cache()
            messagebox.showinfo("Cache Cleared",
                                "AI explanation and score cache cleared for this session.",
                                parent=self)

        r = _row(sec_cache)
        ttk.Button(r, text="Clear entity cache", command=_clear_entity_cache,
                   width=20).pack(side="left")
        self._entity_cache_lbl = ttk.Label(r, text="", foreground="#777",
                                            font=("Segoe UI", 8))
        self._entity_cache_lbl.pack(side="left", padx=8)

        r = _row(sec_cache)
        ttk.Button(r, text="Clear map tile cache", command=_clear_tile_cache,
                   width=20).pack(side="left")
        self._tile_cache_lbl = ttk.Label(r, text="", foreground="#777",
                                          font=("Segoe UI", 8))
        self._tile_cache_lbl.pack(side="left", padx=8)

        r = _row(sec_cache)
        ttk.Button(r, text="Clear AI score cache", command=_clear_ai_cache,
                   width=20).pack(side="left")
        ttk.Label(r, text="(session only — no file to delete)",
                  foreground="#777", font=("Segoe UI", 8)).pack(side="left", padx=8)

        self._refresh_cache_labels()

        # ── Data files ──
        sec_files = _section(outer, "Data Files")

        def _open_folder():
            path = get_data_dir()
            if os.name == "nt":
                os.startfile(path)
            else:
                import subprocess
                subprocess.Popen(["open" if os.uname().sysname == "Darwin"
                                  else "xdg-open", path])

        def _open_file(path):
            if os.path.exists(path):
                if os.name == "nt":
                    os.startfile(path)
                else:
                    import subprocess
                    subprocess.Popen(["open" if os.uname().sysname == "Darwin"
                                      else "xdg-open", path])
            else:
                messagebox.showinfo("Not Found",
                                    f"File does not exist yet:\n{path}", parent=self)

        data_dir = get_data_dir()
        r = _row(sec_files)
        ttk.Button(r, text="Open data folder",
                   command=_open_folder, width=20).pack(side="left")
        ttk.Button(r, text="config.json",
                   command=lambda: _open_file(os.path.join(data_dir, "config.json")),
                   width=12).pack(side="left", padx=4)
        ttk.Button(r, text="notes.json",
                   command=lambda: _open_file(os.path.join(data_dir, "notes.json")),
                   width=12).pack(side="left", padx=4)
        ttk.Button(r, text="entity_cache.json",
                   command=lambda: _open_file(get_cache_path()),
                   width=18).pack(side="left", padx=4)

        # ── Diagnostics ──
        sec_diag = _section(outer, "Diagnostics")
        ttk.Button(sec_diag, text="Run diagnostics",
                   command=self._run_diagnostics).pack(anchor="w")
        self._diag_text = tk.Text(sec_diag, height=7, state="disabled",
                                   font=("Consolas", 8), wrap="word",
                                   background="#f5f5f5", relief="flat")
        self._diag_text.pack(fill="x", pady=(4, 0))

    def _refresh_cache_labels(self):
        """Update the size/count labels next to the cache clear buttons."""
        # Entity cache
        entity_path = get_cache_path()
        if os.path.exists(entity_path):
            try:
                import json
                with open(entity_path, encoding="utf-8") as f:
                    count = len(json.load(f))
                self._entity_cache_lbl.config(text=f"{count:,} entries")
            except Exception:
                self._entity_cache_lbl.config(text="(unreadable)")
        else:
            self._entity_cache_lbl.config(text="empty")

        # Tile cache
        tile_path = get_tile_cache_path()
        if os.path.exists(tile_path):
            size_mb = os.path.getsize(tile_path) / (1024 * 1024)
            self._tile_cache_lbl.config(text=f"{size_mb:.1f} MB")
        else:
            self._tile_cache_lbl.config(text="empty")

    def _clear_log_file(self):
        if not messagebox.askyesno(
            "Clear Log File",
            "Delete current app.log contents?",
            parent=self,
        ):
            return
        try:
            applog.clear_log_file()
            self._refresh_log_label()
            messagebox.showinfo("Log Cleared", "app.log was cleared.", parent=self)
        except Exception as exc:
            messagebox.showerror("Log Error", str(exc), parent=self)

    def _refresh_log_label(self):
        size = applog.get_log_size_bytes()
        if size <= 0:
            self._log_size_lbl.config(text="empty")
            return
        self._log_size_lbl.config(text=f"{size / (1024 * 1024):.2f} MB")

    def _run_diagnostics(self):
        self._diag_text.config(state="normal")
        self._diag_text.delete("1.0", "end")
        self._diag_text.insert("end", "Running diagnostics…\n")
        self._diag_text.config(state="disabled")

        q = queue.Queue()

        def _run():
            lines = []

            # Overpass
            try:
                import requests
                r = requests.get(
                    "https://overpass-api.de/api/interpreter",
                    params={"data": "[out:json];out 0;"},
                    timeout=8,
                )
                lines.append(f"✓ Overpass API  ({r.status_code} in {r.elapsed.total_seconds():.2f}s)")
            except Exception as exc:
                lines.append(f"✗ Overpass API  — {exc}")

            # Wikidata
            try:
                import requests
                r = requests.get(
                    "https://www.wikidata.org/w/api.php",
                    params={"action": "wbsearchentities", "search": "test",
                            "language": "en", "format": "json", "limit": 1},
                    timeout=8,
                )
                lines.append(f"✓ Wikidata  ({r.status_code})")
            except Exception as exc:
                lines.append(f"✗ Wikidata  — {exc}")

            # geopy
            try:
                import geopy  # noqa: F401
                lines.append("✓ geopy installed")
            except ImportError:
                lines.append("✗ geopy not installed")

            # AI model
            ready = ai_scoring.is_ai_ready()
            models = ai_scoring.list_models()
            if ready:
                lines.append(f"✓ AI model loaded  ({len(models)} model(s) on disk)")
            elif models:
                lines.append(f"⚠ AI models on disk ({len(models)}) but none loaded in memory")
            else:
                lines.append("✗ AI — no models downloaded")

            # keyring
            if keystore.has_keyring():
                lines.append("✓ keyring — OS keychain available")
            else:
                lines.append("⚠ keyring not available — API keys stored as plaintext")

            q.put("\n".join(lines))

        def _process():
            try:
                result = q.get_nowait()
                if not self.winfo_exists():
                    return
                self._diag_text.config(state="normal")
                self._diag_text.delete("1.0", "end")
                self._diag_text.insert("end", result)
                self._diag_text.config(state="disabled")
            except queue.Empty:
                if self.winfo_exists():
                    self.after(100, _process)

        threading.Thread(target=_run, daemon=True).start()
        _process()

    # ── Apply / Save ──────────────────────────────────────────────────────

    def _apply(self):
        app = self.app
        cfg = app._config

        # ── AI settings ──
        new_model   = self._ai_model_var.get()
        new_weight  = float(self._ai_weight_var.get())
        new_explain = self._ai_explain_var.get()
        new_scoring = self._ai_score_var.get()
        new_max     = max(10, int(self._ai_max_var.get()))
        new_nolimit = self._ai_nolimit_var.get()
        new_debug   = self._debug_var.get()

        app._ai_model            = new_model
        app._ai_weight           = new_weight
        app._ai_explain_on       = new_explain
        app._ai_scoring_on       = new_scoring
        app._ai_max_score        = new_max
        app._ai_disable_max_limit = new_nolimit
        app._ai_debug            = new_debug
        applog.set_debug(new_debug)
        applog.set_file_logging(self._store_logs_var.get())

        if new_debug:
            os.environ["DEBUG"] = "1"
        else:
            os.environ.pop("DEBUG", None)

        if self._verbose_enrich_var.get():
            os.environ["VERBOSE_ENRICHMENT"] = "1"
        else:
            os.environ.pop("VERBOSE_ENRICHMENT", None)

        if self._show_prompts_var.get():
            os.environ["SHOW_AI_PROMPTS"] = "1"
        else:
            os.environ.pop("SHOW_AI_PROMPTS", None)

        # Reload model if it changed or wasn't loaded
        if not ai_scoring.is_ai_ready() or new_model != getattr(app, "_ai_model", ""):
            running = ai_scoring.load_default_model(new_model)
            if not running:
                for candidate in ai_scoring.list_models():
                    if ai_scoring.load_default_model(candidate):
                        running = True
                        app._ai_model = candidate
                        break
            app._ai_running = running

        if hasattr(app, "_sidebar"):
            app._sidebar.set_ai_status(app._ai_running)
            app._sidebar.ai_scoring_var.set(new_scoring)

        # ── Data source API keys ──
        gp_key = self._gp_key_var.get().strip()
        yl_key = self._yelp_key_var.get().strip()
        keystore.set_key("google_places", gp_key)
        keystore.set_key("yelp", yl_key)

        cfg.setdefault("data_sources", {})
        cfg["data_sources"]["google_places_enabled"] = self._gp_enabled_var.get()
        cfg["data_sources"]["yelp_enabled"]          = self._yelp_enabled_var.get()
        # Mirror keys in config for non-keyring fallback path
        cfg.setdefault("api_keys", {})
        if not keystore.has_keyring():
            cfg["api_keys"]["google_places"] = gp_key
            cfg["api_keys"]["yelp"]          = yl_key

        # ── Search settings ──
        new_max_results = max(50, min(2000, int(self._max_results_var.get())))
        new_radius      = max(0.5, min(25.0, float(self._radius_var.get())))
        new_timeout     = max(10, min(180, int(self._timeout_var.get())))
        new_workers     = max(1, min(20, int(self._workers_var.get())))

        if hasattr(app, "_max_results_limit"):
            app._max_results_limit = new_max_results
            if hasattr(app, "_max_results_var"):
                app._max_results_var.set(new_max_results)
            if hasattr(app, "_max_results_label"):
                app._max_results_label.config(text=str(new_max_results))

        if hasattr(app, "_search_radius"):
            app._search_radius = new_radius
            if hasattr(app, "_radius_var"):
                app._radius_var.set(new_radius)

        cfg["last_max_results"] = new_max_results
        cfg["last_radius_miles"] = new_radius
        cfg.setdefault("search_settings", {})
        cfg["search_settings"]["overpass_timeout"]      = new_timeout
        cfg["search_settings"]["max_enrichment_workers"] = new_workers

        # ── AI settings in config ──
        cfg["ai_settings"] = {
            "model":            app._ai_model,
            "weight":           app._ai_weight,
            "explain_on":       app._ai_explain_on,
            "scoring_on":       app._ai_scoring_on,
            "max_score":        app._ai_max_score,
            "disable_max_limit": app._ai_disable_max_limit,
            "debug_mode":       app._ai_debug,
        }

        # ── Debug settings in config ──
        cfg.setdefault("debug_settings", {})
        cfg["debug_settings"]["verbose_enrichment"] = self._verbose_enrich_var.get()
        cfg["debug_settings"]["show_ai_prompts"]    = self._show_prompts_var.get()
        cfg["debug_settings"]["store_logs"]         = self._store_logs_var.get()

        if hasattr(app, "_set_status"):
            app._set_status("Settings applied.")

    def _save(self):
        self._apply()
        save_config(self.app._config)
        if hasattr(self.app, "_set_status"):
            self.app._set_status("Settings saved.")
        self.destroy()
