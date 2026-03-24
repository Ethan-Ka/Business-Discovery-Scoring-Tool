"""Simple cancellation token for async operations."""

import threading


class CancellationToken:
    """Thread-safe token to signal cancellation of long-running operations."""

    def __init__(self):
        """Initialize the cancellation token."""
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self):
        """Signal cancellation."""
        with self._lock:
            self._cancelled = True

    def is_cancelled(self) -> bool:
        """Check if cancellation has been signalled."""
        with self._lock:
            return self._cancelled

    def reset(self):
        """Reset the token for reuse."""
        with self._lock:
            self._cancelled = False
