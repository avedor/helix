"""Glue between the playback engine and a cast renderer.

A cast target plays an ordinary, signed ``/api/stream/{item}`` URL, so this
module only has to:

* mint that URL and hand it to the renderer,
* keep the engine's server-authoritative clock aligned with what the renderer
  is actually doing (the renderer cannot heartbeat to Helix), and
* advance the queue when the renderer finishes a track.

Ownership follows the existing model: while casting, ``active_device_id`` is the
cast's Helix device id, so every other client mirrors the clock instead of
emitting audio.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..devices import touch_or_create_device
from ..models import PlaybackSession, QueueItem, User
from ..stream_tokens import get_stream_secret, sign_stream_params, signed_stream_path
from .base import CastError, cast_device_id
from .manager import CAST_MANAGER, ActiveCast

LOG = logging.getLogger("helix.cast")

SYNC_INTERVAL_SECONDS = 2.0
# Ignore "finished" reports for a moment after we (re)load a track: the receiver
# briefly reports IDLE while switching, and we must not skip the new item.
END_GRACE_SECONDS = 5.0
MAX_FAILURES = 6


def _engine():
    from ..player import engine

    return engine


def _broadcast_state(user_id: str) -> None:
    try:
        from ..realtime import schedule_player_state_broadcast

        schedule_player_state_broadcast(user_id)
    except Exception:  # pragma: no cover - broadcast is best-effort
        LOG.debug("state broadcast failed for %s", user_id, exc_info=True)


def _broadcast_progress(user_id: str, item_id: str, position_ms: int, playing: bool) -> None:
    try:
        from ..realtime import schedule_player_progress_broadcast

        now = datetime.utcnow()
        stamp = int(now.timestamp() * 1000)
        schedule_player_progress_broadcast(
            user_id,
            queue_item_id=item_id,
            position_ms=max(0, int(position_ms)),
            position_updated_at_ms=stamp,
            server_time_ms=stamp,
        )
    except Exception:  # pragma: no cover - broadcast is best-effort
        LOG.debug("progress broadcast failed for %s", user_id, exc_info=True)


def _content_type(cur: QueueItem) -> str:
    try:
        from ..player.engine import _browser_audio_media_type

        path = str(getattr(cur, "inbound_path", "") or "")
        if path:
            return _browser_audio_media_type(path)
    except Exception:
        LOG.debug("content type lookup failed", exc_info=True)
    # Subsonic originals are usually mp3; the Default Media Receiver accepts it.
    return "audio/mpeg"


def _signed_url(db: Optional[Session], user_id: str, item_id: str, base_url: str) -> str:
    secret = get_stream_secret(db) if db is not None else None
    if not secret:
        own = SessionLocal()
        try:
            secret = get_stream_secret(own)
        finally:
            own.close()
    expires_at, signature = sign_stream_params(secret, item_id, user_id)
    path = signed_stream_path(item_id, user_id, expires_at, signature)
    return f"{base_url.rstrip('/')}{path}"


def _base_url_reachable(base_url: str) -> bool:
    lowered = (base_url or "").lower()
    return not ("//localhost" in lowered or "//127.0.0.1" in lowered or "//[::1]" in lowered)


# ---------------------------------------------------------------------------
# starting / stopping


def start_cast(db: Session, user: User, helix_device_id: str, base_url: str):
    """Hand the current queue item to a renderer and make it the active device."""
    engine = _engine()

    device = CAST_MANAGER.resolve(user.id, helix_device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Cast device not found on the network.")

    sess, _items, cur = engine._current_queue_item(db, user)
    if cur is None:
        raise HTTPException(status_code=400, detail="Nothing is playing.")

    if not _base_url_reachable(base_url):
        LOG.warning(
            "casting with a loopback base URL (%s); set HELIX_PUBLIC_BASE_URL so "
            "the renderer can reach Helix",
            base_url,
        )

    target = CAST_MANAGER.get_target(device)
    # Label the renderer as a playback device up front so clients can show and
    # target it while the cast settles.
    touch_or_create_device(db, user.id, cast_device_id(user.id, device.id), device.label, "cast")

    position_s = engine._effective_position_ms(sess, datetime.utcnow()) / 1000.0
    url = _signed_url(db, user.id, cur.id, base_url)
    try:
        target.play_url(
            url,
            content_type=_content_type(cur),
            title=cur.title or "",
            artist=cur.artist or "",
            art_url=cur.art_url or "",
            position_s=position_s,
            autoplay=bool(sess.is_playing),
        )
    except CastError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    helix_id = cast_device_id(user.id, device.id)
    sess.active_device_id = helix_id
    db.commit()

    CAST_MANAGER.set_active(
        ActiveCast(
            user_id=user.id,
            helix_device_id=helix_id,
            device=device,
            target=target,
            base_url=base_url.rstrip("/"),
            queue_item_id=cur.id,
            pushed_is_playing=bool(sess.is_playing),
            pushed_at=time.time(),
        )
    )
    _broadcast_state(user.id)
    return engine.state(db=db, user=user)


def stop_cast(user_id: str) -> bool:
    active = CAST_MANAGER.pop_active(user_id)
    if active is None:
        return False
    _release(active)
    return True


def _release(active: ActiveCast) -> None:
    """Clear ownership and tear down the renderer connection (never raises)."""
    try:
        active.target.stop()
    except Exception:
        LOG.debug("cast stop failed for %s", active.device.label, exc_info=True)
    try:
        active.target.disconnect()
    except Exception:
        LOG.debug("cast disconnect failed for %s", active.device.label, exc_info=True)

    db = SessionLocal()
    try:
        sess = db.get(PlaybackSession, active.user_id)
        if sess is not None and str(getattr(sess, "active_device_id", "") or "") == active.helix_device_id:
            sess.active_device_id = ""
            db.commit()
            _broadcast_state(active.user_id)
    except Exception:
        LOG.debug("clearing cast ownership failed", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ---------------------------------------------------------------------------
# remote control


def control(db: Session, user: User, action: str, *, position_ms: Optional[int] = None, volume: Optional[float] = None):
    """Apply a transport action to the active renderer and the server clock."""
    engine = _engine()
    active = CAST_MANAGER.active_for(user.id)
    if active is None:
        raise HTTPException(status_code=404, detail="No active cast session.")

    action = (action or "").strip().lower()
    new_playing: Optional[bool] = None
    try:
        if action == "pause":
            active.target.pause()
            new_playing = False
        elif action in ("play", "resume"):
            active.target.resume()
            new_playing = True
        elif action == "seek":
            active.target.seek(max(0, int(position_ms or 0)) / 1000.0)
        elif action == "volume":
            active.target.set_volume(float(volume or 0))
        elif action == "stop":
            stop_cast(active.user_id)
            return _engine().state(db=db, user=user)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown cast action {action!r}")
    except CastError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Mirror the command onto the server clock so viewers (and a later resume)
    # see the same position / play state the renderer is in.
    sess = engine._get_or_create_session(db, user.id)
    items = (
        db.execute(
            select(QueueItem)
            .where(QueueItem.session_user_id == user.id)
            .order_by(QueueItem.position.asc())
        )
        .scalars()
        .all()
    )
    cur = items[sess.current_index] if 0 <= sess.current_index < len(items) else None

    target_playing = None
    if action in ("play", "resume"):
        target_playing = True
    elif action == "pause":
        target_playing = False

    if target_playing is not None:
        sess.is_playing = target_playing
        if target_playing:
            if cur is not None:
                engine._anchor_position(sess, cur.id)
        else:
            engine._freeze_position(sess)
        active.pushed_is_playing = target_playing
    elif action == "seek" and cur is not None:
        engine._anchor_position(sess, cur.id, position_ms=int(position_ms or 0))
    db.commit()

    _broadcast_state(user.id)
    return engine.state(db=db, user=user)


def active_status(user_id: str) -> Optional[dict]:
    active = CAST_MANAGER.active_for(user_id)
    if active is None:
        return None
    info = {
        "device_id": active.helix_device_id,
        "device_name": active.device.label,
        "kind": active.device.kind,
        "queue_item_id": active.queue_item_id,
        "base_url": active.base_url,
        "last_error": active.last_error,
    }
    try:
        status = active.target.status()
        info.update(
            {
                "is_playing": status.is_playing,
                "position_ms": int(max(0.0, status.current_time) * 1000),
                "duration_ms": int(status.duration * 1000) if status.duration else 0,
                "player_state": status.player_state,
            }
        )
    except CastError as exc:
        info["last_error"] = str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        info["last_error"] = str(exc)
    return info


# ---------------------------------------------------------------------------
# background reconciliation


async def sync_active_casts() -> None:
    for active in CAST_MANAGER.all_active():
        try:
            await _sync_one(active)
        except Exception:  # pragma: no cover - one bad cast must not stop the loop
            LOG.exception("cast sync failed for user %s", active.user_id)


async def _sync_one(active: ActiveCast) -> None:
    engine = _engine()

    try:
        status = await asyncio.to_thread(active.target.status)
    except CastError as exc:
        active.last_error = str(exc)
        active.failures += 1
        if active.failures >= MAX_FAILURES:
            LOG.warning("dropping unreachable cast %s: %s", active.device.label, exc)
            await asyncio.to_thread(stop_cast, active.user_id)
        return
    except Exception as exc:  # pragma: no cover - defensive
        active.last_error = str(exc)
        active.failures += 1
        if active.failures >= MAX_FAILURES:
            await asyncio.to_thread(stop_cast, active.user_id)
        return
    active.failures = 0

    db = SessionLocal()
    outcome = "none"
    payload: dict = {}
    try:
        sess = db.get(PlaybackSession, active.user_id)
        user = db.get(User, active.user_id)
        if sess is None or user is None or str(getattr(sess, "active_device_id", "") or "") != active.helix_device_id:
            outcome = "stop"
        else:
            items = (
                db.execute(
                    select(QueueItem)
                    .where(QueueItem.session_user_id == active.user_id)
                    .order_by(QueueItem.position.asc())
                )
                .scalars()
                .all()
            )
            cur = items[sess.current_index] if 0 <= sess.current_index < len(items) else None
            if cur is None:
                outcome = "stop"
            else:
                _refresh_presence(db, active)

                item_changed = str(active.queue_item_id) != str(cur.id)
                recently_pushed = (time.time() - active.pushed_at) < END_GRACE_SECONDS
                if item_changed:
                    outcome = "push"
                    payload = {
                        "item_id": cur.id,
                        "position_ms": engine._effective_position_ms(sess, datetime.utcnow()),
                        "playing": bool(sess.is_playing),
                        "url": _signed_url(db, active.user_id, cur.id, active.base_url),
                        "content_type": _content_type(cur),
                        "title": cur.title or "",
                        "artist": cur.artist or "",
                        "art_url": cur.art_url or "",
                    }
                    active.queue_item_id = cur.id
                    active.pushed_is_playing = bool(sess.is_playing)
                    active.pushed_at = time.time()
                    active.dirty = False
                elif active.dirty:
                    # A first-party client seeked/scrubbed the session; push that
                    # onto the renderer before the renderer becomes authoritative
                    # again.
                    outcome = "reconcile"
                    payload = {
                        "item_id": cur.id,
                        "playing": bool(sess.is_playing),
                        "position_ms": engine._effective_position_ms(sess, datetime.utcnow()),
                    }
                    active.dirty = False
                    active.pushed_at = time.time()
                    active.pushed_is_playing = bool(sess.is_playing)
                elif (
                    status.finished
                    and bool(sess.is_playing)
                    and not recently_pushed
                ):
                    # Only advance when we expect playback: at the end of the
                    # queue ``is_playing`` is cleared, and the receiver keeps
                    # reporting FINISHED for the same item.
                    outcome = "advance"
                elif status.is_idle and recently_pushed:
                    # The receiver reports IDLE for a moment after LOAD.
                    outcome = "none"
                else:
                    outcome = "progress"
                    pos_ms = int(max(0.0, status.current_time) * 1000)
                    playing = status.is_playing
                    engine._anchor_position(sess, cur.id, position_ms=pos_ms)
                    sess.is_playing = playing
                    payload = {"item_id": cur.id, "position_ms": pos_ms, "playing": playing}
        db.commit()
    finally:
        db.close()

    if outcome == "stop":
        await asyncio.to_thread(stop_cast, active.user_id)
        return

    if outcome == "push":
        try:
            await asyncio.to_thread(
                active.target.play_url,
                payload["url"],
                content_type=payload["content_type"],
                title=payload["title"],
                artist=payload["artist"],
                art_url=payload["art_url"],
                position_s=payload["position_ms"] / 1000.0,
                autoplay=bool(payload["playing"]),
            )
        except CastError as exc:
            active.last_error = str(exc)
            LOG.warning("cast load failed for %s: %s", active.device.label, exc)
            return
        _broadcast_state(active.user_id)
        return

    if outcome == "reconcile":
        await _reconcile(active, status, payload)
        return

    if outcome == "advance":
        await _advance(active)
        return

    if outcome == "progress":
        _broadcast_progress(active.user_id, payload["item_id"], payload["position_ms"], bool(payload.get("playing")))


async def _reconcile(active: ActiveCast, status, payload: dict) -> None:
    """Push a client-originated session change (pause/seek/resume) to the renderer."""
    desired_playing = bool(payload.get("playing"))
    desired_ms = int(payload.get("position_ms") or 0)
    try:
        if desired_playing != status.is_playing:
            action = active.target.resume if desired_playing else active.target.pause
            await asyncio.to_thread(action)
        if abs(desired_ms - int(max(0.0, status.current_time) * 1000)) > 2000:
            await asyncio.to_thread(active.target.seek, max(0.0, desired_ms / 1000.0))
    except CastError as exc:
        active.last_error = str(exc)
        active.dirty = True  # retry on the next tick
        LOG.warning("cast reconcile failed for %s: %s", active.device.label, exc)
        return
    _broadcast_state(active.user_id)


def _refresh_presence(db: Session, active: ActiveCast) -> None:
    """Heartbeat the cast device row.

    The cast device has no client socket to ping, so without this its
    ``last_seen_at`` ages past ``ACTIVE_DEVICE_TTL_SECONDS`` and the session
    would release ownership out from under the renderer.
    """
    from ..models import PlaybackDevice

    row = db.get(PlaybackDevice, active.helix_device_id)
    if row is not None and row.user_id == active.user_id:
        row.last_seen_at = datetime.utcnow()


def _device_dict(active: ActiveCast) -> dict[str, str]:
    return {"id": active.helix_device_id, "name": active.device.label, "kind": "cast"}


def _engine_advance_after_end():
    from ..player.engine import advance_after_end

    return advance_after_end


async def _advance(active: ActiveCast) -> None:
    """Move the queue on when the renderer reports the track finished."""
    db = SessionLocal()
    try:
        user = db.get(User, active.user_id)
        if user is None:
            return
        await _engine_advance_after_end()(db, user, played_ms=None, device=_device_dict(active))
    except Exception:
        LOG.exception("cast advance failed for user %s", active.user_id)
    finally:
        db.close()


async def cast_sync_loop() -> None:
    LOG.info("cast sync loop started")
    while True:
        try:
            if CAST_MANAGER.all_active():
                await sync_active_casts()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - the loop must never die
            LOG.exception("cast sync loop error")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
