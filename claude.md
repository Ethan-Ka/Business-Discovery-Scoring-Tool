Build a Python desktop app using Tkinter called "Business Discovery & Scoring Tool" — a personal tool for finding and filtering local businesses as potential car meet sponsors.

---

# TECH STACK

- Python 3.x
- Tkinter + ttk (standard library GUI only)
- requests (HTTP)
- geopy (Nominatim geocoding)
- concurrent.futures (async enrichment)
- csv, json, math, threading, os (standard library)
- No API keys required for core functionality

---

## PROJECT STRUCTURE

```
business_finder/
├── main.py                  # Entry point, root window, layout manager
├── search.py                # Overpass query builder and fetcher
├── enrichment.py            # Entity intelligence pipeline
├── scoring.py               # Rule-based score engine
├── filters.py               # Filter/sort logic
├── export.py                # CSV export, notes persistence
├── profile_manager.py       # Profile load/save/switch logic
├── source_manager.py        # Pluggable data source interface
├── ui/
│   ├── main_window.py       # Top bar, layout frame, status bar
│   ├── menu_bar.py          # Full application menu bar
│   ├── results_table.py     # ttk.Treeview results panel
│   ├── filter_sidebar.py    # Left sidebar filters
│   ├── detail_pane.py       # Right detail panel (on row select)
│   ├── profile_editor.py    # Full profile create/edit UI
│   ├── rule_builder.py      # Scoring rule visual editor
│   └── source_settings.py   # Data source manager UI
├── sources/
│   ├── base.py              # Abstract source interface
│   ├── overpass.py          # OSM/Overpass (always enabled)
│   ├── wikidata.py          # Wikidata enrichment (always enabled)
│   ├── google_places.py     # Optional, requires API key
│   └── yelp.py              # Optional, requires API key
├── profiles/
│   ├── car_meet_sponsor.json
│   └── general_outreach.json
├── config.json              # App-level prefs, saved location, API keys (auto-created)
├── notes.json               # Per-business notes keyed by OSM node ID (auto-created)
├── filters.json             # Saved named filter sets (auto-created)
└── entity_cache.json        # Wikidata lookup cache (auto-created)
```

---

## PROFILE SYSTEM

### What a Profile Is

A profile is a `.json` file in the `profiles/` folder. It defines everything domain-specific:
scoring rules, default filters, audience keywords, export columns, and which data sources to use.
The core app engine never has hardcoded business logic — it all comes from the active profile.

### Profile JSON Schema

```json
{
  "name": "Car Meet Sponsor",
  "description": "Find local businesses likely to sponsor a car meet or car club",
  "scoring_rules": [
    { "field": "industry", "operator": "=", "value": "Auto Parts", "points": 30 },
    { "field": "industry", "operator": "=", "value": "Car Wash", "points": 28 },
    { "field": "industry", "operator": "=", "value": "Tire Shop", "points": 26 },
    { "field": "industry", "operator": "=", "value": "Performance Shop", "points": 30 },
    { "field": "industry", "operator": "=", "value": "Detailing", "points": 28 },
    { "field": "is_chain", "operator": "=", "value": false, "points": 20 },
    { "field": "has_website", "operator": "=", "value": true, "points": 10 },
    { "field": "has_phone", "operator": "=", "value": true, "points": 10 },
    { "field": "distance_mi", "operator": "<", "value": 2, "points": 15 },
    { "field": "distance_mi", "operator": "<", "value": 5, "points": 10 },
    { "field": "distance_mi", "operator": "<", "value": 10, "points": 5 },
    { "field": "audience_overlap", "operator": "contains", "value": "car", "points": 15 },
    { "field": "num_locations", "operator": "<", "value": 5, "points": 10 }
  ],
  "audience_keywords": ["car", "automotive", "enthusiast", "mechanic", "racing", "performance"],
  "default_filters": {
    "hide_chains": true,
    "min_score": 30,
    "category": "All"
  },
  "export_columns": ["Name", "Score", "Industry", "Chain", "Phone", "Email", "Website", "Address", "Audience", "Notes"],
  "data_sources": ["overpass", "wikidata"]
}
```

### Scoring Rule Fields Supported

The rule engine must support all of these fields:

| Field | Type | Description |
|---|---|---|
| `industry` | string | Mapped industry tag (Auto Parts, Restaurant, etc.) |
| `category` | string | Raw OSM amenity/shop category |
| `is_chain` | bool | True if chain_confidence >= 60 |
| `chain_confidence` | int 0-100 | How confident we are it's a chain |
| `entity_type` | string | Local / Regional Chain / National Chain / Franchise / Unknown |
| `num_locations` | int | Estimated number of locations (from Wikidata) |
| `parent_company` | string | Parent company name if known |
| `has_website` | bool | Website tag present in OSM |
| `has_email` | bool | Email tag present in OSM |
| `has_phone` | bool | Phone tag present in OSM |
| `has_opening_hours` | bool | Opening hours tag present |
| `osm_completeness` | int 0-100 | % of expected OSM tags that are filled |
| `distance_mi` | float | Distance from search center in miles |
| `audience_overlap` | string | Inferred audience description |
| `founded_year` | int | Year business was founded (Wikidata) |

### Rule Operators Supported

`=`, `!=`, `>`, `<`, `>=`, `<=`, `contains`, `not contains`, `is empty`, `is not empty`

### Rule Stacking

Rules are additive. Total score is capped at 100. Rules are evaluated in order.
Distance rules are mutually exclusive — only the highest matching tier applies.

### Built-in Profiles (ship with app)

**car_meet_sponsor.json** — as shown above

**general_outreach.json** — neutral baseline:

```json
{
  "name": "General Outreach",
  "description": "Balanced scoring for general local business outreach",
  "scoring_rules": [
    { "field": "is_chain", "operator": "=", "value": false, "points": 25 },
    { "field": "has_website", "operator": "=", "value": true, "points": 20 },
    { "field": "has_phone", "operator": "=", "value": true, "points": 20 },
    { "field": "distance_mi", "operator": "<", "value": 2, "points": 20 },
    { "field": "distance_mi", "operator": "<", "value": 5, "points": 10 },
    { "field": "osm_completeness", "operator": ">", "value": 50, "points": 15 }
  ],
  "audience_keywords": [],
  "default_filters": { "hide_chains": false, "min_score": 0, "category": "All" },
  "export_columns": ["Name", "Score", "Industry", "Phone", "Email", "Website", "Address", "Notes"],
  "data_sources": ["overpass", "wikidata"]
}
```

---

## PROFILE EDITOR UI

See the dedicated PROFILE EDITOR section below for full spec.
The profile system is optional — all filtering, sorting, and scoring works without
an active profile. Profiles exist purely to save and recall a preferred configuration.

### Profile Selector (top bar)

- Dropdown showing all profiles in profiles/ folder plus a "No profile" option
- "New" button -> opens Profile Builder blank
- "Clone" button -> duplicates active profile with " (copy)" suffix
- "Delete" button -> confirmation dialog, disabled if only one profile exists
- Switching profiles prompts: "Apply this profile's default filters?" Yes / No / Always
- With "No profile" selected: sidebar starts at neutral app defaults, AI prompts use
  a generic description ("general local business outreach")

---

## LOCATION INPUT

Three modes selectable via radio buttons in the top bar:

### Manual Address

- Text entry field -> geocode on search via geopy Nominatim
- Show resolved coordinates in small label below field for confirmation

### Saved Location

- Dropdown of saved locations (loaded from config.json)
- "Save current" button -> prompts for a name, saves lat/lon + address to config.json
- "Delete" button removes selected saved location

### Drop a Pin

- Dialog with two number fields: Latitude, Longitude
- "Use my location" button attempts IP-based geolocation via ip-api.com (free, no key)
- Confirm button closes dialog and sets search center

---

## RADIUS & SEARCH

- Slider: 0.5 mi to 25 mi, step 0.5, default 5 mi
- Label shows current value in miles
- "Search" button -> validates location -> runs fetch in background thread
- While fetching: progress bar in status bar, "Searching..." label, Search button disabled
- Results cached in memory for the session — re-filtering/sorting never re-fetches

---

## OVERPASS API (sources/overpass.py)

### Query Strategy

Build an Overpass QL union query targeting:

```
node["name"]["shop"](bbox);
node["name"]["amenity"](bbox);
node["name"]["office"](bbox);
node["name"]["leisure"](bbox);
way["name"]["shop"](bbox);
way["name"]["amenity"](bbox);
```

Bounding box computed from center lat/lon + radius using Haversine.
Cap results at 300. If raw result count > 300, sort by proximity and take closest 300.

### Tags to Extract

`name`, `addr:housenumber`, `addr:street`, `addr:city`, `addr:state`, `addr:postcode`,
`phone`, `email`, `website`, `opening_hours`, `brand`, `brand:wikidata`, `operator`,
`franchise`, `shop`, `amenity`, `office`, `leisure`, `cuisine`, `description`

### Distance Calculation

Haversine formula for each result from search center. Store as `distance_mi` (float, 2 decimal places).

---

## ENTITY INTELLIGENCE (enrichment.py)

Run for every result after fetch. Use ThreadPoolExecutor(max_workers=10) so 300 results enrich concurrently.

### Step 1 — OSM Tag Analysis (instant, no network)

```python
def analyze_osm_tags(tags):
    if "brand:wikidata" in tags:
        return { "chain_confidence": 95, "source": "osm_wikidata_tag" }
    if "brand" in tags:
        return { "chain_confidence": 75, "source": "osm_brand_tag" }
    if "franchise" in tags:
        return { "chain_confidence": 70, "source": "osm_franchise_tag" }
    if "operator" in tags:
        return { "chain_confidence": 50, "source": "osm_operator_tag" }
    return { "chain_confidence": 0, "source": "none" }
```

### Step 2 — Wikidata Lookup (async, cached)

Only run if chain_confidence from Step 1 is 0.
Cache key: normalized business name (lowercase, stripped punctuation).
Check entity_cache.json before making any network call.

```python
def lookup_wikidata(name):
    normalized = normalize_name(name)
    cached = load_cache().get(normalized)
    if cached:
        return cached
 
    url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbsearchentities",
        "search": name,
        "language": "en",
        "format": "json",
        "limit": 1
    }
    try:
        r = requests.get(url, params=params, timeout=5).json()
    except Exception:
        return default_entity_result()
 
    results = r.get("search", [])
    if not results:
        return default_entity_result()
 
    desc = results[0].get("description", "").lower()
    chain_keywords = [
        "chain", "franchise", "restaurant chain", "retail chain",
        "fast food", "multinational", "corporation", "convenience store",
        "supermarket", "pharmacy chain", "gas station"
    ]
    confidence = 80 if any(kw in desc for kw in chain_keywords) else 10
 
    result = {
        "chain_confidence": confidence,
        "wikidata_id": results[0].get("id"),
        "wikidata_description": results[0].get("description", ""),
        "source": "wikidata"
    }
    save_cache(normalized, result)
    return result
```

### Step 3 — Industry Tagging

Map OSM tags to a human-readable industry label. Use a minimal seed map only for the
most unambiguous OSM tag values — this is a fallback only, not the primary source:

```python
INDUSTRY_SEED_MAP = {
    "fuel": "Gas Station",
    "fast_food": "Fast Food",
    "supermarket": "Supermarket",
    "bank": "Bank",
    "hospital": "Hospital",
    "pharmacy": "Pharmacy",
}
```

For any OSM tag not in the seed map, pass the raw tag value plus any available OSM
tags (name, shop, amenity, cuisine, description) to the AI inference step below.
Do NOT hardcode a comprehensive mapping — the AI handles everything else.

### Step 4 — AI Inference (industry + audience, single call per business)

For each business where industry is unknown or audience is needed, query the local model with:

```
Given this business data from OpenStreetMap, infer:
1. A short industry label (2-4 words, e.g. "Auto Parts", "Craft Brewery", "Tattoo Studio")
2. A brief target audience description (1 sentence, who shops or visits here)
 
OSM data:
- Name: {name}
- Tags: {relevant_tags}
 
Respond ONLY with valid JSON, no markdown:
{"industry": "...", "audience": "..."}
```

Parse the JSON response. On failure (model returns garbage or times out), fall back to:

- industry: humanize the raw OSM tag (e.g. "car_repair" -> "Car Repair")
- audience: "General public"

Cache all AI inference results in entity_cache.json keyed by osm_id — never re-infer
a business already in cache. This means AI inference only runs once per unique business
ever seen, not on every app launch.

### Step 5 — OSM Completeness Score

Count how many of these tags are present: `name`, `phone`, `email`, `website`, `opening_hours`,
`addr:street`, `addr:city`. Score = (present / 7) * 100.

### Step 6 — Entity Type Classification

```python
def classify_entity_type(chain_confidence, num_locations):
    if chain_confidence < 30:
        return "Local"
    if chain_confidence < 60:
        return "Unknown"
    if num_locations and num_locations < 10:
        return "Regional Chain"
    if num_locations and num_locations < 100:
        return "National Chain"
    return "Franchise"
```

### Final Enriched Business Object

```python
{
    # Core OSM fields
    "osm_id": str,
    "name": str,
    "address": str,           # formatted full address
    "phone": str,
    "email": str,
    "website": str,
    "opening_hours": str,
    "lat": float,
    "lon": float,
 
    # Computed fields
    "distance_mi": float,
    "industry": str,
    "category": str,          # raw OSM tag value
    "audience_overlap": str,
    "has_phone": bool,
    "has_email": bool,
    "has_website": bool,
    "has_opening_hours": bool,
    "osm_completeness": int,
 
    # Entity intelligence
    "chain_confidence": int,
    "is_chain": bool,         # chain_confidence >= 60
    "entity_type": str,
    "parent_company": str,
    "num_locations": int,
    "founded_year": int,
    "wikidata_id": str,
    "wikidata_description": str,
 
    # App state
    "score": int,             # computed by scoring engine
    "shortlisted": bool,
    "note": str,
}
```

---

## SCORING ENGINE (scoring.py)

```python
def compute_score(business, rules):
    score = 0
    distance_scored = False
 
    for rule in rules:
        field = rule["field"]
        operator = rule["operator"]
        value = rule["value"]
        points = rule["points"]
 
        # Distance rules are mutually exclusive — highest tier only
        if field == "distance_mi" and distance_scored:
            continue
 
        if evaluate_rule(business.get(field), operator, value):
            score += points
            if field == "distance_mi":
                distance_scored = True
 
    return min(score, 100)
 
 
def evaluate_rule(field_value, operator, rule_value):
    if field_value is None:
        return operator in ("is empty",)
    ops = {
        "=":           lambda a, b: a == b,
        "!=":          lambda a, b: a != b,
        ">":           lambda a, b: float(a) > float(b),
        "<":           lambda a, b: float(a) < float(b),
        ">=":          lambda a, b: float(a) >= float(b),
        "<=":          lambda a, b: float(a) <= float(b),
        "contains":    lambda a, b: str(b).lower() in str(a).lower(),
        "not contains":lambda a, b: str(b).lower() not in str(a).lower(),
        "is empty":    lambda a, b: not a,
        "is not empty":lambda a, b: bool(a),
    }
    try:
        return ops[operator](field_value, rule_value)
    except Exception:
        return False
```

---

## MAIN UI LAYOUT

Window title: "Business Finder"
Minimum size: 1200 x 750
Resizable, remembers size and position via config.json

```
+-------------------------------------------------------------------------------------------+
|  MENU BAR: File | Edit | View | Search | Profiles | Filters | Tools | Help               |
+-------------------------------------------------------------------------------------------+
|  TOP BAR: [Profile dropdown] [Location mode radio] [Address field] [Radius slider] [Search] |
+----------------+------------------------------------------+-----------------------------+
|                |                                          |                             |
|  FILTER        |   RESULTS TABLE (ttk.Treeview)           |  DETAIL PANE                |
|  SIDEBAR       |   flexible width                         |  (visible on row select)    |
|  ~220px        |                                          |  ~300px                     |
|                |                                          |                             |
+----------------+------------------------------------------+-----------------------------+
|  STATUS BAR: [AI status dot] [progress bar] [status label]  [result count] [Export btn]  |
+-------------------------------------------------------------------------------------------+
```

---

## MENU BAR (ui/menu_bar.py)

Standard Tkinter Menu bar across the top of the window. Every major feature is
reachable from the menu — the app should be fully operable via menu alone.

### File

- New Session — clears all results, notes, and filters for a fresh start (confirms if unsaved)
- Open results... — load a previously exported JSON session file
- Save session... — save current results + notes + filters to a JSON session file
- ── separator ──
- Export shortlist to CSV — same as status bar Export button
- Export ALL results to CSV — exports full unfiltered result set
- Export session report... — generates a formatted text/markdown summary report
- ── separator ──
- Settings... — opens Settings dialog (API keys, AI settings, data sources)
- ── separator ──
- Exit

### Edit

- Select all — checks all shortlist checkboxes
- Deselect all — unchecks all shortlist checkboxes
- Invert selection
- ── separator ──
- Copy selected names — copies all shortlisted business names to clipboard
- Copy selected emails — copies all shortlisted emails to clipboard (newline separated)
- Copy selected phones — copies all shortlisted phones to clipboard
- ── separator ──
- Clear all notes — prompts confirmation, wipes notes.json
- Clear AI cache — clears session AI explanation cache (forces re-generation)
- Clear entity cache — clears entity_cache.json (forces fresh Wikidata lookups)

### View

- Toggle filter sidebar — show/hide left sidebar
- Toggle detail pane — show/hide right detail pane
- ── separator ──
- Columns... — opens column visibility dialog (checkboxes for each column)
- Compact rows — toggle between normal and compact row height
- ── separator ──
- Score: All / High (>=70) / Medium (40-69) / Low (<40) — quick score tier filter
- ── separator ──
- Zoom in / Zoom out / Reset zoom — font size scaling for accessibility

### Search

- New search — focuses address field, selects all text
- Repeat last search — re-runs the exact previous query
- ── separator ──
- Search settings...
  - Max results cap (default 300, adjustable 50-1000)
  - Request timeout (seconds)
  - Cache results between sessions on/off
- ── separator ──
- Clear cached results

### Profiles

- Active profile submenu — lists all profiles, checkmark on active, click to switch
- ── separator ──
- New profile... — opens Profile Builder blank
- Edit active profile... — opens Profile Builder for current profile
- Clone active profile — duplicates with " (copy)" suffix
- ── separator ──
- Manage profiles... — opens Profile Manager dialog
- Import profile from file...
- Export active profile to file...
- ── separator ──
- No profile (neutral mode)

### Filters

- Save current filters as... — prompts for name, saves to filters.json
- Load saved filter — submenu listing all saved named filters
- ── separator ──
- Build custom filter... — opens Custom Filter dialog
- Clear custom filter
- ── separator ──
- Reset to profile defaults
- Reset all filters
- ── separator ──
- Quick filters submenu (generated from common patterns):
  - Local businesses only
  - Has contact info (phone OR email OR website)
  - Fully contactable (phone AND email AND website)
  - High OSM completeness (>= 70%)
  - Within 2 miles
  - Score >= 70

### Tools

- AI Scoring — toggle on/off (checkmark)
- Run AI score on all results...
- Clear AI scores
- ── separator ──
- Manage data sources... — opens Data Source Manager
- ── separator ──
- Open entity cache file — opens entity_cache.json in default text editor
- Open notes file — opens notes.json in default text editor
- Open config file — opens config.json in default text editor
- ── separator ──
- Run diagnostics — checks local AI model status, Overpass connectivity, geopy availability,
  prints report to a small text dialog

### Help

- Getting started — opens a simple text dialog with quickstart instructions
- Keyboard shortcuts — opens shortcuts reference dialog
- About — version, project info

---

## RESULTS TABLE (ui/results_table.py)

### Columns

Score | Name | Industry | Type | Chain? | Distance | Phone | Website

- Score column: colored badge — green bg >= 70, yellow bg 40-69, red bg < 40
- Chain? column: "Yes" in red text, "No" in green text, "?" in gray
- Distance formatted as "2.3 mi"
- Website column: clickable, opens in default browser via webbrowser.open()
- Column header click -> sort by that column (toggle asc/desc, arrow indicator)
- Alternating row background colors (subtle)
- Row tinting: green-tinted rows >= 70, red-tinted rows < 40
- Shortlist checkbox in leftmost column
- Double-click row -> opens/focuses detail pane

### Context Menu (right-click on row)

- Add to shortlist / Remove from shortlist
- Add note
- Copy name
- Copy phone
- Copy email
- Open website
- Search Google (opens browser)

---

## FILTER SIDEBAR (ui/filter_sidebar.py)

Always visible on the left. Sections separated by thin dividers.
All filters operate independently — no profile required. Profile default_filters
pre-populate these fields on load but every control is fully editable at runtime.
Changes take effect immediately (live filtering on every interaction).

### Search

- Text entry: live filter by business name keyword (updates on every keystroke)

### Industry

- Multi-select listbox: all unique industry values in current results
- "All" selected by default, individual selections narrow results
- Ctrl+click to select multiple industries

### Chain Filter

- Checkbox: "Hide chains"
- Checkbox: "Hide unknowns" (entity_type = Unknown)
- Dropdown: Entity type — All / Local / Regional Chain / National Chain / Franchise / Unknown

### Contact Info

- Checkbox: "Has phone"
- Checkbox: "Has email"
- Checkbox: "Has website"

### Score

- Label: "Min score" with current value
- Slider 0-100
- Label: "Max score" with current value
- Slider 0-100 (default 100)
- These two sliders define a score range band, not just a floor

### Distance

- Label: "Max distance"
- Slider 0.5-25 mi with current value label

### OSM Completeness

- Label: "Min data completeness"
- Slider 0-100 (default 0) — filters out businesses with sparse OSM data

### AI Score (visible only when AI scoring is ON)

- Label: "Min AI score"
- Slider 0-100

### Sort By

- Primary sort dropdown: Score (default), AI Score, Combined Score, Distance,
  Name, Industry, Entity Type, Chain Confidence, OSM Completeness, Has Phone,
  Has Email, Has Website
- Direction toggle: Ascending / Descending
- Secondary sort dropdown: None (default) + same options as primary
- Secondary direction toggle

### Custom Filter

- Button: "Build Custom Filter" -> opens custom filter dialog
- If active: green "Custom filter active" label + "Clear" button

### Saved Filters

- Button: "Save current filters" -> prompts for a name, saves all current sidebar
  state to filters.json
- Dropdown of saved filters -> selecting one restores all sidebar fields to that state
- "Delete saved filter" button
- Saved filters are independent of profiles — they persist across sessions

### Buttons

- "Reset to defaults" — resets all fields to active profile's default_filters
  (if no profile loaded, resets to app defaults: no filters, sort by score desc)
- "Reset all" — clears every filter completely regardless of profile

---

## DETAIL PANE (ui/detail_pane.py)

Shown on the right when a row is selected. Hidden when nothing is selected.
Scrollable. Sections:

- Business name (large, bold)
- Score badge (large, colored)
- Core info: address, phone (clickable tel: link), email (clickable mailto: link), website (clickable), opening hours
- Classification: industry, category, entity type, chain confidence displayed as a visual bar, parent company
- Audience: inferred target audience text
- OSM data: completeness score as a visual bar, wikidata ID, raw OSM tags (collapsible section)
- Notes: multi-line text area — auto-saves on focus-out to notes.json
- Shortlist toggle button

---

## CUSTOM FILTER DIALOG (ui/custom_filter.py)

Opened via "Build Custom Filter" in sidebar. Operates on top of standard sidebar
filters — both apply simultaneously.

- Table of rules: Field dropdown | Operator dropdown | Value entry | Delete button
- Supported fields: all fields in the enriched business object (same list as scoring rules)
- AND/OR toggle at top: "Match ALL rules" / "Match ANY rule"
- "Add Rule" button appends a blank row
- "Apply" -> closes dialog, marks sidebar "Custom filter active", results update immediately
- "Clear" -> removes custom filter entirely
- "Save as named filter" -> prompts for name, saves to filters.json (same pool as sidebar saved filters)
- "Save as profile default" -> writes these rules into active profile's default_filters

---

## PROFILE EDITOR (ui/profile_editor.py)

Accessible via: top bar "Profiles" menu -> "New Profile", "Edit Profile", or "Manage Profiles"
Also accessible from sidebar "Reset to defaults" area.

### Profile Manager Dialog

Lists all profiles in profiles/ folder in a scrollable panel.
Per profile: name, description, Edit button, Clone button, Delete button.
"New Profile" button at top -> opens Profile Builder blank.
"Import profile" button -> load a .json file from disk as a new profile.
"Export profile" button -> save active profile as a .json file to disk (for sharing).

### Profile Builder / Editor

Full-window modal with tabs:

**General tab**

- Name field (required)
- Description field (used in AI prompts — be descriptive)
- Created / last modified labels (auto-set)

**Scoring Rules tab**
Rule builder table: Field | Operator | Value | Points | Delete | Drag-to-reorder

- "Add Rule" button
- Operator options adapt to field type (bool fields get =, !=; numeric get all; string get contains etc.)
- Value widget adapts: checkbox for bool, spinbox for number, text entry for string,
  dropdown for fields with known enum values (entity_type, industry)
- "Test Score" button: if results are loaded, runs rules against them and shows
  a live ranked preview in a small scrollable list alongside the editor
- "Clear all rules" button

**Audience Keywords tab**

- Chip-style tag input: type keyword + Enter to add, click X on chip to remove
- Keywords used in AI scoring prompts and audience_overlap field matching
- No hardcoded suggestions — user defines what matters for their use case

**Default Filters tab**

- Full mirror of the sidebar filter controls (same fields, same widgets)
- These values pre-populate the sidebar when this profile is activated
- "Copy from current sidebar" button: pulls whatever is currently set in the
  sidebar into these defaults — fastest way to build defaults from a live session

**Export Columns tab**

- Checklist of all available fields
- Drag to reorder
- Preview of what the CSV header row will look like

**Data Sources tab**

- Checkboxes for enabled sources (Overpass always on)
- Wikidata toggle
- Optional source toggles (Google Places, Yelp) with key status indicator

### Profile Selector (top bar)

- Dropdown showing all profiles in profiles/ folder
- "New" button -> Profile Builder blank
- "Clone" button -> duplicates active profile with " (copy)" suffix
- "Delete" button -> confirmation dialog, disabled if only one profile exists
- Switching profiles: prompts "Apply this profile's default filters?" Yes / No / Always
- "No profile" option available — run with no profile, all defaults neutral

---

## SHORTLIST & EXPORT (export.py)

### Shortlist

- Checkboxes in results table
- Shortlist persists in memory for the session

### CSV Export

- File save dialog, default filename: `business_export_YYYY-MM-DD.csv`
- Exports only the columns defined in active profile's export_columns
- Always exports all shortlisted rows regardless of active filters

### Notes

- Per-business text notes stored in notes.json keyed by OSM node ID
- Loaded on app start, saved on every edit (debounced 500ms)

---

## DATA SOURCE MANAGER (ui/source_settings.py)

Accessible via: Settings menu -> Data Sources

### Per-source UI

- Enable/disable toggle
- Source name + description
- API key field if required (stored in config.json only, never in profiles)
- "Test Connection" button

### Built-in Sources (no key required)

- **OpenStreetMap / Overpass** — core business data
- **Wikidata** — chain detection and entity intelligence

### Optional Sources (user-supplied key)

- **Google Places** — ratings, review count, photos, richer business data
- **Yelp Fusion** — ratings, price level, review snippets

### Source Interface (sources/base.py)

```python
class BaseSource:
    name: str
    requires_key: bool
 
    def fetch(self, lat, lon, radius_m) -> list[dict]:
        """Return list of raw business dicts"""
        raise NotImplementedError
 
    def enrich(self, business: dict) -> dict:
        """Add fields to an existing business dict, return updated"""
        return business
 
    def test_connection(self) -> bool:
        raise NotImplementedError
```

Results from multiple active sources are merged using business name + proximity deduplication.

---

## APP SETTINGS (config.json)

Auto-created on first run. Never committed to version control.

```json
{
  "window": { "width": 1200, "height": 750, "x": 100, "y": 100 },
  "last_location": { "lat": 33.014, "lon": -97.093, "label": "Flower Mound, TX" },
  "saved_locations": [
    { "label": "Home", "lat": 33.014, "lon": -97.093 }
  ],
  "active_profile": "car_meet_sponsor",
  "last_radius_mi": 5.0,
  "api_keys": {
    "google_places": "",
    "yelp": ""
  }
}
```

---

## UX & PERFORMANCE NOTES

- All network calls run in background threads — UI never freezes
- Enrichment runs concurrently with ThreadPoolExecutor(max_workers=10)
- Results table updates progressively as enrichment completes (batch UI refresh every 500ms)
- entity_cache.json persists across sessions — same business name is never looked up twice
- Filters and sorts operate entirely in-memory on the cached result list — instant
- Re-scoring after profile switch is an O(n) pass over cached results, no network calls
- Status bar shows fetch progress, enrichment progress ("Enriching 47/300..."), and filtered count
- App remembers last window size, position, radius, and active profile via config.json

---

## CONSTRAINTS

- No external paid APIs required for core functionality
- Minimal dependencies: requests, geopy — nothing else outside standard library
- Target platform: Windows 10/11 primary, macOS/Linux compatible
- No internet connection required after initial fetch (session cache)
- All user data (notes, config, cache) stored locally in project folder — no cloud sync

---

## AI SCORING (ai_scoring.py)

Uses `llama-cpp-python` for direct local LLM inference — fully offline, no API key, no token costs,
no data leaving the machine, no external services. Two modes: Explanation (per selection) and AI Score
(batch, user-initiated).

### Prerequisites

- Python package: `llama-cpp-python` (included in requirements.txt)
- A model file (.gguf format) downloaded from HuggingFace on-demand
- No external services or installations needed

### Dependency

- `llama-cpp-python>=0.2.0` — already in requirements.txt

### Model Selection (Settings -> AI Settings)

- Dropdown of available models from local cache (in `~/.cache/sponsor_finder/models/`)
- Pre-configured registry with Ollama-style names (llama3.2, mistral, gemma3, phi3)
- Models mapped to HuggingFace GGUF URLs for direct download
- "Download Model" button to selected model if not cached
- Default: llama3.2:1b (fastest, 1.3 GB)
- If no models cached: show "Download a model to enable AI features"
- AI features are hidden/disabled gracefully — app works fully without models

### Connection Check

On app start, check if `/models` directory exists. Show status indicator in status bar:
- Green dot "AI ready" if a model is cached
- Gray dot "AI offline" if no models cached

### Mode 1: Score Explanation (detail pane)

Triggered automatically when a row is selected and a model is loaded.
Runs in a background thread — detail pane shows "Generating insight..." placeholder,
then updates when the local model responds.

Prompt:

```
You are helping evaluate local businesses as potential sponsors for: {profile.description}

Business details:
- Name: {name}
- Industry: {industry}
- Entity type: {entity_type} (chain confidence: {chain_confidence}%)
- Distance: {distance_mi} miles from event location
- Has website: {has_website}, Has phone: {has_phone}, Has email: {has_email}
- Target audience: {audience_overlap}
- Rule-based score: {score}/100
- OSM completeness: {osm_completeness}%

In 2-3 sentences: explain why this business scored the way it did, and suggest
a specific outreach angle. Be direct and practical. No fluff.
```

Output displayed in detail pane under "AI Insight" section.
Cache explanations in memory for the session keyed by osm_id — don't re-generate if already done.

### Mode 2: AI Score Mode

Activated via toggle in filter sidebar: "AI Scoring: ON/OFF"
When ON: each business gets an additional ai_score (0-100) from the local model.

Batch prompt (10 businesses per call — local models are slower than cloud):

```
You are scoring local businesses as potential sponsors for: {profile.description}

Score each business 0-100 based on fit. Consider: industry relevance, local vs chain,
professionalism signals, audience overlap with the event.

Respond ONLY with a valid JSON array, no explanation, no markdown:
[{"osm_id": "...", "ai_score": 85, "reason": "one sentence"}, ...]

Businesses:
{json.dumps(business_list, indent=2)}
```

business_list contains only: osm_id, name, industry, entity_type, chain_confidence,
distance_mi, has_website, has_phone, has_email, audience_overlap

Parse response carefully — local models occasionally add extra text before/after JSON.
Use regex to extract the JSON array if needed: re.search(r'\[.*\]', response, re.DOTALL)

### Combined Score

When AI Scoring is ON, show three columns in results table:

- Rule score
- AI score
- Combined score: weighted average, adjustable via slider in AI Settings

Combined score = (rule_score * rule_weight) + (ai_score * ai_weight)
where rule_weight + ai_weight = 1.0

### AI Settings Dialog (Settings -> AI Settings)

- Model status indicator + "Download Model" button
- Model registry dropdown: llama3.2 (recommended), llama3.2:1b (fastest), mistral, gemma3, phi3
- "Download" button with progress bar for selected model
- Downloaded models list with "Delete" button per model to free space
- AI scoring weight slider: Rule [----|---------] AI (default 50/50)
- "Enable AI explanations" checkbox (default on if model available)
- "Enable AI scoring mode" checkbox (default off — slower, processes in batches)
- "Max businesses to AI score" number input (default 50, cap at 200)

### Performance Notes

- Local models are slower than cloud APIs — batch size capped at 10
- Explanation mode: typically 3-10 seconds per business depending on hardware and model
- AI Score mode: runs batches sequentially, progress shown in status bar ("AI scoring 20/50...")
- Session cache: never re-score a business already scored this session
- GPU acceleration: automatic if using supported hardware (NVIDIA/AMD GPU or Apple Silicon)
