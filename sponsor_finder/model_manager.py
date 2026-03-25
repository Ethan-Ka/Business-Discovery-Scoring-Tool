"""
Model management for llama-cpp-python.
Handles model registry, downloading, caching, and loading.

Models are stored in {app_base}/data/models/ as .gguf files.
For packaged executables this resolves to {exe_dir}/data/models/.
Uses Ollama-style naming (e.g., "llama3", "mistral") but maps to GGUF URLs.
"""

import os
import json
import shutil
import requests
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, List

try:
    from sponsor_finder.paths import get_models_dir as get_models_dir_path
except ImportError:
    from paths import get_models_dir as get_models_dir_path


# Model registry: user-facing names mapped to public GGUF URLs.
# Prefer direct-download hosts that do not require auth tokens.
OLLAMA_MODEL_REGISTRY = {
    "llama3": {
        "url": "https://gpt4all.io/models/gguf/Meta-Llama-3-8B-Instruct.Q4_0.gguf",
        "size_gb": 4.0,
        "description": "Meta Llama 3 8B Instruct (Q4) — recommended",
        "chat_format": "llama-3",
    },
    "mistral": {
        "url": "https://gpt4all.io/models/gguf/mistral-7b-instruct-v0.1.Q4_0.gguf",
        "size_gb": 4.1,
        "description": "Mistral 7B Instruct (Q4) — strong reasoning",
        "chat_format": "mistral-instruct",
    },
    "phi3": {
        "url": "https://gpt4all.io/models/gguf/Phi-3-mini-4k-instruct.Q4_0.gguf",
        "size_gb": 2.2,
        "description": "Microsoft Phi-3 Mini 4K Instruct (Q4) — efficient",
        "chat_format": "chatml",
    },
    "orca-mini:3b": {
        "url": "https://gpt4all.io/models/gguf/orca-mini-3b-gguf2-q4_0.gguf",
        "size_gb": 2.0,
        "description": "Orca Mini 3B (Q4) — lightweight option",
        "chat_format": "chatml",
    },
    "falcon": {
        "url": "https://gpt4all.io/models/gguf/gpt4all-falcon-newbpe-q4_0.gguf",
        "size_gb": 4.2,
        "description": "GPT4All Falcon 7B (Q4) — fast general-purpose",
        "chat_format": "chatml",
    },

    # Backward-compat aliases to avoid breaking existing config values.
    "llama3.2": {
        "url": "https://gpt4all.io/models/gguf/Meta-Llama-3-8B-Instruct.Q4_0.gguf",
        "size_gb": 4.0,
        "description": "Alias to llama3",
        "chat_format": "llama-3",
    },
    "llama3.2:1b": {
        "url": "https://gpt4all.io/models/gguf/orca-mini-3b-gguf2-q4_0.gguf",
        "size_gb": 2.0,
        "description": "Alias to orca-mini:3b",
        "chat_format": "chatml",
    },
    "gemma3:4b": {
        "url": "https://gpt4all.io/models/gguf/Phi-3-mini-4k-instruct.Q4_0.gguf",
        "size_gb": 2.2,
        "description": "Alias to phi3",
        "chat_format": "chatml",
    },
}


def _is_valid_gguf_file(path: Path) -> bool:
    """Best-effort validation for local GGUF files.

    We only do lightweight checks here so invalid/corrupt placeholders do not
    appear as selectable models and cannot block AI startup.
    """
    try:
        if not path.exists() or not path.is_file():
            return False
        if path.stat().st_size < 16:
            return False
        with open(path, "rb") as f:
            magic = f.read(4)
        return magic == b"GGUF"
    except Exception:
        return False


def get_models_dir() -> Path:
    """Return the app-local models directory, migrating legacy model paths if needed."""
    models_dir = Path(get_models_dir_path())

    # One-time best-effort migration from legacy cache locations.
    # Keeps existing downloads usable after path normalization.
    if not any(models_dir.glob("*.gguf")):
        legacy_dirs: list[Path] = []

        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            legacy_dirs.append(Path(local_app_data) / "sponsor_finder" / "models")

        legacy_dirs.append(Path.home() / ".cache" / "sponsor_finder" / "models")

        for legacy_dir in legacy_dirs:
            if not legacy_dir.exists() or legacy_dir.resolve() == models_dir.resolve():
                continue
            for legacy_file in legacy_dir.glob("*.gguf"):
                target = models_dir / legacy_file.name
                if target.exists():
                    continue
                try:
                    shutil.copy2(legacy_file, target)
                except Exception:
                    continue

    return models_dir


def get_model_registry() -> Dict[str, Dict]:
    """Return the curated model registry."""
    return OLLAMA_MODEL_REGISTRY.copy()


def list_available_models() -> List[str]:
    """
    List model names that are cached locally as .gguf files.
    Returns list of filenames (without path).
    """
    models_dir = get_models_dir()
    if not models_dir.exists():
        return []

    valid_models: List[str] = []
    for f in models_dir.glob("*.gguf"):
        if _is_valid_gguf_file(f):
            valid_models.append(f.name)
    return sorted(valid_models)


def resolve_model_url(model_name: str) -> str:
    """
    Resolve a model name to its download URL.

    If model_name is in the registry, return its URL.
    Otherwise, assume it's a full GGUF URL and return as-is.
    This allows power users to specify custom model URLs.
    """
    if model_name in OLLAMA_MODEL_REGISTRY:
        return OLLAMA_MODEL_REGISTRY[model_name]["url"]
    # Assume it's a full URL
    return model_name


def resolve_model_filename(model_name: str) -> str:
    """
    Resolve a model name to its local filename.
    For registry models, extract filename from URL.
    For custom URLs, extract from last path component.
    """
    url = resolve_model_url(model_name)
    # Extract filename from URL (before query params)
    filename = url.split("/")[-1].split("?")[0]
    return filename


def get_model_info(model_name: str) -> Optional[Dict]:
    """
    Get info about a model (size, description, etc).
    Returns dict or None if not found in registry.
    """
    return OLLAMA_MODEL_REGISTRY.get(model_name)


def download_model(
    model_name: str,
    progress_callback: Optional[Callable[[str, Optional[float]], None]] = None,
    cancel_token=None,
) -> bool:
    """
    Download a model to the local cache.

    Args:
        model_name: Registry model name or full GGUF URL
        progress_callback: Called as progress_callback(status_msg, progress_pct)
                          progress_pct is 0.0-1.0 or None if unknown
        cancel_token: Object with .is_cancelled() method for user cancellation

    Returns True on success, False on failure.
    """
    def log(msg: str, pct: Optional[float] = None):
        if progress_callback:
            progress_callback(msg, pct)

    try:
        url = resolve_model_url(model_name)
        filename = resolve_model_filename(model_name)
        filepath = get_models_dir() / filename

        log(f"Downloading {filename}...", None)

        # Check for cancellation before starting
        if cancel_token and cancel_token.is_cancelled():
            log("Download cancelled", None)
            return False

        # Stream download with progress
        response = requests.get(url, stream=True, timeout=30, allow_redirects=True)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                # Check for cancellation during download
                if cancel_token and cancel_token.is_cancelled():
                    f.close()
                    try:
                        filepath.unlink()
                    except Exception:
                        pass
                    log("Download cancelled", None)
                    return False

                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = downloaded / total_size
                        log(f"Downloading: {pct*100:.1f}%", pct)

        log(f"Downloaded {filename}", 1.0)
        return True

    except requests.exceptions.RequestException as e:
        log(f"Download failed: {e}", None)
        return False
    except Exception as e:
        log(f"Error: {e}", None)
        return False


def delete_model(model_name: str) -> bool:
    """
    Delete a locally cached model.

    Args:
        model_name: Model name (will be resolved to filename)

    Returns True on success, False on failure.
    """
    try:
        filename = resolve_model_filename(model_name)
        filepath = get_models_dir() / filename

        if filepath.exists():
            filepath.unlink()
            return True
        return False
    except Exception:
        return False


def load_model(model_name: str, ctx_limit: int = 2048, n_gpu_layers: int = 0):
    """
    Load a model using llama-cpp-python.

    Args:
        model_name: Model name to load from cache
        ctx_limit: Context window size (tokens)
        n_gpu_layers: GPU layers to offload (0 = CPU-only; -1 = auto-detect GPU)
                      CPU-only is the safe default — GPU auto-detect can segfault
                      on machines without a compatible CUDA/ROCm driver.

    Returns Llama instance, or None if model not found.
    Raises ImportError if llama-cpp-python not installed.
    """
    from llama_cpp import Llama

    filename = resolve_model_filename(model_name)
    filepath = get_models_dir() / filename

    if not filepath.exists():
        raise FileNotFoundError(f"Model file not found: {filepath}")
    if not _is_valid_gguf_file(filepath):
        raise ValueError(f"Invalid GGUF model file: {filepath}")

    info = get_model_info(model_name) or {}
    chat_format = info.get("chat_format")

    _debug = bool(os.environ.get("DEBUG"))

    context_candidates = [int(ctx_limit)]
    for candidate in (1024, 512):
        if candidate not in context_candidates and candidate < int(ctx_limit):
            context_candidates.append(candidate)

    last_error = None
    for n_ctx in context_candidates:
        kwargs: dict = dict(
            model_path=str(filepath),
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=_debug,
            n_threads=4,
        )
        if chat_format:
            kwargs["chat_format"] = chat_format
        try:
            return Llama(**kwargs)
        except Exception as e:
            last_error = e

    if last_error is not None:
        raise RuntimeError(
            f"Failed to load model '{model_name}' after context fallbacks: {last_error}"
        )
    raise RuntimeError(f"Failed to load model '{model_name}'")


def download_model_async(
    model_name: str,
    on_progress: Callable[[str, Optional[float]], None],
    on_done: Callable[[], None],
    on_error: Callable[[str], None],
    cancel_token=None,
) -> None:
    """
    Download a model in a background thread.

    Args:
        model_name: Model to download
        on_progress: Called as on_progress(status_msg, progress_pct)
        on_done: Called on successful completion
        on_error: Called as on_error(error_msg) on failure
        cancel_token: Object with .is_cancelled() method
    """
    def _run():
        try:
            success = download_model(model_name, on_progress, cancel_token)
            if success:
                on_done()
            else:
                on_error("Download failed or was cancelled")
        except Exception as e:
            on_error(str(e))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
