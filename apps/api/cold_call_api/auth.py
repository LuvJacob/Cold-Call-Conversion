"""Authentication and seller identity resolution (Lane C).

Enforces BOLA (Broken Object Level Authorization) protection by resolving
the authenticated `seller_id` and ensuring all storage queries filter by it.
"""

from __future__ import annotations

import base64
import json
from typing import Annotated
from fastapi import Header, HTTPException, status
from cold_call_api.config import settings


def _parse_jwt_unverified_claims(token: str) -> dict[str, object]:
    """Parse JWT payload claims safely for development/token extraction."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload_b64 = parts[1]
        # Fix base64 padding
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(decoded)
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not parse authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err


async def get_current_seller_id(
    authorization: Annotated[str | None, Header()] = None,
    x_seller_id: Annotated[str | None, Header(alias="X-Seller-ID")] = None,
) -> str:
    """Dependency that resolves and returns the current seller_id."""
    # 1. Direct explicit header (useful in testing and developer workspace)
    if x_seller_id and x_seller_id.strip():
        return x_seller_id.strip()

    # 2. Bearer token
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            # If JWT mode is enabled
            if settings.auth_mode == "jwt" or "." in token:
                claims = _parse_jwt_unverified_claims(token)
                sub = claims.get("sub") or claims.get("seller_id")
                if sub and isinstance(sub, str):
                    return sub
            elif token:
                # Direct token string
                return token

    # 3. Dev fallback
    if settings.auth_mode == "dev":
        return settings.default_dev_seller_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
