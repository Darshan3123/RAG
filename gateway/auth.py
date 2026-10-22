# =========================================================================
# gateway/auth.py
# Internal Service Authentication for GeMBridge REST Gateway (Phase 1)
# =========================================================================
import datetime
import hmac
from typing import Optional
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from config import settings
from utils.logger import get_logger

log = get_logger("gateway_auth")

# OpenAPI header scheme: displays "Authorize 🔒" dialog in Swagger UI (/docs)
internal_key_header_scheme = APIKeyHeader(
    name="X-Internal-Key",
    auto_error=False,
    description="Internal service authentication key for Django-to-Gateway communication.",
)


def require_internal_key(
    request: Request,
    api_key: Optional[str] = Security(internal_key_header_scheme),
) -> str:
    """
    Enforces that incoming requests provide a valid X-Internal-Key header.
    Validates against GATEWAY_INTERNAL_KEY and GATEWAY_INTERNAL_KEY_PREVIOUS
    using constant-time comparison (hmac.compare_digest) for zero-downtime key rotation.
    """
    valid_keys = [
        k for k in (settings.GATEWAY_INTERNAL_KEY, settings.GATEWAY_INTERNAL_KEY_PREVIOUS)
        if k and k.strip()
    ]

    # Safety check: if no internal key is configured in the environment, deny all requests
    if not valid_keys:
        log.error("CRITICAL: No GATEWAY_INTERNAL_KEY configured in environment. Denying request.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gateway internal authentication keys are not configured.",
        )

    client_ip = request.client.host if request.client else "unknown"

    if not api_key:
        log.warning(f"Unauthorized request without X-Internal-Key from IP {client_ip} to {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required 'X-Internal-Key' header.",
        )

    # Constant-time comparison across current and previous active keys
    is_valid = any(hmac.compare_digest(api_key.strip(), key.strip()) for key in valid_keys)

    if not is_valid:
        log.warning(f"Invalid X-Internal-Key rejected from IP {client_ip} to {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal key.",
        )

    return api_key
