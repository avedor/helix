from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from typing import Optional


class CastError(RuntimeError):
    """Base class for casting failures (reported to the client as 502)."""


class CastUnavailable(CastError):
    """The optional casting dependency is not installed."""


class CastDeviceUnreachable(CastError):
    """The renderer could not be reached or controlled."""


def cast_device_id(user_id: str, hardware_id: str) -> str:
    """Stable Helix device id for one user's renderer.

    ``PlaybackDevice.id`` is a global primary key, so two users casting to the
    same speaker must not collide. Namespacing a UUIDv5 with the owner keeps the
    real hardware id private while staying deterministic across restarts (which
    keeps the device picker and ownership checks stable).
    """
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"helix-cast:{user_id}:{hardware_id}"))


@dataclass
class CastDevice:
    """A discovered renderer, before it is bound to a user."""

    id: str  # hardware id (e.g. the Chromecast UUID)
    name: str
    kind: str = "chromecast"
    model: str = ""
    host: str = ""
    port: int = 8009
    cast_type: str = ""

    @property
    def label(self) -> str:
        return self.name or self.model or self.id


@dataclass
class RendererStatus:
    """A renderer's reported playback state at poll time."""

    player_state: str = "UNKNOWN"  # PLAYING | PAUSED | BUFFERING | IDLE | UNKNOWN
    current_time: float = 0.0
    duration: Optional[float] = None
    content_id: str = ""
    idle_reason: Optional[str] = None
    volume_level: Optional[float] = None

    @property
    def is_playing(self) -> bool:
        return self.player_state in {"PLAYING", "BUFFERING"}

    @property
    def is_idle(self) -> bool:
        return self.player_state in {"IDLE", "UNKNOWN"}

    @property
    def finished(self) -> bool:
        return self.is_idle and (self.idle_reason or "") == "FINISHED"
