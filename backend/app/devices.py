from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .models import PlaybackDevice


def touch_or_create_device(
    db: Session,
    user_id: str,
    device_id: str,
    name: str = "",
    kind: str = "",
) -> Optional[PlaybackDevice]:
    """Register or refresh this user's device identified by ``device_id``.

    Returns ``None`` when no id was supplied or when the id belongs to a
    different user (a client must never claim someone else's device). Callers
    are responsible for committing.
    """
    device_id = (device_id or "").strip()
    if not device_id or len(device_id) > 36:
        return None

    dev = db.get(PlaybackDevice, device_id)
    if dev and dev.user_id != user_id:
        return None

    clean_name = (name or "").strip()[:128]
    clean_kind = ((kind or "").strip()[:16] or "unknown")

    if dev is None:
        dev = PlaybackDevice(
            id=device_id,
            user_id=user_id,
            name=clean_name or "Helix device",
            kind=clean_kind,
        )
        db.add(dev)
    else:
        if clean_name:
            dev.name = clean_name
        if (kind or "").strip():
            dev.kind = clean_kind
    dev.last_seen_at = datetime.utcnow()
    return dev