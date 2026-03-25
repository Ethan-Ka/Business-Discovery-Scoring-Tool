"""
Lightweight app-wide logger.

Call setup() once at startup (main.py).  Any module can then do:

    import logging
    log = logging.getLogger(__name__)
    log.info("something happened")

Writes to data/logs/app.log with rotation (1 MB × 3 backups = max ~3 MB on disk).
Console output goes to the root logger at WARNING+ unless debug mode is on.
"""

import logging
import logging.handlers
import os


_FILE_HANDLER_ATTR = "_sponsor_file_handler"


def setup(debug: bool = False, file_logging: bool = True) -> None:
    from paths import get_log_path

    level = logging.DEBUG if debug else logging.INFO

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — kept small automatically
    fh = None
    if file_logging:
        log_path = get_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=1 * 1024 * 1024,  # 1 MB
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        setattr(fh, _FILE_HANDLER_ATTR, True)

    # Console handler — warnings and above only (errors visible in terminal)
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid adding duplicate handlers if setup() is called more than once
    if fh and not any(getattr(h, _FILE_HANDLER_ATTR, False)
                      for h in root.handlers):
        root.addHandler(fh)
    if not any(isinstance(h, logging.StreamHandler) and not
               isinstance(h, logging.handlers.RotatingFileHandler)
               for h in root.handlers):
        root.addHandler(ch)


def set_debug(enabled: bool) -> None:
    """Adjust log level at runtime when the debug toggle is flipped."""
    logging.getLogger().setLevel(logging.DEBUG if enabled else logging.INFO)


def set_file_logging(enabled: bool) -> None:
    """Enable/disable rotating file logging at runtime."""
    from paths import get_log_path

    root = logging.getLogger()
    existing = [h for h in root.handlers if getattr(h, _FILE_HANDLER_ATTR, False)]
    if enabled:
        if existing:
            return
        log_path = get_log_path()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        fmt = logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=1 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        setattr(fh, _FILE_HANDLER_ATTR, True)
        root.addHandler(fh)
    else:
        for handler in existing:
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


def get_log_size_bytes() -> int:
    """Return current app log size in bytes, 0 if missing."""
    from paths import get_log_path

    path = get_log_path()
    return os.path.getsize(path) if os.path.exists(path) else 0


def clear_log_file() -> None:
    """Delete current app log and recreate an empty file if logging is enabled."""
    from paths import get_log_path

    path = get_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, _FILE_HANDLER_ATTR, False):
            try:
                handler.acquire()
                if handler.stream:
                    try:
                        handler.stream.close()
                    except Exception:
                        pass
                handler.stream = open(path, "a", encoding="utf-8")
            finally:
                try:
                    handler.release()
                except Exception:
                    pass
