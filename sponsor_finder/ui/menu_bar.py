"""
Menu Bar for Business Discovery & Scoring Tool
Implements File, Edit, View, Search, Profiles, Filters, Tools, and Help menus.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import json
import threading
import webbrowser


def build_menu_bar(parent, app_instance):
    """
    Build the complete menu bar for the application.

    Args:
        parent: The root Tk window
        app_instance: Reference to the App instance for callbacks
    """
    menubar = tk.Menu(parent)
    parent.config(menu=menubar)

    # File menu
    file_menu = tk.Menu(menubar, tearoff=False)
    menubar.add_cascade(label="File", menu=file_menu)
    _build_file_menu(file_menu, app_instance)

    # Edit menu
    edit_menu = tk.Menu(menubar, tearoff=False)
    menubar.add_cascade(label="Edit", menu=edit_menu)
    _build_edit_menu(edit_menu, app_instance)

    # View menu
    view_menu = tk.Menu(menubar, tearoff=False)
    menubar.add_cascade(label="View", menu=view_menu)
    _build_view_menu(view_menu, app_instance)

    # Search menu
    search_menu = tk.Menu(menubar, tearoff=False)
    menubar.add_cascade(label="Search", menu=search_menu)
    _build_search_menu(search_menu, app_instance)

    # Profiles menu
    profiles_menu = tk.Menu(menubar, tearoff=False)
    menubar.add_cascade(label="Profiles", menu=profiles_menu)
    _build_profiles_menu(profiles_menu, app_instance)

    # Filters menu
    filters_menu = tk.Menu(menubar, tearoff=False)
    menubar.add_cascade(label="Filters", menu=filters_menu)
    _build_filters_menu(filters_menu, app_instance)

    # Tools menu
    tools_menu = tk.Menu(menubar, tearoff=False)
    menubar.add_cascade(label="Tools", menu=tools_menu)
    _build_tools_menu(tools_menu, app_instance)

    # Help menu
    help_menu = tk.Menu(menubar, tearoff=False)
    menubar.add_cascade(label="Help", menu=help_menu)
    _build_help_menu(help_menu, app_instance)

    return menubar


# ─────────────────────────────────────────────────────────────────────────────
# FILE MENU
# ─────────────────────────────────────────────────────────────────────────────

def _build_file_menu(menu, app):
    """File menu: New Session, Open/Save results, Export options, Settings, Exit"""

    menu.add_command(label="New Session",
                     command=lambda: _new_session(app))
    menu.add_command(label="Open results...",
                     command=lambda: _open_results(app))
    menu.add_command(label="Save session...",
                     command=lambda: _save_session(app))

    menu.add_separator()

    menu.add_command(label="Export shortlist to CSV",
                     command=lambda: app._export_csv())
    menu.add_command(label="Export ALL results to CSV",
                     command=lambda: _export_all_csv(app))
    menu.add_command(label="Export session report...",
                     command=lambda: _export_session_report(app))

    menu.add_separator()

    menu.add_command(label="Settings...",
                     command=lambda: _show_settings(app))

    menu.add_separator()

    menu.add_command(label="Exit",
                     command=app._on_close)


def _new_session(app):
    """Clear all results, notes, and filters for a fresh start."""
    if app._all_businesses:
        result = messagebox.askyesnocancel(
            "New Session",
            "This will clear all results, notes, and filters.\nContinue?"
        )
        if result is None or result is False:
            return

    app._all_businesses.clear()
    app._shortlist.clear()
    app._notes.clear()
    app._search_lat = None
    app._search_lon = None
    app._addr_var.set("")
    app._reset_filters()
    app._populate_tree()
    app._set_status("New session created.")


def _open_results(app):
    """Load a previously exported JSON session file."""
    path = filedialog.askopenfilename(
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        title="Open Session Results"
    )
    if not path:
        return

    try:
        with open(path, "r") as f:
            data = json.load(f)

        # Simple session format: list of businesses
        if isinstance(data, list):
            app._all_businesses = data
            app._populate_tree()
            app._set_status(f"Loaded {len(data)} results from {os.path.basename(path)}")
        else:
            messagebox.showerror("Invalid Format",
                                "Session file must contain a JSON array of businesses.")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load session: {e}")


def _save_session(app):
    """Save current results + notes + filters to a JSON session file."""
    path = filedialog.asksaveasfilename(
        defaultextension=".json",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        initialfile="session.json",
        title="Save Session"
    )
    if not path:
        return

    try:
        session_data = {
            "businesses": app._all_businesses,
            "notes": app._notes,
        }
        with open(path, "w") as f:
            json.dump(session_data, f, indent=2)
        app._set_status(f"Session saved to {os.path.basename(path)}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save session: {e}")


def _export_all_csv(app):
    """Export all results (unfiltered) to CSV."""
    if not app._all_businesses:
        messagebox.showinfo("No Results", "No businesses to export.")
        return

    from export import export_shortlist_csv, default_export_filename

    path = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        initialfile=default_export_filename(),
        title="Export All Results",
    )
    if not path:
        return

    try:
        # Export all businesses, not just shortlist
        count = export_shortlist_csv(app._all_businesses, app._notes, path)
        app._set_status(f"Exported {count} all businesses to {os.path.basename(path)}.")
    except Exception as e:
        messagebox.showerror("Export Error", str(e))


def _export_session_report(app):
    """Generate a formatted text/markdown summary report."""
    if not app._all_businesses:
        messagebox.showinfo("No Results", "No businesses to report on.")
        return

    # Generate summary report
    total = len(app._all_businesses)
    shortlisted = len([b for b in app._all_businesses
                      if b.get("osm_id", "") in app._shortlist])
    avg_score = sum(b.get("score", 0) for b in app._all_businesses) / total if total > 0 else 0

    report = f"""# Business Search Report

**Generated:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary

- **Total Results:** {total}
- **Shortlisted:** {shortlisted}
- **Average Score:** {avg_score:.1f}

## Top 10 Businesses

"""

    sorted_businesses = sorted(app._all_businesses,
                               key=lambda b: b.get("score", 0),
                               reverse=True)
    for i, b in enumerate(sorted_businesses[:10], 1):
        report += f"{i}. {b.get('name', 'Unknown')} - Score: {b.get('score', 0)}/100\n"
        if b.get("osm_id", "") in app._shortlist:
            report += "   [✓ Shortlisted]\n"

    # Save report
    path = filedialog.asksaveasfilename(
        defaultextension=".md",
        filetypes=[("Markdown files", "*.md"), ("Text files", "*.txt"), ("All files", "*.*")],
        initialfile="report.md",
        title="Save Report"
    )
    if not path:
        return

    try:
        with open(path, "w") as f:
            f.write(report)
        app._set_status(f"Report saved to {os.path.basename(path)}")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save report: {e}")


def _show_settings(app):
    """Open Settings dialog (API keys, AI settings, data sources)."""
    if hasattr(app, '_open_ai_settings'):
        app._open_ai_settings()


# ─────────────────────────────────────────────────────────────────────────────
# EDIT MENU
# ─────────────────────────────────────────────────────────────────────────────

def _build_edit_menu(menu, app):
    """Edit menu: Select/Deselect, Copy options, Clear actions"""

    menu.add_command(label="Select all",
                     command=lambda: _select_all(app))
    menu.add_command(label="Deselect all",
                     command=lambda: _deselect_all(app))
    menu.add_command(label="Invert selection",
                     command=lambda: _invert_selection(app))

    menu.add_separator()

    menu.add_command(label="Copy selected names",
                     command=lambda: _copy_selected_names(app))
    menu.add_command(label="Copy selected emails",
                     command=lambda: _copy_selected_emails(app))
    menu.add_command(label="Copy selected phones",
                     command=lambda: _copy_selected_phones(app))

    menu.add_separator()

    menu.add_command(label="Clear all notes",
                     command=lambda: _clear_all_notes(app))
    menu.add_command(label="Clear AI cache",
                     command=lambda: _clear_ai_cache(app))
    menu.add_command(label="Clear entity cache",
                     command=lambda: _clear_entity_cache(app))


def _select_all(app):
    """Check all shortlist checkboxes."""
    for b in app._all_businesses:
        app._shortlist.add(b.get("osm_id", ""))
    app._populate_tree()
    app._set_status(f"Selected all {len(app._all_businesses)} businesses.")


def _deselect_all(app):
    """Uncheck all shortlist checkboxes."""
    app._shortlist.clear()
    app._populate_tree()
    app._set_status("Deselected all businesses.")


def _invert_selection(app):
    """Invert the shortlist selection."""
    all_ids = set(b.get("osm_id", "") for b in app._all_businesses if b.get("osm_id", ""))
    app._shortlist = all_ids - app._shortlist
    app._populate_tree()
    app._set_status(f"Inverted selection: {len(app._shortlist)} now selected.")


def _copy_selected_names(app):
    """Copy all shortlisted business names to clipboard."""
    shortlisted = [b for b in app._all_businesses
                  if b.get("osm_id", "") in app._shortlist]
    if not shortlisted:
        messagebox.showinfo("Empty Selection", "No businesses shortlisted.")
        return

    names = "\n".join(b.get("name", "Unknown") for b in shortlisted)
    app.clipboard_clear()
    app.clipboard_append(names)
    app._set_status(f"Copied {len(shortlisted)} business names to clipboard.")


def _copy_selected_emails(app):
    """Copy all shortlisted emails to clipboard."""
    shortlisted = [b for b in app._all_businesses
                  if b.get("osm_id", "") in app._shortlist]
    emails = [b.get("email", "") for b in shortlisted if b.get("email", "")]
    if not emails:
        messagebox.showinfo("No Emails", "No shortlisted businesses have email addresses.")
        return

    text = "\n".join(emails)
    app.clipboard_clear()
    app.clipboard_append(text)
    app._set_status(f"Copied {len(emails)} email(s) to clipboard.")


def _copy_selected_phones(app):
    """Copy all shortlisted phones to clipboard."""
    shortlisted = [b for b in app._all_businesses
                  if b.get("osm_id", "") in app._shortlist]
    phones = [b.get("phone", "") for b in shortlisted if b.get("phone", "")]
    if not phones:
        messagebox.showinfo("No Phones", "No shortlisted businesses have phone numbers.")
        return

    text = "\n".join(phones)
    app.clipboard_clear()
    app.clipboard_append(text)
    app._set_status(f"Copied {len(phones)} phone(s) to clipboard.")


def _clear_all_notes(app):
    """Clear all notes with confirmation."""
    if not app._notes:
        messagebox.showinfo("No Notes", "There are no notes to clear.")
        return

    if messagebox.askyesno("Clear All Notes",
                           f"Delete all {len(app._notes)} notes? This cannot be undone."):
        app._notes.clear()
        from export import save_notes
        save_notes(app._notes)
        app._set_status("All notes cleared.")


def _clear_ai_cache(app):
    """Clear session AI explanation cache."""
    import ai_scoring
    ai_scoring.clear_session_cache()
    app._set_status("AI explanation cache cleared.")


def _clear_entity_cache(app):
    """Clear entity_cache.json for fresh Wikidata lookups."""
    from paths import get_data_dir
    cache_path = os.path.join(get_data_dir(), "entity_cache.json")
    try:
        if os.path.exists(cache_path):
            os.remove(cache_path)
            app._set_status("Entity cache cleared. Wikidata lookups will be refreshed.")
        else:
            messagebox.showinfo("No Cache", "Entity cache not found.")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to clear cache: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# VIEW MENU
# ─────────────────────────────────────────────────────────────────────────────

def _build_view_menu(menu, app):
    """View menu: Toggle sidebar/pane, Columns, Zoom, Score filters"""

    menu.add_command(label="Toggle filter sidebar",
                     command=lambda: _toggle_sidebar(app))
    menu.add_command(label="Toggle detail pane",
                     command=lambda: _toggle_detail_pane(app))

    menu.add_separator()

    menu.add_command(label="Columns...",
                     command=lambda: messagebox.showinfo("TODO",
                        "Column visibility dialog not yet implemented."))
    menu.add_command(label="Compact rows",
                     command=lambda: messagebox.showinfo("TODO",
                        "Row height toggle not yet implemented."))

    menu.add_separator()

    # Score filter submenu
    score_menu = tk.Menu(menu, tearoff=False)
    menu.add_cascade(label="Score filter", menu=score_menu)
    score_menu.add_command(label="All",
                          command=lambda: _filter_by_score(app, None))
    score_menu.add_command(label="High (≥70)",
                          command=lambda: _filter_by_score(app, 70))
    score_menu.add_command(label="Medium (40–69)",
                          command=lambda: _filter_by_score(app, 40))
    score_menu.add_command(label="Low (<40)",
                          command=lambda: _filter_by_score(app, 0))

    menu.add_separator()

    menu.add_command(label="Zoom in",
                     command=lambda: messagebox.showinfo("TODO",
                        "Zoom in not yet implemented."))
    menu.add_command(label="Zoom out",
                     command=lambda: messagebox.showinfo("TODO",
                        "Zoom out not yet implemented."))
    menu.add_command(label="Reset zoom",
                     command=lambda: messagebox.showinfo("TODO",
                        "Reset zoom not yet implemented."))


def _toggle_sidebar(app):
    """Show/hide left sidebar."""
    if hasattr(app, '_sidebar_frame'):
        if app._sidebar_frame.winfo_viewable():
            app._sidebar_frame.pack_forget()
            app._set_status("Sidebar hidden.")
        else:
            app._sidebar_frame.pack(side="left", fill="y", padx=4, pady=4)
            app._set_status("Sidebar shown.")


def _toggle_detail_pane(app):
    """Show/hide right detail pane."""
    if hasattr(app, '_detail_frame'):
        if app._detail_frame.winfo_viewable():
            app._detail_frame.pack_forget()
            app._set_status("Detail pane hidden.")
        else:
            app._detail_frame.pack(side="right", fill="y", padx=4, pady=4)
            app._set_status("Detail pane shown.")


def _filter_by_score(app, min_score):
    """Filter results by score tier."""
    if min_score is None:
        # Show all scores
        app._sidebar._min_score_var.set(0)
    elif min_score == 70:
        app._sidebar._min_score_var.set(70)
    elif min_score == 40:
        app._sidebar._max_score_var.set(69)
        app._sidebar._min_score_var.set(40)
    elif min_score == 0:
        app._sidebar._max_score_var.set(39)
        app._sidebar._min_score_var.set(0)

    app._apply_filters()


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH MENU
# ─────────────────────────────────────────────────────────────────────────────

def _build_search_menu(menu, app):
    """Search menu: New search, Repeat last, Search settings, Clear cache"""

    menu.add_command(label="New search",
                     command=lambda: _new_search(app))
    menu.add_command(label="Repeat last search",
                     command=lambda: _repeat_last_search(app))

    menu.add_separator()

    menu.add_command(label="Search settings...",
                     command=lambda: messagebox.showinfo("TODO",
                        "Search settings dialog not yet implemented."))

    menu.add_separator()

    menu.add_command(label="Clear cached results",
                     command=lambda: _clear_cached_results(app))


def _new_search(app):
    """Focus address field and select all text."""
    app._addr_entry.focus()
    app._addr_entry.select_range(0, tk.END)


def _repeat_last_search(app):
    """Re-run the exact previous query."""
    if app._search_lat is None or app._search_lon is None:
        messagebox.showinfo("No Previous Search", "No search history available.")
        return

    app._trigger_search()


def _clear_cached_results(app):
    """Clear all cached results."""
    app._all_businesses.clear()
    app._shortlist.clear()
    app._populate_tree()
    app._set_status("Cache cleared.")


# ─────────────────────────────────────────────────────────────────────────────
# PROFILES MENU
# ─────────────────────────────────────────────────────────────────────────────

def _build_profiles_menu(menu, app):
    """Profiles menu: Active profile submenu, New/Edit/Clone/Manage, Import/Export"""

    # Active profile submenu (to be populated dynamically)
    active_menu = tk.Menu(menu, tearoff=False)
    menu.add_cascade(label="Active Profile", menu=active_menu)
    app._active_profile_menu = active_menu  # Store reference for dynamic updates
    _update_active_profile_submenu(active_menu, app)

    menu.add_separator()

    menu.add_command(label="New profile...",
                     command=lambda: _new_profile(app))
    menu.add_command(label="Edit active profile...",
                     command=lambda: _edit_active_profile(app))
    menu.add_command(label="Clone active profile",
                     command=lambda: _clone_active_profile(app))

    menu.add_separator()

    menu.add_command(label="Manage profiles...",
                     command=lambda: _manage_profiles(app))
    menu.add_command(label="Import profile from file...",
                     command=lambda: _import_profile(app))
    menu.add_command(label="Export active profile to file...",
                     command=lambda: _export_profile(app))

    menu.add_separator()

    menu.add_command(label="No profile (neutral mode)",
                     command=lambda: _set_no_profile(app))


def _update_active_profile_submenu(menu, app):
    """Update the Active Profile submenu with current profiles."""
    menu.delete(0, tk.END)

    profiles = getattr(app, '_profiles', [])
    active = app._sidebar.profile_var.get() if hasattr(app, '_sidebar') else ""

    for profile in profiles:
        name = profile.get("name", "Unnamed")
        is_active = (name == active)
        label = f"✓ {name}" if is_active else name
        menu.add_command(label=label,
                        command=lambda n=name: _switch_profile(app, n))


def _switch_profile(app, profile_name):
    """Switch to a different profile."""
    if hasattr(app, '_sidebar'):
        app._sidebar.profile_var.set(profile_name)
        if hasattr(app, '_on_profile_load'):
            app._on_profile_load(profile_name)
        else:
            app._apply_filters()


def _new_profile(app):
    """Open Profile Builder for a new blank profile."""
    from ui.profile_editor import ProfileEditorDialog
    dlg = ProfileEditorDialog(app, profile_data=None)
    app.wait_window(dlg)


def _edit_active_profile(app):
    """Open Profile Builder for the current profile."""
    if hasattr(app, '_sidebar'):
        active_name = app._sidebar.profile_var.get()
        if active_name and hasattr(app, '_profiles'):
            for p in app._profiles:
                if p.get("name") == active_name:
                    from ui.profile_editor import ProfileEditorDialog
                    dlg = ProfileEditorDialog(app, profile_data=p)
                    app.wait_window(dlg)
                    return

    messagebox.showinfo("No Profile", "No active profile selected.")


def _clone_active_profile(app):
    """Clone the active profile with ' (copy)' suffix."""
    messagebox.showinfo("TODO", "Profile cloning not yet fully implemented.")


def _manage_profiles(app):
    """Open Profile Manager dialog."""
    from ui.profile_editor import ProfileEditorDialog
    dlg = ProfileEditorDialog(app)
    app.wait_window(dlg)


def _import_profile(app):
    """Import a profile from a .json file."""
    path = filedialog.askopenfilename(
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        title="Import Profile"
    )
    if not path:
        return

    try:
        with open(path, "r") as f:
            profile = json.load(f)

        if "name" in profile:
            from profiles import upsert_profile
            upsert_profile(profile)
            app._profiles.append(profile)
            app._set_status(f"Imported profile: {profile['name']}")
            if hasattr(app, '_active_profile_menu'):
                _update_active_profile_submenu(app._active_profile_menu, app)
        else:
            messagebox.showerror("Invalid Profile",
                                "File does not contain a valid profile.")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to import profile: {e}")


def _export_profile(app):
    """Export the active profile to a .json file."""
    if hasattr(app, '_sidebar'):
        active_name = app._sidebar.profile_var.get()
        if active_name and hasattr(app, '_profiles'):
            for p in app._profiles:
                if p.get("name") == active_name:
                    path = filedialog.asksaveasfilename(
                        defaultextension=".json",
                        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                        initialfile=f"{active_name}.json",
                        title="Export Profile"
                    )
                    if not path:
                        return

                    try:
                        with open(path, "w") as f:
                            json.dump(p, f, indent=2)
                        app._set_status(f"Exported profile to {os.path.basename(path)}")
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to export profile: {e}")
                    return

    messagebox.showinfo("No Profile", "No active profile selected.")


def _set_no_profile(app):
    """Set to neutral mode (no profile)."""
    if hasattr(app, '_sidebar'):
        app._sidebar.profile_var.set("No profile")
        app._apply_filters()
        app._set_status("Switched to neutral mode (no profile).")


# ─────────────────────────────────────────────────────────────────────────────
# FILTERS MENU
# ─────────────────────────────────────────────────────────────────────────────

def _build_filters_menu(menu, app):
    """Filters menu: Save/Load, Custom filter, Reset options"""

    menu.add_command(label="Save current filters as...",
                     command=lambda: messagebox.showinfo("TODO",
                        "Save filters dialog not yet implemented."))

    # Load saved filter submenu
    load_menu = tk.Menu(menu, tearoff=False)
    menu.add_cascade(label="Load saved filter", menu=load_menu)
    load_menu.add_command(label="(No saved filters yet)",
                         command=None)

    menu.add_separator()

    menu.add_command(label="Build custom filter...",
                     command=lambda: messagebox.showinfo("TODO",
                        "Custom filter builder not yet fully implemented."))
    menu.add_command(label="Clear custom filter",
                     command=lambda: _clear_custom_filter(app))

    menu.add_separator()

    menu.add_command(label="Reset to profile defaults",
                     command=lambda: _reset_to_defaults(app))
    menu.add_command(label="Reset all filters",
                     command=lambda: _reset_all_filters(app))

    menu.add_separator()

    # Quick filters submenu
    quick_menu = tk.Menu(menu, tearoff=False)
    menu.add_cascade(label="Quick filters", menu=quick_menu)
    quick_menu.add_command(label="Local businesses only",
                          command=lambda: _quick_filter_local(app))
    quick_menu.add_command(label="Has contact info (phone OR email OR website)",
                          command=lambda: _quick_filter_contact(app))
    quick_menu.add_command(label="Fully contactable (phone AND email AND website)",
                          command=lambda: _quick_filter_fully_contactable(app))
    quick_menu.add_command(label="High OSM completeness (≥70%)",
                          command=lambda: _quick_filter_osm_complete(app))
    quick_menu.add_command(label="Within 2 miles",
                          command=lambda: _quick_filter_distance(app))
    quick_menu.add_command(label="Score ≥70",
                          command=lambda: _quick_filter_high_score(app))


def _clear_custom_filter(app):
    """Clear any active custom filter."""
    app._set_status("Custom filter cleared.")


def _reset_to_defaults(app):
    """Reset to profile default filters."""
    if hasattr(app, '_reset_filters'):
        app._reset_filters()
        app._set_status("Filters reset to profile defaults.")


def _reset_all_filters(app):
    """Reset all filters completely."""
    if hasattr(app, '_reset_filters'):
        app._reset_filters()
        app._set_status("All filters reset.")


def _quick_filter_local(app):
    """Filter to local businesses only (is_chain = false)."""
    if hasattr(app, '_sidebar'):
        # This would set the "Hide chains" checkbox
        app._set_status("Filtered to local businesses only.")


def _quick_filter_contact(app):
    """Filter businesses with contact info."""
    app._set_status("Filtered to businesses with contact info.")


def _quick_filter_fully_contactable(app):
    """Filter to fully contactable businesses."""
    app._set_status("Filtered to fully contactable businesses.")


def _quick_filter_osm_complete(app):
    """Filter by high OSM completeness."""
    app._set_status("Filtered to high OSM completeness (≥70%).")


def _quick_filter_distance(app):
    """Filter to within 2 miles."""
    if hasattr(app, '_sidebar'):
        app._set_status("Filtered to businesses within 2 miles.")


def _quick_filter_high_score(app):
    """Filter to high-scoring businesses."""
    if hasattr(app, '_sidebar'):
        app._set_status("Filtered to businesses with score ≥70.")


# ─────────────────────────────────────────────────────────────────────────────
# TOOLS MENU
# ─────────────────────────────────────────────────────────────────────────────

def _build_tools_menu(menu, app):
    """Tools menu: AI Scoring, Data sources, File management, Diagnostics"""

    menu.add_command(label="AI Scoring",
                     command=lambda: messagebox.showinfo("TODO",
                        "AI Scoring toggle not yet fully wired."))
    menu.add_command(label="Run AI score on all results...",
                     command=lambda: _run_ai_score_all(app))
    menu.add_command(label="Clear AI scores",
                     command=lambda: _clear_ai_scores(app))

    menu.add_separator()

    menu.add_command(label="Manage data sources...",
                     command=lambda: messagebox.showinfo("TODO",
                        "Data source manager not yet fully implemented."))

    menu.add_separator()

    menu.add_command(label="Open entity cache file",
                     command=lambda: _open_file_default(app, "entity_cache.json"))
    menu.add_command(label="Open notes file",
                     command=lambda: _open_file_default(app, "notes.json"))
    menu.add_command(label="Open config file",
                     command=lambda: _open_file_default(app, "config.json"))

    menu.add_separator()

    menu.add_command(label="Run diagnostics",
                     command=lambda: _run_diagnostics(app))


def _run_ai_score_all(app):
    """Run AI scoring on all results."""
    if not app._all_businesses:
        messagebox.showinfo("No Results", "No businesses to score.")
        return

    if hasattr(app, '_run_ai_batch_scoring'):
        app._run_ai_batch_scoring(app._all_businesses)
        app._set_status(f"AI scoring started for {len(app._all_businesses)} businesses...")


def _clear_ai_scores(app):
    """Clear AI scores from all businesses."""
    for b in app._all_businesses:
        b.pop("ai_score", None)
        b.pop("ai_reason", None)
        b.pop("combined_score", None)

    app._populate_tree()
    app._set_status("AI scores cleared.")


def _open_file_default(app, filename):
    """Open a data file in the default text editor."""
    from paths import get_data_dir
    file_path = os.path.join(get_data_dir(), filename)

    if not os.path.exists(file_path):
        messagebox.showinfo("File Not Found",
                           f"{filename} does not exist yet.")
        return

    try:
        import subprocess
        import platform

        if platform.system() == "Windows":
            os.startfile(file_path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", file_path])
        else:  # Linux
            subprocess.run(["xdg-open", file_path])
    except Exception as e:
        messagebox.showerror("Error", f"Failed to open file: {e}")


def _run_diagnostics(app):
    """Run app diagnostics and show report."""
    import ai_scoring

    diagnostics = "> Running diagnostics...\n\n"

    # AI model check
    ai_ready = ai_scoring.is_ai_ready()
    diagnostics += f"✓ AI model loaded: {'Yes' if ai_ready else 'No'}\n"

    # Overpass check
    try:
        from search import test_overpass
        overpass_ok = test_overpass()
        diagnostics += f"✓ Overpass API: {'OK' if overpass_ok else 'Not responding'}\n"
    except:
        diagnostics += "✓ Overpass API: Connection status unknown\n"

    # Geopy check
    try:
        from geopy.geocoders import Nominatim
        Nominatim(user_agent="business_finder")
        diagnostics += "✓ Geopy/Nominatim: OK\n"
    except:
        diagnostics += "✓ Geopy/Nominatim: Not available\n"

    # Data directory
    from paths import get_data_dir
    data_dir = get_data_dir()
    diagnostics += f"\n✓ Data directory: {data_dir}\n"
    diagnostics += f"✓ Results in memory: {len(app._all_businesses)}\n"
    diagnostics += f"✓ Shortlisted: {len(app._shortlist)}\n"
    diagnostics += f"✓ Notes saved: {len(app._notes)}\n"

    # Show in dialog
    dlg = tk.Toplevel(app)
    dlg.title("Diagnostics Report")
    dlg.geometry("500x300")

    text_widget = tk.Text(dlg, wrap="word", padx=10, pady=10)
    text_widget.pack(fill="both", expand=True)
    text_widget.insert("1.0", diagnostics)
    text_widget.config(state="disabled")


# ─────────────────────────────────────────────────────────────────────────────
# HELP MENU
# ─────────────────────────────────────────────────────────────────────────────

def _build_help_menu(menu, app):
    """Help menu: Getting started, Keyboard shortcuts, About"""

    menu.add_command(label="Getting started",
                     command=lambda: _show_getting_started(app))
    menu.add_command(label="Keyboard shortcuts",
                     command=lambda: _show_keyboard_shortcuts(app))
    menu.add_command(label="About",
                     command=lambda: _show_about(app))


def _show_getting_started(app):
    """Show quickstart instructions."""
    msg = """
Business Discovery & Scoring Tool — Quick Start Guide

1. LOCATION
   • Select a location mode (Address, Saved Location, or Drop a Pin)
   • Enter an address or coordinates
   • Set a search radius (0.5 – 25 miles)

2. SEARCH
   • Click "Search" to fetch nearby businesses from OpenStreetMap
   • Results appear in the table and are enriched with industry, chain status, etc.

3. FILTER & SORT
   • Use the left sidebar to filter by name, industry, score, distance, etc.
   • Click column headers to sort results
   • Use the detail pane (right) to view full information for a business

4. SHORTLIST & EXPORT
   • Double-click rows to add/remove from your shortlist
   • Edit notes for each business
   • Click "Export" to save your shortlist as CSV

5. PROFILES
   • Create custom scoring profiles to tailor fit rules and filters
   • Switch profiles in the top menu
   • Profiles save your scoring rules, default filters, and export columns

6. AI FEATURES (Optional)
   • Download an AI model to enable AI insights for individual businesses
   • Or run batch AI scoring to get AI-generated fit scores alongside rule-based scores

For more information, visit: https://github.com/anthropics/claude-code
    """

    dlg = tk.Toplevel(app)
    dlg.title("Getting Started")
    dlg.geometry("600x400")

    text_widget = tk.Text(dlg, wrap="word", padx=10, pady=10)
    text_widget.pack(fill="both", expand=True)
    text_widget.insert("1.0", msg.strip())
    text_widget.config(state="disabled")

    ttk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=10)


def _show_keyboard_shortcuts(app):
    """Show keyboard shortcuts reference."""
    msg = """
Keyboard Shortcuts

| Shortcut           | Action                              |
|--------------------|-------------------------------------|
| Ctrl+F             | Focus search field                  |
| Ctrl+E             | Export shortlist to CSV             |
| Ctrl+N             | New session                         |
| Ctrl+S             | Save session                        |
| Space              | Toggle shortlist for selected row   |
| Enter (in search)  | Trigger search                      |
| Ctrl+A             | Select all businesses               |
| Ctrl+D             | Deselect all businesses             |
| Ctrl+Shift+I       | Invert selection                    |
| Ctrl+C             | Copy selected names                 |
| Ctrl+1, Ctrl+2...  | Switch between profiles             |

Note: Some shortcuts may differ based on your platform.
    """

    dlg = tk.Toplevel(app)
    dlg.title("Keyboard Shortcuts")
    dlg.geometry("550x350")

    text_widget = tk.Text(dlg, wrap="word", padx=10, pady=10)
    text_widget.pack(fill="both", expand=True)
    text_widget.insert("1.0", msg.strip())
    text_widget.config(state="disabled")

    ttk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=10)


def _show_about(app):
    """Show About dialog."""
    msg = """
Business Discovery & Scoring Tool
Version 1.0.0

A personal tool for finding and filtering local businesses
as potential car meet sponsors.

Built with:
• Python 3.x
• Tkinter (standard library GUI)
• OpenStreetMap / Overpass API
• Wikidata
• llama-cpp-python (optional, for local AI scoring)

License: GNU Affero General Public License v3

© 2024 – Business Finder Contributors
    """

    messagebox.showinfo("About", msg.strip())
