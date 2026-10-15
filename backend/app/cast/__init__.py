"""Server-side cast/renderer support (T3).

Helix can hand its server-authoritative playback to a LAN renderer (starting
with Chromecast) instead of only mirroring it between first-party clients. A
cast target becomes a normal :class:`~app.models.PlaybackDevice` of kind
``"cast"``: it claims ``active_device_id``, and a background loop keeps the
server clock aligned with what the renderer is actually playing (and advances
the queue when a track ends).

The optional ``pychromecast`` dependency is imported lazily so the rest of the
app runs unchanged when casting is unavailable.
"""

from __future__ import annotations

from .base import CastError, CastUnavailable

__all__ = ["cast_available", "CastError", "CastUnavailable"]


def cast_available() -> bool:
    """Whether the Chromecast dependency is importable in this environment."""
    from .manager import CAST_MANAGER

    return CAST_MANAGER.available()
