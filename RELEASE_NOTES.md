# Business Discovery & Scoring Tool — Release Notes

## v1.1.0 — Settings, Reliability, and Data Path Improvements (2026-03-24)

This release focuses on quality-of-life upgrades, safer local credential handling, and more robust runtime behavior across source and packaged installs.

### Highlights

- Added a new unified **Settings** dialog with dedicated tabs for:
  - Data Sources
  - AI
  - Search
  - Debug
- Improved local AI model management with clearer download/status UX and better compatibility aliases.
- Expanded filtering capabilities with additional quality and amenities-focused controls.

### Security & Configuration

- Added secure API key storage via OS keychain integration (`keyring`) when available.
- Added graceful fallback to `config.json` storage if keychain is unavailable.
- Added per-source key visibility toggles, key clearing, and connection test actions in Settings.

### Data Paths, Migration, and Packaging

- Standardized app-local data paths for both dev and packaged execution.
- Added automatic best-effort migration for legacy data locations (config, profiles, models).
- Improved profile file bootstrapping to ensure default profiles are seeded when missing.

### AI & Model Runtime

- Improved model registry and default model behavior (`llama3` baseline with backward-compatible aliases).
- Added safer model lifecycle handling and explicit shutdown cleanup to reduce teardown/runtime issues.
- Improved model download flow with cancellation support and clearer progress reporting.

### Search, Filtering, and UX

- Improved Overpass search geometry by using geodesic `around` queries instead of square bounding boxes.
- Added stronger client-side distance guarding and mirror fallback behavior.
- Added/expanded standard filters (including open-now and amenity-based options), plus custom filter field coverage.
- Improved diagnostics/debug workflow with rotating app logs and additional debug settings.

### Compatibility Notes

- Existing user data is preserved; migration logic is best-effort and non-destructive.
- Core functionality remains local-first and works without paid APIs.

## v1.0.0 — Initial Release (2026-03-24)

This is the first public release of **Business Discovery & Scoring Tool**, a desktop app for discovering and evaluating local businesses as potential sponsors.

### Highlights

- Desktop app built with Python + Tkinter (Windows-first, cross-platform capable)
- OpenStreetMap/Overpass powered business discovery with radius-based search
- Multiple location modes:
  - Address geocoding
  - Saved location recall
  - Drop-a-pin (map when available, manual fallback)
- Adjustable search controls:
  - Radius from 0.5 to 25 miles
  - Max businesses cap up to 1000

### Enrichment & Scoring

- Automatic business enrichment pipeline:
  - Industry/category tagging
  - Chain detection (OSM tags + Wikidata + frequency analysis)
  - Audience inference
  - OSM completeness scoring
- Rule-based scoring engine with profile-aware rules and fallback mode
- Score breakdown visibility in the detail pane

### Profiles, Filters, and Workflow

- Built-in profile support with create/edit/clone/delete flows
- Profile editor with tabs for:
  - General info
  - Scoring rules
  - Audience keywords
  - Default filters
  - Export columns
  - Data source toggles
- Live filtering and sorting in-memory for fast interaction
- Custom filter builder with AND/OR rule combinations

### Results, Notes, and Export

- Interactive results table with:
  - Sortable columns
  - Color-coded score rows
  - Shortlist toggle
  - Context-menu quick actions
- Detail pane with business summary, score context, and notes
- Persistent shortlist and notes storage in local JSON files
- Export options:
  - Shortlist to CSV
  - All results to CSV
  - Session summary report (Markdown/Text)

### AI Features (Optional, Local)

- Optional local AI via `llama-cpp-python` (no API key required)
- Local model download/management from within AI Settings
- AI explanation mode for selected businesses
- Batch AI scoring mode with combined rule+AI weighted score
- Session-level AI caching to avoid repeated inference work

### Reliability and UX

- Background-threaded network operations to keep UI responsive
- Multi-mirror Overpass fallback handling
- Session persistence for window geometry, search settings, and AI preferences
- Full top-level menu system (File/Edit/View/Search/Profiles/Filters/Tools/Help)

### Requirements

- Python 3.8+
- Dependencies in `requirements.txt`
- Internet required for live Overpass/Wikidata lookups
- Internet required once for initial AI model download (if AI is enabled)

### Known Limitations

- Search/enrichment depends on external data source availability (Overpass/Wikidata uptime)
- AI scoring speed depends on local hardware and selected model size
- Map-based pin drop requires `tkintermapview`; app falls back to manual coordinate entry if unavailable

### Notes

- This release focuses on core sponsor discovery workflow and local-first data handling.
- All app data (config, notes, shortlist, cache) remains local to your machine.
