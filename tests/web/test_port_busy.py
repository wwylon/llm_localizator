"""A port another server listens on is reported busy, also on Windows (M0, audit ops #16)."""

from __future__ import annotations

import socket

from llm_localizator.web.server import _LoopbackServer, _port_busy


def test_listening_port_is_busy_and_freed() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    try:
        assert _port_busy(port)
    finally:
        sock.close()
    assert not _port_busy(port)


def test_server_does_not_share_ports_on_windows() -> None:
    import os

    assert _LoopbackServer.allow_reuse_address is (os.name != "nt")
