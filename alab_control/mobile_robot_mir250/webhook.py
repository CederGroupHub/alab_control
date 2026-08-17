"""Receive Ability execution-state callbacks instead of polling for them.

``PUT /v2/programs/current`` accepts a ``webhook`` field, and the controller then PUTs
every execution state change to that URI as
``{"state": ..., "message": ..., "context": ...}``. Replying 200 keeps the subscription;
replying 404 unregisters it.

Use this rather than a Hooks subscription in the web UI. Hooks can be marked *critical*,
and a failed critical notification puts the robot into entity error and aborts the running
mission. The per-program webhook has no such coupling, so a listener that dies costs
observability and nothing else.

A webhook registered by one run outlives it. A dead listener then makes the controller
fault with "Unable to connect to program webhook server" on the *next* execution of
anything at all, which reads as a fault in whatever you were doing instead. So a listener
is registered per run and always cleared -- see ``session.clear_stale_webhook``.

    with WebhookListener() as listener:
        ability.load_program("Main", args, webhook_uri=listener.uri)
        ability.start()
        event = listener.wait_for(lambda e: e.state in IDLE_STATES, timeout=600)
"""

from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .clients import ABILITY_HOST

logger = logging.getLogger(__name__)

DEFAULT_PATH = "/ability"


@dataclass
class StateEvent:
    """One execution-state callback from the controller."""

    received_at: str
    elapsed_s: float
    state: str
    message: str
    context: str
    raw: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [f"{self.elapsed_s:7.2f}s  {self.state}"]
        if self.message:
            parts.append(f"message={self.message!r}")
        if self.context:
            parts.append(f"context={self.context!r}")
        return "  ".join(parts)


def local_ip_for(host: str = ABILITY_HOST) -> str:
    """The address of the interface that can reach the controller.

    The callback URI has to be an address the controller can dial back, so localhost is
    never right and a machine with several interfaces needs the one on the robot network.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def listener(self) -> "WebhookListener":
        return self.server.listener  # type: ignore[attr-defined]

    def _receive(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        try:
            payload = json.loads(body) if body else {}
        except ValueError:
            payload = {"unparsed_body": body}
        if not isinstance(payload, dict):
            payload = {"body": payload}
        self.listener._record(payload)
        # 200 keeps the subscription, 404 asks the controller to forget it.
        self.send_response(self.listener.reply_status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_PUT = _receive
    do_POST = _receive

    def do_GET(self) -> None:
        """A health endpoint, handy for checking reachability from the robot network."""
        body = json.dumps({"events": self.listener.count}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        """Silence the default stderr access log; callbacks are logged by the listener."""


class WebhookListener:
    """A small HTTP server that collects Ability state callbacks."""

    def __init__(
        self,
        port: int = 0,
        path: str = DEFAULT_PATH,
        *,
        host: str = ABILITY_HOST,
        on_event: Callable[[StateEvent], None] | None = None,
        echo: bool = False,
        reply_status: int = 200,
    ) -> None:
        self.path = path if path.startswith("/") else f"/{path}"
        self.on_event = on_event
        self.echo = echo
        self.reply_status = reply_status
        self.events: "queue.Queue[StateEvent]" = queue.Queue()
        self.history: list[StateEvent] = []
        self.count = 0
        self._started = time.monotonic()
        self._server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
        self._server.listener = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="webhook-listener", daemon=True
        )
        self.host = local_ip_for(host)
        self.port = self._server.server_address[1]

    @property
    def uri(self) -> str:
        return f"http://{self.host}:{self.port}{self.path}"

    def start(self) -> "WebhookListener":
        self._thread.start()
        self._started = time.monotonic()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "WebhookListener":
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def _record(self, payload: dict[str, Any]) -> None:
        event = StateEvent(
            received_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
            elapsed_s=round(time.monotonic() - self._started, 2),
            state=str(payload.get("state", "")),
            message=str(payload.get("message", "") or ""),
            context=str(payload.get("context", "") or ""),
            raw=payload,
        )
        self.count += 1
        self.history.append(event)
        self.events.put(event)
        if self.echo:
            logger.info("webhook %s", event)
        if self.on_event:
            self.on_event(event)

    def drain(self) -> list[StateEvent]:
        """Everything received since the last drain."""
        out: list[StateEvent] = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def next_event(self, timeout: float) -> StateEvent | None:
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_for(
        self, predicate: Callable[[StateEvent], bool], timeout: float
    ) -> StateEvent | None:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            event = self.next_event(remaining)
            if event is not None and predicate(event):
                return event
