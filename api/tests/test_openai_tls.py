from __future__ import annotations

from pathlib import Path

from api.backend.openai_tls import build_websocket_connection_options, resolve_tls_verify


def test_resolve_tls_verify_prefers_explicit_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "ca.pem"
    bundle.write_text("dummy", encoding="utf-8")
    verify = resolve_tls_verify(str(bundle))
    assert verify == str(bundle)


def test_resolve_tls_verify_falls_back_when_bundle_missing() -> None:
    verify = resolve_tls_verify("/tmp/does-not-exist-ca.pem")
    assert verify is True or isinstance(verify, str)


def test_websocket_options_include_ssl_context() -> None:
    opts = build_websocket_connection_options(True)
    assert "ssl" in opts
