from __future__ import annotations

import logging
import ssl
from pathlib import Path
from typing import Any

import certifi

LOG = logging.getLogger("grumpyadmin.openai_tls")


def resolve_tls_verify(ca_bundle: str) -> str | bool:
    """Resolve TLS verification source for OpenAI clients.

    Priority:
    1) explicit OPENAI_CA_BUNDLE path (if valid file)
    2) certifi CA bundle
    3) system default verification (True)
    """
    candidate = ca_bundle.strip()
    if candidate:
        bundle_path = Path(candidate).expanduser()
        if bundle_path.is_file():
            return str(bundle_path)
        LOG.warning("OPENAI_CA_BUNDLE not found at %s; falling back to certifi/system trust", bundle_path)

    try:
        return certifi.where()
    except Exception:
        LOG.warning("certifi bundle unavailable; using system TLS trust store")
        return True


def build_websocket_connection_options(verify: str | bool) -> dict[str, Any]:
    """Build websocket options with explicit SSL context for Realtime."""
    if isinstance(verify, str):
        return {"ssl": ssl.create_default_context(cafile=verify)}
    if verify is True:
        return {"ssl": ssl.create_default_context()}
    return {}
