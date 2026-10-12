from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..security import secrets_compare
from ..station_providers import get_station_provider
from ..station_providers.models import StationContext

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


class SongResult(BaseModel):
    title: str
    artist: str
    album: str = ""


class SimilarResponse(BaseModel):
    songs: list[SongResult]


def _clean(value: str) -> str:
    return " ".join((value or "").strip().split())


def _require_api_token(request: Request) -> None:
    expected = (os.getenv("HELIX_RECOMMENDATIONS_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Recommendations endpoint not configured")
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        token = auth[7:]
    else:
        token = auth
    token = token.strip()
    if not secrets_compare(token, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/similar", response_model=SimilarResponse)
async def similar_songs(
    request: Request,
    type: str = "track",
    title: str = "",
    artist: str = "",
    album: str = "",
    limit: int = 20,
):
    _require_api_token(request)

    rec_type = (type or "track").lower()
    limit = max(1, min(100, int(limit or 20)))

    config: dict[str, Any] = {}
    station_type = "similar_artist"

    if rec_type == "track":
        station_type = "song_radio"
        config["seed_title"] = _clean(title)
        config["seed_artist"] = _clean(artist)
        if album:
            config["seed_album"] = _clean(album)
    elif rec_type == "artist":
        station_type = "similar_artist"
        config["seed_artist"] = _clean(artist or title)
    elif rec_type == "album":
        station_type = "similar_artist"
        # Use album artist; fallback to title context if artist missing
        config["seed_artist"] = _clean(artist or title)
    else:
        raise HTTPException(status_code=400, detail="type must be one of track, album, artist")

    provider = get_station_provider(station_type)

    # Build minimal stateless context
    context = StationContext(
        user_id="navidrome-proxy",
        station_id="navidrome-proxy",
        station_name="Navidrome Similar",
        station_type=station_type,
        config=config,
        recent_tracks=[],
        recent_artists=[],
        queued_tracks=[],
        already_selected=[],
    )

    try:
        results = await asyncio.wait_for(
            provider.next_tracks(context, limit),
            timeout=float(os.getenv("HELIX_RECOMMENDATIONS_TIMEOUT_S", "20")),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to generate recommendations: {exc}") from exc

    songs = []
    for r in results[:limit]:
        if not r or not _clean(r.title) or not _clean(r.artist):
            continue
        songs.append(
            SongResult(
                title=_clean(r.title),
                artist=_clean(r.artist),
                album=_clean(r.album or ""),
            )
        )

    return SimilarResponse(songs=songs)
