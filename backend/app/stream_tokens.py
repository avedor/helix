"""Short-lived signed URLs for cookieless stream access.

First-party Helix clients authenticate to ``/api/stream/{queue_item_id}`` with the
``mr_session`` cookie. Renderers that cannot attach cookies (a Chromecast/AirPlay
helper, or a browser ``<audio>`` embedded by another origin) instead present a
signed query string minted by ``GET /api/stream/{queue_item_id}/url``.

The scheme is deliberately small and dependency-light so it can be unit-tested
without the FastAPI app: the signature is an HMAC-SHA256 over
``"{item_id}:{user_id}:{expires_at}"``. Verification recomputes the HMAC with a
constant-time compare and rejects expired links. The signing secret is resolved
by :func:`get_stream_secret`, which prefers ``HELIX_STREAM_SECRET`` and otherwise
persists a generated secret in the settings table so existing links keep working
across restarts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime
from typing import Optional, Tuple

# Signed links are short-lived: long enough to start a track and let a renderer
# buffer/seek, short enough that a leaked URL ages out quickly.
DEFAULT_TTL_SECONDS = 6 * 60 * 60

# Settings key holding the generated signing secret (used when no env var is set).
_SECRET_SETTING_KEY = "stream_url_secret"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _message(item_id: str, user_id: str, expires_at: int) -> bytes:
    return f"{item_id}:{user_id}:{expires_at}".encode("utf-8")


def _sign(secret: str, item_id: str, user_id: str, expires_at: int) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        _message(item_id, user_id, expires_at),
        hashlib.sha256,
    ).digest()
    return _b64(digest)


def sign_stream_params(
    secret: str,
    item_id: str,
    user_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: Optional[int] = None,
) -> Tuple[int, str]:
    """Return ``(expires_at, signature)`` for a stream URL.

    ``expires_at`` is a Unix timestamp in seconds; ``signature`` is the URL-safe
    HMAC binding the item, the user, and that expiry.
    """
    if not secret:
        raise ValueError("stream signing secret is required")
    issued = int(now if now is not None else time.time())
    expires_at = issued + max(1, int(ttl_seconds))
    return expires_at, _sign(secret, item_id, user_id, expires_at)


def verify_stream_params(
    secret: str,
    item_id: str,
    user_id: str,
    expires_at: object,
    signature: Optional[str],
    *,
    now: Optional[int] = None,
) -> bool:
    """Validate a signed stream URL, returning ``False`` for anything invalid."""
    if not secret or not signature:
        return False
    try:
        exp = int(expires_at)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    current = int(now if now is not None else time.time())
    if exp < current:
        return False
    expected = _sign(secret, item_id, user_id, exp)
    return hmac.compare_digest(expected, signature)


def signed_stream_path(item_id: str, user_id: str, expires_at: int, signature: str) -> str:
    """Relative signed path for a stream item (no scheme/host)."""
    from urllib.parse import quote, urlencode

    query = urlencode({"uid": user_id, "exp": int(expires_at), "sig": signature})
    return f"/api/stream/{quote(item_id, safe='')}?{query}"


def _decode_secret(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return raw.strip()
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        inner = value.get("value")
        if isinstance(inner, str):
            return inner.strip()
    return ""


def get_stream_secret(db) -> str:
    """Resolve the stream signing secret, generating and persisting one if needed.

    ``HELIX_STREAM_SECRET`` wins when set (useful for multi-host deployments that
    must agree on signatures). Otherwise a random secret is stored in the
    ``settings`` table on first use so it is stable across restarts.
    """
    env = (os.getenv("HELIX_STREAM_SECRET") or "").strip()
    if env:
        return env

    # Imported lazily so this module (and its unit tests) stay free of the ORM.
    from .models import Setting

    row = db.get(Setting, _SECRET_SETTING_KEY)
    if row is not None:
        existing = _decode_secret(row.value_json)
        if existing:
            return existing

    secret = secrets.token_urlsafe(48)
    if row is None:
        db.add(Setting(key=_SECRET_SETTING_KEY, value_json=json.dumps(secret)))
    else:
        row.value_json = json.dumps(secret)
        row.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        # Another worker may have generated the secret first; adopt theirs.
        persisted = _read_persisted_secret(db)
        if persisted:
            return persisted
        raise
    return secret


def _read_persisted_secret(db) -> str:
    from .models import Setting

    row = db.get(Setting, _SECRET_SETTING_KEY)
    return _decode_secret(row.value_json) if row is not None else ""
