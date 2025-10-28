"""
Protocol primitives shared between the DSControl server and client.

Messages are encoded as UTF-8 JSON strings transported over UDP/TCP. Each
message contains a `type` field identifying the payload kind, and an
optional `payload` dictionary with message-specific data.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, TypedDict

# Transport defaults -------------------------------------------------------

DEFAULT_PORT = 8750
HEARTBEAT_INTERVAL_SECONDS = 0.1
HEARTBEAT_TIMEOUT_SECONDS = 0.25

# Shared Constants ---------------------------------------------------------
COLOR_DS_STATES_MAPPING = {
    "No Robot Communication": "#FF3B30",   # bright red - critical error
    "Teleoperated Enabled": "#34C759",     # green - active/ready
    "Teleoperated Disabled": "#FFD60A",    # yellow - idle but ready
    "Autonomous Enabled": "#0A84FF",       # blue - active auto mode
    "Autonomous Disabled": "#5AC8FA",      # light blue - standby auto mode
    "No Robot Code": "#FF9500"             # orange - missing program
}

DS_STATES = COLOR_DS_STATES_MAPPING.keys()


class MessageType(str, Enum):
    HELLO = "HELLO"
    HEARTBEAT = "HEARTBEAT"
    COMMAND = "COMMAND"
    STATUS = "STATUS"
    ERROR = "ERROR"


class CommandType(str, Enum):
    ENABLE = "enable"
    DISABLE = "disable"
    ESTOP = "estop"
    TELEOP = "teleop"
    AUTO = "auto"
    PRACTICE = "practice"
    TEST = "test"


class ProtocolError(Exception):
    """Raised when a protocol frame cannot be parsed or is invalid."""


class MessageDict(TypedDict, total=False):
    type: str
    payload: Dict[str, Any]


@dataclass
class ProtocolMessage:
    """Represents a protocol frame exchanged between client and server."""

    type: MessageType
    payload: Dict[str, Any]

    def to_json(self) -> bytes:
        return json.dumps({"type": self.type.value, "payload": self.payload}).encode("utf-8")

    @staticmethod
    def from_json(data: bytes) -> "ProtocolMessage":
        try:
            raw: MessageDict = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError("Invalid JSON payload") from exc

        msg_type_str = raw.get("type")
        if not msg_type_str:
            raise ProtocolError("Missing message type")

        try:
            msg_type = MessageType(msg_type_str)
        except ValueError as exc:
            raise ProtocolError(f"Unknown message type '{msg_type_str}'") from exc

        payload = raw.get("payload") or {}
        if not isinstance(payload, dict):
            raise ProtocolError("Payload must be an object")

        return ProtocolMessage(type=msg_type, payload=payload)


@dataclass
class StatusReport:
    """Current server-side driver station state."""

    robot_state: str
    last_command_by: Optional[str]
    last_command_at: Optional[float]
    connected_clients: int
    ds_state: Optional[str]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "robot_state": self.robot_state,
            "last_command_by": self.last_command_by,
            "last_command_at": self.last_command_at,
            "connected_clients": self.connected_clients,
            "ds_state": self.ds_state,
            "timestamp": time.time(),
        }


def make_hello(client_id: str) -> ProtocolMessage:
    payload: Dict[str, Any] = {"client_id": client_id}
    return ProtocolMessage(MessageType.HELLO, payload)


def make_heartbeat(client_id: str) -> ProtocolMessage:
    return ProtocolMessage(MessageType.HEARTBEAT, {"client_id": client_id, "timestamp": time.time()})


def make_command(client_id: str, command: CommandType) -> ProtocolMessage:
    return ProtocolMessage(
        MessageType.COMMAND, {"client_id": client_id, "timestamp": time.time(), "command": command.value}
    )


def make_status(report: StatusReport) -> ProtocolMessage:
    return ProtocolMessage(MessageType.STATUS, report.to_payload())


def make_error(message: str) -> ProtocolMessage:
    return ProtocolMessage(MessageType.ERROR, {"error": message, "timestamp": time.time()})

