from __future__ import annotations

from fastapi import APIRouter

from ..api_schemas.player import PlayerDevicesResponse
from ..player import engine as player_engine

router = APIRouter(prefix="/api/player", tags=["player"])

router.add_api_route("/devices", player_engine.player_devices, methods=["GET"], response_model=PlayerDevicesResponse)