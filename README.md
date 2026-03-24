# Business Discovery & Scoring Tool

A local-first Python desktop app for finding and scoring nearby businesses as potential sponsors (built for car meet outreach, but profile-driven for other use cases too).

## Releases
- Latest releases: https://github.com/Ethan-Ka/Sponsor-Finder/releases

## Quick Overview
- Tkinter desktop app (Windows-first, cross-platform capable)
- Searches local businesses via OpenStreetMap/Overpass
- Enriches data (distance, contact info, chain confidence, completeness)
- Applies rule-based scoring with profile support
- Supports shortlist, notes, filtering, and CSV export
- Optional offline AI scoring/explanations via `llama-cpp-python`

## Requirements
- Python 3.8+
- Dependencies in `requirements.txt`

## Run
```bash
pip install -r requirements.txt
python sponsor_finder/main.py
```

