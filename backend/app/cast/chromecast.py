"""Chromecast renderer support.

Everything here degrades gracefully: the module can be imported (and the app
can start) without ``pychromecast`` installed. The heavy import only happens
inside :func:`_load_pychromecast`, which raises :class:`CastUnavailable` when the
package is missing.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
from uuid import UUID

from .base import (
    CastDevice,
    CastDeviceUnreachable,
    CastUnavailable,
    RendererStatus,
)

LOG = logging.getLogger("helix.cast.chromecast")


def _load_pychromecast():
    try:
        import pychromecast  # type: ignore

        return pychromecast
    except Exception as exc:  # pragma: no cover - depends on the environment
        raise CastUnavailable(
            "pychromecast is not installed; Chromecast support is unavailable."
        ) from exc


def available() -> bool:
    try:
        _load_pychromecast()
        return True
    except CastUnavailable:
        return False


def discover(timeout: float = 5.0) -> list[CastDevice]:
    """Return the Chromecasts visible on the LAN.

    Uses a raw ``CastBrowser`` rather than ``pychromecast.get_chromecasts`` so
    listing devices never opens a control connection to each one (slow, and a
    single sleeping speaker can fail the whole sweep). Connections are opened
    lazily only when a device is actually used.
    """
    _load_pychromecast()
    import zeroconf
    from pychromecast.discovery import CastBrowser, SimpleCastListener

    zconf = zeroconf.Zeroconf()
    browser = CastBrowser(SimpleCastListener(), zconf)
    try:
        browser.start_discovery()
        time.sleep(max(1.0, float(timeout)))
        infos = list(browser.devices.values())
    finally:
        try:
            browser.stop_discovery()
        except Exception:  # pragma: no cover - best-effort cleanup
            LOG.debug("chromecast discovery cleanup failed", exc_info=True)

    devices: list[CastDevice] = []
    for info in infos:
        try:
            devices.append(
                CastDevice(
                    id=str(info.uuid),
                    name=info.friendly_name or "",
                    kind="chromecast",
                    model=info.model_name or "",
                    host=info.host or "",
                    port=int(info.port or 8009),
                    cast_type=info.cast_type or "",
                )
            )
        except Exception:  # pragma: no cover - defensive
            LOG.debug("skipping malformed chromecast info: %r", info, exc_info=True)
    return devices


class ChromecastTarget:
    """Drive a single Chromecast through pychromecast."""

    kind = "chromecast"

    def __init__(self, device: CastDevice) -> None:
        self.device = device
        self._cast = None

    # -- connection ---------------------------------------------------------

    def connect(self, timeout: float = 10.0) -> None:
        if self._cast is not None:
            return
        pychromecast = _load_pychromecast()
        try:
            cast_uuid = UUID(self.device.id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise CastDeviceUnreachable(
                f"Invalid Chromecast id {self.device.id!r}"
            ) from exc
        host = (self.device.host or "").strip()
        if not host:
            raise CastDeviceUnreachable(f"No host known for {self.device.label}")
        try:
            cast = pychromecast.get_chromecast_from_host(
                (
                    host,
                    int(self.device.port or 8009),
                    cast_uuid,
                    self.device.model or None,
                    self.device.name or None,
                )
            )
            cast.wait(timeout=timeout)
        except Exception as exc:
            self._cast = None
            raise CastDeviceUnreachable(
                f"Could not reach {self.device.label}: {exc}"
            ) from exc
        self._cast = cast

    @property
    def _media(self):
        self.connect()
        return self._cast.media_controller

    # -- renderer surface ---------------------------------------------------

    def play_url(
        self,
        url: str,
        *,
        content_type: str = "audio/mpeg",
        title: str = "",
        artist: str = "",
        art_url: str = "",
        position_s: float = 0.0,
        autoplay: bool = True,
    ) -> None:
        mc = self._media
        start = float(position_s) if position_s and position_s > 0 else None
        try:
            mc.play_media(
                url,
                content_type or "audio/mpeg",
                title=(title or f"{artist}".strip() or None),
                thumb=art_url or None,
                current_time=start,
                autoplay=bool(autoplay),
                stream_type="BUFFERED",
            )
            try:
                mc.block_until_active(timeout=15)
            except Exception:  # pragma: no cover - can throw for paused loads
                LOG.debug("block_until_active timed out for %s", self.device.label)
        except Exception as exc:
            raise CastDeviceUnreachable(
                f"Failed to load media on {self.device.label}: {exc}"
            ) from exc

    def pause(self) -> None:
        self._media.pause()

    def resume(self) -> None:
        self._media.play()

    def stop(self) -> None:
        try:
            self._media.stop()
        except Exception:
            LOG.debug("stop failed for %s", self.device.label, exc_info=True)

    def seek(self, position_s: float) -> None:
        self._media.seek(max(0.0, float(position_s)))

    def set_volume(self, level: float) -> None:
        self.connect()
        self._cast.set_volume(max(0.0, min(1.0, float(level))))

    def status(self) -> RendererStatus:
        mc = self._media
        try:
            mc.update_status()
        except Exception:
            LOG.debug("update_status failed for %s", self.device.label, exc_info=True)
        st = getattr(mc, "status", None)
        if st is None:
            return RendererStatus()

        current = getattr(st, "current_time", 0.0) or 0.0
        try:
            adjusted = getattr(st, "adjusted_current_time", None)
            if adjusted is not None:
                current = adjusted
        except Exception:  # pragma: no cover - defensive
            pass

        duration = getattr(st, "duration", None)
        volume = getattr(st, "volume_level", None)
        idle_reason = getattr(st, "idle_reason", None)
        return RendererStatus(
            player_state=str(getattr(st, "player_state", "") or "UNKNOWN"),
            current_time=float(current or 0.0),
            duration=(float(duration) if duration is not None else None),
            content_id=str(getattr(st, "content_id", "") or ""),
            idle_reason=(str(idle_reason) if idle_reason else None),
            volume_level=(float(volume) if volume is not None else None),
        )

    def disconnect(self) -> None:
        cast = self._cast
        self._cast = None
        if cast is not None:
            try:
                cast.disconnect(timeout=5)
            except Exception:
                LOG.debug(
                    "disconnect failed for %s", self.device.label, exc_info=True
                )
