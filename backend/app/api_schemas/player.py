from __future__ import annotations

from typing import Optional
from pydantic import BaseModel

from .stations import StationResponse


class PlayerQueueItem(BaseModel):
    id: str
    position: int
    title: str
    artist: str
    album: str = ""
    duration_ms: int = 0
    # Progressive streaming support (web UI seek clamping).
    seekable_ms: int = 0
    available_bytes: int = 0
    is_final: bool = False
    art_url: str = ""
    source: str = "subsonic"
    subsonic_song_id: str = ""
    yt_video_id: str = ""
    yt_browse_id: str = ""
    mb_recording_id: str = ""
    mb_artist_id: str = ""
    is_playable: bool = False
    error: str = ""


class PlayerStateResponse(BaseModel):
    is_playing: bool
    current_index: int
    now_playing: Optional[PlayerQueueItem] = None
    queue: list[PlayerQueueItem] = []
    autoplay_enabled: bool = True
    active_station_id: str = ""
    active_station: Optional[StationResponse] = None
    # Server-authoritative playback clock. Clients derive the effective position:
    # position_ms + (is_playing ? (server_now - position_updated_at_ms) : 0),
    # where server_now is reconstructed from server_time_ms + local offset.
    position_ms: int = 0
    position_updated_at_ms: int = 0
    server_time_ms: int = 0
    active_device_id: str = ""


class PlayerPlayTrackRequest(BaseModel):
    # Prefer passing rich metadata from the UI; recording MBID is optional.
    recording_id: Optional[str] = None
    title: str
    artist: str
    album: Optional[str] = None
    duration_ms: Optional[int] = None
    art_url: Optional[str] = None
    # Primary id for YT Music tracks
    yt_video_id: Optional[str] = None
    ytmusic_url: Optional[str] = None



class PlayerPlayPlaylistRequest(BaseModel):
    # Playlist identifier. Use "liked" for the system Liked Songs playlist.
    playlist_id: str
    # When true, the backend expands the playlist and randomizes the queue order.
    shuffle: bool = False

class PlayerPlayAlbumRequest(BaseModel):
    # YT Music album identifier (browseId). Blank is allowed for Subsonic albums.
    browse_id: str = ""
    # Subsonic album id, used when playing library albums from search.
    subsonic_album_id: Optional[str] = None
    source: Optional[str] = None
    # Optional metadata for better UX/fallback.
    title: Optional[str] = None
    artist: Optional[str] = None
    art_url: Optional[str] = None


class PlayerJumpRequest(BaseModel):
    index: int


class PlayerQueueAppendAlbumRequest(BaseModel):
    browse_id: str = ""
    subsonic_album_id: Optional[str] = None
    source: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    art_url: Optional[str] = None


class PlayerQueueAppendTrackRequest(BaseModel):
    recording_id: Optional[str] = None
    title: str
    artist: str
    album: Optional[str] = None
    duration_ms: Optional[int] = None
    art_url: Optional[str] = None
    yt_video_id: Optional[str] = None
    ytmusic_url: Optional[str] = None


class PlayerQueueReorderRequest(BaseModel):
    # Ordered queue item ids. Items not included because they were appended during
    # the drag are preserved at the end in existing order.
    item_ids: list[str] = []


class PlayerRemoveQueueItemResponse(BaseModel):
    ok: bool = True


class PlayerHistoryItem(BaseModel):
    id: str
    queue_item_id: str
    title: str
    artist: str
    album: str = ""
    duration_ms: int = 0
    art_url: str = ""
    subsonic_song_id: str = ""
    yt_video_id: str = ""
    yt_browse_id: str = ""
    mb_recording_id: str = ""
    mb_artist_id: str = ""
    station_id: str = ""
    source: str = "subsonic"
    event: str = "skipped"
    reason: str = ""
    played_ms: int = 0
    created_at: str


class PlayerHistoryResponse(BaseModel):
    limit: int
    offset: int = 0
    total: int = 0
    has_more: bool = False
    items: list[PlayerHistoryItem] = []


class PlayerPositionRequest(BaseModel):
    queue_item_id: Optional[str] = None
    position_ms: int = 0


class PlayerSeekRequest(BaseModel):
    position_ms: int = 0


class PlaybackDeviceResponse(BaseModel):
    id: str
    name: str = ""
    kind: str = "unknown"
    last_seen_at: str = ""
    is_active: bool = False


class PlayerDevicesResponse(BaseModel):
    active_device_id: str = ""
    devices: list[PlaybackDeviceResponse] = []


class PlayerActionRequest(BaseModel):
    position_ms: Optional[int] = None


class PlayerReplayRequest(BaseModel):
    history_id: str
    position_ms: Optional[int] = None

class AutoplaySetRequest(BaseModel):
    enabled: bool
