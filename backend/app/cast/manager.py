from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from . import chromecast as _chromecast
from .base import CastDevice, CastError, CastUnavailable, cast_device_id

LOG = logging.getLogger("helix.cast")

# Re-running an mDNS sweep on every request would be slow and noisy, so the
# device list is cached briefly. Discovery itself is the expensive part.
DISCOVERY_TTL_SECONDS = 30.0
DISCOVERY_TIMEOUT_SECONDS = 5.0


@dataclass
class ActiveCast:
    """A renderer currently playing on behalf of one Helix user."""

    user_id: str
    helix_device_id: str
    device: CastDevice
    target: object  # ChromecastTarget (duck-typed)
    base_url: str = ""
    # Last item pushed to the renderer, so a queue change triggers a reload.
    queue_item_id: str = ""
    pushed_is_playing: bool = False
    pushed_at: float = 0.0
    # Set when a first-party client changed session state (seek/pause/next) and
    # the renderer must be re-synced from the server before it is authoritative
    # again.
    dirty: bool = False
    last_error: str = ""
    failures: int = 0


class CastManager:
    """Process-wide discovery + active-cast registry.

    The manager is intentionally free of FastAPI/SQLAlchemy imports so it can be
    exercised (and imported) in isolation. Ownership of the DB session and of
    the engine clock lives in ``service.py``.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, CastDevice] = {}
        self._devices_at = 0.0
        self._targets: dict[str, object] = {}
        self._active: dict[str, ActiveCast] = {}

    # -- capability ---------------------------------------------------------

    def available(self) -> bool:
        return _chromecast.available()

    # -- discovery ----------------------------------------------------------

    def list_devices(self, *, force: bool = False) -> list[CastDevice]:
        with self._lock:
            now = time.time()
            fresh = (now - self._devices_at) < DISCOVERY_TTL_SECONDS
            if not force and self._devices_at and fresh:
                return list(self._devices.values())
        try:
            devices = _chromecast.discover(timeout=DISCOVERY_TIMEOUT_SECONDS)
        except CastUnavailable:
            raise
        except Exception as exc:
            LOG.warning("cast discovery failed: %s", exc)
            raise CastError(f"Cast discovery failed: {exc}") from exc
        with self._lock:
            self._devices = {d.id: d for d in devices}
            self._devices_at = time.time()
        return devices

    def cached_devices(self) -> list[CastDevice]:
        with self._lock:
            return list(self._devices.values())

    def resolve(self, user_id: str, helix_device_id: str) -> Optional[CastDevice]:
        """Find the discovered device behind a Helix cast device id."""
        helix_device_id = (helix_device_id or "").strip()
        if not helix_device_id:
            return None

        def _match(devices: list[CastDevice]) -> Optional[CastDevice]:
            for d in devices:
                if cast_device_id(user_id, d.id) == helix_device_id:
                    return d
            return None

        found = _match(self.cached_devices())
        if found is not None:
            return found
        # Freshly started server, or discovery has not run yet.
        try:
            self.list_devices(force=True)
        except CastError:
            return None
        return _match(self.cached_devices())

    # -- targets ------------------------------------------------------------

    def get_target(self, device: CastDevice) -> object:
        with self._lock:
            target = self._targets.get(device.id)
            if target is None:
                target = _chromecast.ChromecastTarget(device)
                self._targets[device.id] = target
            return target

    # -- active casts -------------------------------------------------------

    def active_for(self, user_id: str) -> Optional[ActiveCast]:
        with self._lock:
            return self._active.get(user_id)

    def active_by_device(self, helix_device_id: str) -> Optional[ActiveCast]:
        helix_device_id = (helix_device_id or "").strip()
        if not helix_device_id:
            return None
        with self._lock:
            for active in self._active.values():
                if active.helix_device_id == helix_device_id:
                    return active
        return None

    def set_active(self, active: ActiveCast) -> None:
        with self._lock:
            self._active[active.user_id] = active

    def pop_active(self, user_id: str) -> Optional[ActiveCast]:
        with self._lock:
            return self._active.pop(user_id, None)

    def mark_dirty(self, user_id: str) -> None:
        with self._lock:
            active = self._active.get(user_id)
            if active is not None:
                active.dirty = True

    def all_active(self) -> list[ActiveCast]:
        with self._lock:
            return list(self._active.values())


CAST_MANAGER = CastManager()
