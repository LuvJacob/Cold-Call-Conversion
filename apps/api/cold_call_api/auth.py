"""Authentication and seller identity resolution (Lane C).

Enforces BOLA (Broken Object Level Authorization) protection by resolving
the authenticated `seller_id` and ensuring all storage queries filter by it.

Modes (`AUTH_MODE`):
- ``jwt``: the seller is the verified ``sub`` (or ``seller_id``) claim of a signed
  Bearer token. Signature, expiry and algorithm are always checked. Fails closed.
- ``dev``: local development only. Accepts the ``X-Seller-ID`` header or falls back
  to ``DEFAULT_DEV_SELLER_ID``. Never use in a deployed environment.
"""

from __future__ import annotations

import logging
from typing import Annotated

import jwt
from fastapi import Header, HTTPException, status

from cold_call_api.config import settings

logger = logging.getLogger("cold_call_api.auth")


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_jwt_seller_id(token: str) -> str:
    """Return the seller id from a verified JWT, or raise 401."""
    if not settings.jwt_secret:
        # Misconfiguration must never degrade into accepting unsigned tokens.
        logger.error("AUTH_MODE=jwt but JWT_SECRET is not configured; rejecting request")
        raise _unauthorized()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp"]},
        )
    except jwt.PyJWTError:
        logger.warning("Rejected invalid bearer token")
        raise _unauthorized() from None
    seller = claims.get("sub") or claims.get("seller_id")
    if not isinstance(seller, str) or not seller.strip() or len(seller) > 100:
        raise _unauthorized()
    return seller.strip()


async def get_current_seller_id(
    authorization: Annotated[str | None, Header()] = None,
    x_seller_id: Annotated[str | None, Header(alias="X-Seller-ID")] = None,
) -> str:
    """Dependency that resolves and returns the current seller_id."""
    if settings.auth_mode == "jwt":
        if authorization:
            parts = authorization.split()
            if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
                return verify_jwt_seller_id(parts[1])
        raise _unauthorized()

    if settings.auth_mode == "dev":
        if x_seller_id and x_seller_id.strip():
            return x_seller_id.strip()
        return settings.default_dev_seller_id

    # Unknown mode: fail closed.
    raise _unauthorized()
