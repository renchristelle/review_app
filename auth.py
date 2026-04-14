"""Authentification simple — HMAC stateless cookie de session."""

from __future__ import annotations

import hashlib
import hmac


def make_session_token(secret: str, username: str) -> str:
    return hmac.new(secret.encode(), username.encode(), hashlib.sha256).hexdigest()


def verify_session_token(secret: str, username: str, token: str) -> bool:
    expected = make_session_token(secret, username)
    return hmac.compare_digest(expected, token)
