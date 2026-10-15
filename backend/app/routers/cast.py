from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..api_schemas.cast import (
    CastControlRequest,
    CastDeviceResponse,
    CastDevicesResponse,
    CastStartRequest,
    CastStatusResponse,
    CastStopResponse,
)
from ..api_schemas.player import PlayerStateResponse
from ..auth import get_current_user
from ..cast import service as cast_service
from ..cast.base import CastUnavailable, cast_device_id
from ..cast.manager import CAST_MANAGER
from ..db import get_db
from ..models import User
from ..player import engine as player_engine

router = APIRouter(prefix="/api/cast", tags=["cast"])


def _collect_devices(user_id: str, refresh: bool) -> tuple[bool, list[CastDeviceResponse], str]:
    """Return ``(available, devices, error)`` without raising for an empty LAN."""
    try:
        devices = CAST_MANAGER.list_devices(force=refresh)
    except CastUnavailable:
        return False, [], ""
    except Exception as exc:  # discovery is best-effort; surface the reason to the UI
        return True, [], str(exc)
    return True, [
        CastDeviceResponse(
            id=cast_device_id(user_id, d.id),
            name=d.label,
            kind=d.kind,
            model=d.model,
        )
        for d in devices
    ], ""


def cast_devices(user: User = Depends(get_current_user), refresh: bool = False):
    available, devices, error = _collect_devices(user.id, refresh)
    return CastDevicesResponse(available=available, devices=devices, error=error)


def cast_start(
    payload: CastStartRequest,
    request: Request,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    base_url = player_engine._public_base_url(request)
    return cast_service.start_cast(db, user, payload.device_id, base_url)


def cast_stop(user: User = Depends(get_current_user)):
    return CastStopResponse(ok=cast_service.stop_cast(user.id))


def cast_status(user: User = Depends(get_current_user)):
    info = cast_service.active_status(user.id)
    if not info:
        return CastStatusResponse()
    return CastStatusResponse(
        active=True,
        device_id=str(info.get("device_id") or ""),
        device_name=str(info.get("device_name") or ""),
        kind=str(info.get("kind") or ""),
        queue_item_id=str(info.get("queue_item_id") or ""),
        is_playing=bool(info.get("is_playing")),
        position_ms=int(info.get("position_ms") or 0),
        duration_ms=int(info.get("duration_ms") or 0),
        player_state=str(info.get("player_state") or ""),
        last_error=str(info.get("last_error") or ""),
    )


def cast_control(
    payload: CastControlRequest,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    action = (payload.action or "").strip().lower()
    if action == "stop":
        cast_service.stop_cast(user.id)
        return player_engine.state(db=db, user=user)
    return cast_service.control(
        db,
        user,
        action,
        position_ms=payload.position_ms,
        volume=payload.volume,
    )


router.add_api_route("/devices", cast_devices, methods=["GET"], response_model=CastDevicesResponse)
router.add_api_route("/start", cast_start, methods=["POST"], response_model=PlayerStateResponse)
router.add_api_route("/stop", cast_stop, methods=["POST"], response_model=CastStopResponse)
router.add_api_route("/status", cast_status, methods=["GET"], response_model=CastStatusResponse)
router.add_api_route("/control", cast_control, methods=["POST"], response_model=PlayerStateResponse)
