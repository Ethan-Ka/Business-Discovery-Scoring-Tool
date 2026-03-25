# Business Discovery & Scoring Tool — Installation & Setup

## Quick Start

### For End Users (Recommended)

Download `BusinessFinder.exe` and double-click it.

**That's it!** You'll have immediate access to all core features:
- Business search and filtering
- Scoring rules
- CSV export

AI features (automated scoring explanations, advanced analysis) work without any additional installation. Models are downloaded on-demand the first time you enable AI features.

No setup required. No Python knowledge needed.

### For Developers / Manual Install

If running from Python source:

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python sponsor_finder/main.py
```

Or use the provided batch launcher:
```bash
run.bat
```

### Build EXE (Do Not Bundle Models)

Use the included build script/spec to produce a packaged app that does **not**
ship `.gguf` model files:

```bash
build_exe.bat
```

This calls PyInstaller with `business_finder.spec`, which intentionally sets
no bundled data payload for models. AI models are always downloaded later by
the end user into the local data folder.

If you use auto-py-to-exe directly, do **not** add `data/models` (or any
`.gguf` files) in "Additional Files".

## What Happens on First Launch

When you run the app for the first time:

1. **Core features available immediately** — Search, filter, and export work right away
2. **Optional AI setup** — The first time you enable AI scoring, a model (~1.3 - 4 GB) is downloaded from HuggingFace
3. **Model cached locally** — Once downloaded, the model stays on your computer and is reused (no re-downloads)
4. **Ready for AI** — AI scoring and explanations are then available offline

**No runtime dependencies needed!** All inference happens locally on your machine, completely offline.

## System Requirements

- **Windows 10/11** (recommended for .exe)
- **macOS/Linux** — Python install (no .exe)
- **~5 GB** disk space (if using AI features with a model)
- **Internet connection** only for:
  - Searching businesses (OSM/Wikidata)
  - First AI model download
- **After initial setup: fully offline capable**

## What Gets Downloaded

### Core App
- App files and dependencies (via pip or .exe)

### AI Models (optional, on-demand)
Downloaded from HuggingFace only when you first enable AI scoring. Choose one:

- **llama3.2:1b** (recommended for speed) — 1.3 GB, fast inference
- **llama3.2** — 4.0 GB, high quality
- **mistral** — 4.1 GB, excellent reasoning
- **gemma3:4b** — 3.3 GB, balanced
- **phi3** — 2.3 GB, efficient

Models are cached locally in the app data folder:

- Windows EXE: `<exe folder>\data\models\`
- Source/dev run: `<project root>\data\models\`

Once downloaded, models are reused and never re-downloaded unless deleted.

## Troubleshooting

### "AI features not working"

AI features are **optional**. The app works fully without them.

If you want to use AI:
1. Open **Settings → AI Settings**
2. You'll see available models
3. Select one and it will download (~1-4 GB depending on choice)
4. Once complete, AI features are enabled

**No external services needed** — everything runs locally on your machine.

### "Model download failed"

- Check your internet connection
- Try a different model (smaller ones download faster)
- If it still fails, AI features simply remain unavailable — core app works normally

### App won't start

**If using Python source:**
- Make sure Python 3.8+ is installed
- Run: `pip install -r requirements.txt`
- Then: `python sponsor_finder/main.py`

**If using .exe:**
- Try deleting `<exe folder>\data\models\` to clear cached AI files
- Then restart the app

### Performance Issues

If AI responses are very slow:
- Close other applications to free up system RAM
- Use a smaller model (llama3.2:1b is fastest)
- Restart the app to free up model memory

## Advanced: Uninstalling

### Remove the application
Simply delete the app folder or use Windows Add/Remove Programs.

### Remove cached AI models (optional)
If you want to reclaim disk space:

**Windows:**
1. Open File Explorer
2. Navigate to: `<exe folder>\data\models\`
3. Delete the `.gguf` model files

**macOS/Linux:**
```bash
rm ~/.cache/sponsor_finder/models/*.gguf
```

## What is llama-cpp-python?

The app uses `llama-cpp-python` for direct, local LLM inference:
- **Fully offline** — all processing happens on your machine
- **No external services** — data never leaves your PC
- **No fees** — completely free, no token costs
- **Privacy** — complete local control
- **Fast** — runs efficiently on commodity hardware

Supported models are pre-quantized for optimal balance between speed and quality.

## Privacy & Data

- **All processing is local** — Your business data never leaves your computer
- **No telemetry** — The app does not phone home
- **No accounts** — No login, no subscriptions, no tracking
- **Models are open source** — View them on HuggingFace

## Support

For issues not covered here:
- Open Settings → AI Settings in the app for model management
- Check the app's README.md in the repository

