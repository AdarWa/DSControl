"""
Async UDP client that communicates with the Driver Station server.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .. import protocol

_LOGGER = logging.getLogger(__name__)

StatusCallback = Callable[[protocol.StatusReport], None]
ErrorCallback = Callable[[str], None]

@dataclass
class ClientConfig:
    server_host: str = "127.0.0.1"
    server_port: int = protocol.DEFAULT_PORT
    client_id: str = "client"
    heartbeat_interval: float = protocol.HEARTBEAT_INTERVAL_SECONDS
    hello_retry_interval: float = 1.0

    def to_dict(self):
        return {
            "server_host": self.server_host,
            "server_port": self.server_port,
            "client_id": self.client_id,
            "heartbeat_interval": self.heartbeat_interval,
            "hello_retry_interval": self.hello_retry_interval
        }

DEFAULT_SETTINGS_FILENAME = "settings.json"
DEFAULT_SETTINGS_DICT = ClientConfig()

def read_settings(filename=DEFAULT_SETTINGS_FILENAME):
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        update_settings(DEFAULT_SETTINGS_DICT, filename)
        return DEFAULT_SETTINGS_DICT.to_dict()


def update_settings(client_config: ClientConfig, filename=DEFAULT_SETTINGS_FILENAME):
    with open(filename, "w") as f:
        config_dict = client_config.to_dict()
        json.dump(config_dict, f)
        return config_dict


class RemoteClient(asyncio.DatagramProtocol):
    """
    Implements the networking stack for a remote DS control client.
    """

    def __init__(
            self,
            config: ClientConfig,
            on_status: Optional[StatusCallback] = None,
            on_error: Optional[ErrorCallback] = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.on_status = on_status
        self.on_error = on_error
        self.transport: Optional[asyncio.DatagramTransport] = None
        self._connected = asyncio.Event()
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._hello_task: Optional[asyncio.Task[None]] = None
        self.last_status: Optional[protocol.StatusReport] = None
        self._last_hello = 0.0
        self._status_waiter: Optional[asyncio.Future[None]] = None

    # Lifecycle -------------------------------------------------------------

    async def connect(self) -> None:
        if self._running:
            return

        loop = asyncio.get_running_loop()
        self._status_waiter = loop.create_future()
        await loop.create_datagram_endpoint(
            lambda: self, remote_addr=(self.config.server_host, self.config.server_port)
        )
        await self._connected.wait()
        self._running = True
        try:
            await self._ping_server()
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
        if self._hello_task:
            self._hello_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._hello_task
        if self.transport:
            self.transport.close()
        self._status_waiter = None

    # DatagramProtocol overrides -------------------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        self._connected.set()
        self._hello_task = asyncio.create_task(self._hello_loop(), name="hello-loop")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="heartbeat-loop")
        _LOGGER.info(
            "Connected to server %s:%s as %s",
            self.config.server_host,
            self.config.server_port,
            self.config.client_id,
        )

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        try:
            message = protocol.ProtocolMessage.from_json(data)
        except protocol.ProtocolError as exc:
            _LOGGER.error("Malformed datagram from %s: %s", addr, exc)
            return

        if message.type == protocol.MessageType.STATUS:
            self._handle_status(message)
        elif message.type == protocol.MessageType.ERROR:
            error = message.payload.get("error", "Unknown error")
            _LOGGER.error("Server error: %s", error)
            if self.on_error:
                self.on_error(str(error))
        else:
            _LOGGER.debug("Received unexpected message type %s", message.type.value)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        _LOGGER.warning("Connection lost: %s", exc)
        self._running = False
        self._connected.clear()
        if self.on_error:
            self.on_error("Connection lost")

    # Networking helpers ---------------------------------------------------

    def send_command(self, command: protocol.CommandType) -> None:
        if not self.transport:
            raise RuntimeError("Client not connected")
        message = protocol.make_command(self.config.client_id, command)
        self.transport.sendto(message.to_json())
        _LOGGER.info("Sent %s command", command.value)

    # Handshake & heartbeat loops -----------------------------------------

    async def _hello_loop(self) -> None:
        try:
            while True:
                now = time.time()
                if now - self._last_hello >= self.config.hello_retry_interval:
                    self._send(protocol.make_hello(self.config.client_id))
                    self._last_hello = now
                await asyncio.sleep(self.config.hello_retry_interval)
        except asyncio.CancelledError:
            pass

    async def _heartbeat_loop(self) -> None:
        try:
            await asyncio.sleep(self.config.heartbeat_interval)
            while True:
                self._send(protocol.make_heartbeat(self.config.client_id))
                await asyncio.sleep(self.config.heartbeat_interval)
        except asyncio.CancelledError:
            pass

    # Message handlers -----------------------------------------------------

    def _handle_status(self, message: protocol.ProtocolMessage) -> None:
        payload = message.payload
        last_command_at_raw = payload.get("last_command_at")
        last_command_at = (
            float(last_command_at_raw)
            if isinstance(last_command_at_raw, (int, float))
            else None
        )
        connected_raw = payload.get("connected_clients", 0)
        try:
            connected_clients = int(connected_raw)
        except (TypeError, ValueError):
            connected_clients = 0

        report = protocol.StatusReport(
            robot_state=str(payload.get("robot_state", "unknown")),
            last_command_by=payload.get("last_command_by"),
            last_command_at=last_command_at,
            connected_clients=connected_clients,
            ds_state=payload.get("ds_state")
        )
        self.last_status = report
        if self._status_waiter and not self._status_waiter.done():
            self._status_waiter.set_result(None)
        if self.on_status:
            self.on_status(report)

    def _send(self, message: protocol.ProtocolMessage) -> None:
        if not self.transport:
            _LOGGER.error("Cannot send message; transport not ready")
            return
        self.transport.sendto(message.to_json())

    async def _ping_server(self, timeout: float = 1.0) -> None:
        if not self.transport:
            raise RuntimeError("Client not connected")
        waiter = self._status_waiter
        if not waiter or waiter.done():
            loop = asyncio.get_running_loop()
            waiter = loop.create_future()
            self._status_waiter = waiter
        self._send(protocol.make_hello(self.config.client_id))
        try:
            await asyncio.wait_for(asyncio.shield(waiter), timeout=timeout)
        except asyncio.TimeoutError as exc:
            waiter.cancel()
            raise TimeoutError("Timed out waiting for status response from server") from exc
        finally:
            self._status_waiter = None
