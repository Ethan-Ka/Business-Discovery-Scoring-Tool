"""
Secure API key storage.

Uses the OS keychain (keyring) when available:
  - Windows  → Credential Manager
  - macOS    → Keychain
  - Linux    → Secret Service / libsecret

Falls back to plaintext config.json when keyring is not installed or
fails to initialise (common on headless / CI environments).
"""

try:
    import keyring as _kr
    # Probe to confirm the backend is actually functional.
    _kr.get_password("_sf_probe", "_sf_probe")
    _HAS_KEYRING = True
except Exception:
    _HAS_KEYRING = False

_SERVICE = "SponsorFinder"


def has_keyring() -> bool:
    """Return True if the OS keychain is available and functional."""
    return _HAS_KEYRING


def get_key(name: str) -> str:
    """Retrieve an API key. Returns '' if not set."""
    if _HAS_KEYRING:
        try:
            return _kr.get_password(_SERVICE, name) or ""
        except Exception:
            pass
    from export import load_config
    return load_config().get("api_keys", {}).get(name, "")


def set_key(name: str, value: str) -> None:
    """Store an API key. Pass '' to clear/delete it."""
    if _HAS_KEYRING:
        try:
            if value:
                _kr.set_password(_SERVICE, name, value)
            else:
                try:
                    _kr.delete_password(_SERVICE, name)
                except Exception:
                    pass
            return
        except Exception:
            pass
    # Fallback: plaintext config.json
    from export import load_config, save_config
    cfg = load_config()
    cfg.setdefault("api_keys", {})[name] = value
    save_config(cfg)


def storage_label(name: str) -> str:
    """Short human-readable description of where this key is stored."""
    if _HAS_KEYRING:
        try:
            val = _kr.get_password(_SERVICE, name)
            return "Stored in OS keychain" if val else "Not set"
        except Exception:
            pass
    from export import load_config
    val = load_config().get("api_keys", {}).get(name, "")
    return "Stored in config.json (plaintext)" if val else "Not set"
