from __future__ import annotations

from pydantic import BaseModel


class CastDeviceResponse(BaseModel):
    id: str  # the Helix cast device id (namespaced per user)
    name: str = ""
    kind: str = "chromecast"
    model: str = ""


class CastDevicesResponse(BaseModel):
    # False when the optional casting dependency is not installed; the UI can
    # then hide the "cast" section instead of showing an empty list.
    available: bool = True
    devices: list[CastDeviceResponse] = []
    error: str = ""


class CastStartRequest(BaseModel):
    device_id: str


class CastControlRequest(BaseModel):
    action: str  # play | pause | resume | stop | seek | volume
    position_ms: int = 0
    volume: float = 0.0


class CastStatusResponse(BaseModel):
    active: bool = False
    device_id: str = ""
    device_name: str = ""
    kind: str = ""
    queue_item_id: str = ""
    is_playing: bool = False
    position_ms: int = 0
    duration_ms: int = 0
    player_state: str = ""
    last_error: str = ""


class CastStopResponse(BaseModel):
    ok: bool
