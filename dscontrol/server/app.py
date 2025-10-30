"""
Async UDP server responsible for mediating remote commands to the Driver Station.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .. import protocol
from .control_interface import DriverStationController, RobotMode
from .stream_server import start_ffmpeg_server
from .remote_window import DriverStationPipeline

_LOGGER = logging.getLogger(__name__)

ClientAddress = Tuple[str, int]


@dataclass
class ClientSession:
    client_id: str
    address: ClientAddress
    last_heartbeat: float = field(default_factory=lambda: time.time())

    def update_heartbeat(self) -> None:
        self.last_heartbeat = time.time()


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = protocol.DEFAULT_PORT
    heartbeat_timeout: float = protocol.HEARTBEAT_TIMEOUT_SECONDS
    status_interval: float = 0.1
    log_status_every: float = 5.0
    require_hello: bool = True
    use_fms: bool = False
    team_id: int = 5987
    alliance_station: str = "R1"
    ds_address: str = "127.0.0.1"
    enable_stream: bool = False
    enable_pipeline: bool = False


class DriverStationServer(asyncio.DatagramProtocol):
    """
    UDP-based server that enforces heartbeat and safety policies described in OVERVIEW.md.
    """

    def __init__(self, config: Optional[ServerConfig] = None) -> None:
        super().__init__()
        self.config = config or ServerConfig()
        self.controller = DriverStationController(
            use_fms=self.config.use_fms,
            team_id=self.config.team_id,
            alliance_station=self.config.alliance_station,
            ds_address=self.config.ds_address,
        )
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.sessions: Dict[str, ClientSession] = {}
        self.running = asyncio.Event()
        self.robot_state = "disabled"
        self.last_command_by: Optional[str] = None
        self.last_command_at: Optional[float] = None
        self._watchdog_task: Optional[asyncio.Task[None]] = None
        self._status_task: Optional[asyncio.Task[None]] = None
        self._status_log_deadline = time.time()
        if config.enable_pipeline:
            self.pipeline = DriverStationPipeline()

    # Lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=(self.config.host, self.config.port)
        )
        self.transport = transport
        self.running.set()
        _LOGGER.info("DriverStationServer listening on %s:%s", self.config.host, self.config.port)
        self._watchdog_task = asyncio.create_task(self._watchdog_loop(), name="watchdog-loop")
        self._status_task = asyncio.create_task(self._status_loop(), name="status-loop")
        if self.config.enable_stream:
            start_ffmpeg_server(self.config.host, self.config.port+1)
        if self.config.enable_pipeline:
            self.pipeline.start()
            # self.pipeline.show_live()

    async def wait_closed(self) -> None:
        if self.transport:
            await asyncio.sleep(0)  # let protocol settle
        if self._watchdog_task:
            await self._watchdog_task
        if self._status_task:
            await self._status_task

    def connection_lost(self, exc: Optional[Exception]) -> None:
        _LOGGER.warning("Transport connection lost: %s", exc)
        self.running.clear()

    async def close(self) -> None:
        self.running.clear()
        if self._watchdog_task:
            self._watchdog_task.cancel()
        if self._status_task:
            self._status_task.cancel()
        if self.transport:
            self.transport.close()
        if self.config.enable_pipeline:
            self.pipeline.stop()

    # DatagramProtocol callbacks -------------------------------------------

    def datagram_received(self, data: bytes, addr: ClientAddress) -> None:
        try:
            message = protocol.ProtocolMessage.from_json(data)
        except protocol.ProtocolError as exc:
            _LOGGER.error("Invalid packet from %s:%s: %s", addr[0], addr[1], exc)
            self._send(protocol.make_error(str(exc)), addr)
            return

        handlers = {
            protocol.MessageType.HELLO: self._handle_hello,
            protocol.MessageType.HEARTBEAT: self._handle_heartbeat,
            protocol.MessageType.COMMAND: self._handle_command,
        }
        handler = handlers.get(message.type)
        if handler:
            handler(message.payload, addr)
        elif message.type == protocol.MessageType.STATUS:
            _LOGGER.debug("Ignoring STATUS message from client (server authoritative).")
        elif message.type == protocol.MessageType.ERROR:
            _LOGGER.warning("Client reported error: %s", message.payload.get("error"))

    # Message handlers -----------------------------------------------------

    def _handle_hello(self, payload: Dict[str, object], addr: ClientAddress) -> None:
        client_id = self._extract_client_id(payload, addr)
        if not client_id:
            return

        session = self.sessions.get(client_id)
        if session:
            _LOGGER.info("Client %s refreshed HELLO from %s:%s", client_id, *addr)
            session.address = addr
            session.update_heartbeat()
        else:
            _LOGGER.info("Client %s registered from %s:%s", client_id, *addr)
            self.sessions[client_id] = ClientSession(client_id=client_id, address=addr)

        self._send_status(addr)

    def _handle_heartbeat(self, payload: Dict[str, object], addr: ClientAddress) -> None:
        client_id = self._extract_client_id(payload, addr)
        if not client_id:
            return

        session = self.sessions.get(client_id)
        if not session:
            if self.config.require_hello:
                _LOGGER.warning("Heartbeat from unknown client_id=%s (%s:%s)", client_id, *addr)
                self._send(protocol.make_error("Send HELLO before HEARTBEAT"), addr)
                return
            session = ClientSession(client_id, addr)
            self.sessions[client_id] = session

        session.address = addr
        session.update_heartbeat()

    def _handle_command(self, payload: Dict[str, object], addr: ClientAddress) -> None:
        client_id = self._extract_client_id(payload, addr)
        if not client_id:
            return

        if client_id not in self.sessions:
            _LOGGER.warning("Command rejected from unregistered client %s", client_id)
            self._send(protocol.make_error("Client not registered; send HELLO first"), addr)
            return

        command_str = payload.get("command")
        try:
            command = protocol.CommandType(command_str)
        except Exception:
            _LOGGER.warning("Invalid command '%s' from %s", command_str, client_id)
            self._send(protocol.make_error("Unknown command"), addr)
            return

        self._apply_command(command, client_id)

    # Command execution ----------------------------------------------------

    def _apply_command(self, command: protocol.CommandType, client_id: str) -> None:
        if command == protocol.CommandType.ENABLE:
            result = self.controller.enable()
            if result.success:
                self.robot_state = "enabled"
        elif command == protocol.CommandType.ESTOP:
            result = self.controller.estop()
            self.robot_state = "estop"
        elif command == protocol.CommandType.TELEOP:
            self.controller.set_mode(RobotMode.TELEOP)
        elif command == protocol.CommandType.AUTO:
            self.controller.set_mode(RobotMode.AUTO)
        elif command == protocol.CommandType.PRACTICE:
            self.controller.set_mode(RobotMode.PRACTICE)
        elif command == protocol.CommandType.TEST:
            self.controller.set_mode(RobotMode.TEST)
        else:
            result = self.controller.disable()
            self.robot_state = "disabled"

        self.last_command_by = client_id
        self.last_command_at = time.time()
        _LOGGER.info(
            "Applied command %s from %s (backend=%s success=%s)",
            command.value,
            client_id,
            result.backend,
            result.success,
        )

        if not result.success:
            _LOGGER.warning("Command %s from %s failed: %s", command.value, client_id, result.message)
        self._broadcast_status()

    # Background loops -----------------------------------------------------

    async def _watchdog_loop(self) -> None:
        try:
            while self.running.is_set():
                await asyncio.sleep(self.config.heartbeat_timeout / 2)
                now = time.time()
                timed_out = [
                    cid
                    for cid, session in self.sessions.items()
                    if now - session.last_heartbeat > self.config.heartbeat_timeout
                ]
                for cid in timed_out:
                    _LOGGER.warning("Client %s timed out; removing session", cid)
                    self.sessions.pop(cid, None)

                if self.robot_state == "enabled" and (timed_out or not self.sessions):
                    _LOGGER.error("Heartbeat loss/no clients detected, disabling robot for safety")
                    self._apply_command(protocol.CommandType.DISABLE, client_id="watchdog")
        except asyncio.CancelledError:
            pass

    async def _status_loop(self) -> None:
        try:
            while self.running.is_set():
                self._broadcast_status()
                await asyncio.sleep(self.config.status_interval)
        except asyncio.CancelledError:
            pass

    # Status helpers -------------------------------------------------------

    def _broadcast_status(self) -> None:
        if not self.sessions:
            if time.time() >= self._status_log_deadline:
                _LOGGER.debug("No connected clients; skipping broadcast.")
                self._status_log_deadline = time.time() + self.config.log_status_every
            return

        message = protocol.make_status(self._status_report())
        for session in list(self.sessions.values()):
            self._send(message, session.address)

    def _send_status(self, addr: ClientAddress) -> None:
        message = protocol.make_status(self._status_report())
        self._send(message, addr)

    def _status_report(self) -> protocol.StatusReport:
        report = protocol.StatusReport(
            robot_state=self.robot_state,
            last_command_by=self.last_command_by,
            last_command_at=self.last_command_at,
            connected_clients=len(self.sessions),
            ds_state=""
        )
        if self.config.enable_pipeline:
            report.ds_state = self.pipeline.get_outputs().ds_state
        return report

    # Utility --------------------------------------------------------------

    def _extract_client_id(self, payload: Dict[str, object], addr: ClientAddress) -> Optional[str]:
        client_id = payload.get("client_id")
        if not isinstance(client_id, str):
            _LOGGER.error("Missing or invalid client_id from %s:%s", addr[0], addr[1])
            self._send(protocol.make_error("client_id required"), addr)
            return None
        return client_id

    def _send(self, message: protocol.ProtocolMessage, addr: ClientAddress) -> None:
        if not self.transport:
            _LOGGER.error("Attempted to send without active transport")
            return
        self.transport.sendto(message.to_json(), addr)


async def run_server(config: Optional[ServerConfig] = None) -> None:
    """
    Convenience entry point that starts the server and keeps it running until interrupted.
    """
    server = DriverStationServer(config)
    await server.start()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_stop() -> None:
        if not stop_event.is_set():
            stop_event.set()

    for sig_name in ("SIGTERM", "SIGINT"):
        try:
            import signal

            loop.add_signal_handler(getattr(signal, sig_name), _handle_stop)
        except (ImportError, AttributeError, NotImplementedError):
            pass

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        _LOGGER.info("Server coroutine cancelled; shutting down.")
    finally:
        await server.close()
        await server.wait_closed()
