"""
Interactive command-line interface for the DSControl client.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Optional

from .. import protocol
from .app import ClientConfig, RemoteClient

_LOGGER = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remote control client for the FRC Driver Station")
    parser.add_argument("--host", default="10.59.87.210", help="Server hostname or IP (default: 10.59.87.210)")
    parser.add_argument(
        "--port", type=int, default=protocol.DEFAULT_PORT, help=f"Server UDP port (default: {protocol.DEFAULT_PORT})"
    )
    parser.add_argument("--client-id", default="client", help="Identifier advertised to the server")
    parser.add_argument(
        "--command",
        choices=[protocol.CommandType.ENABLE.value, protocol.CommandType.DISABLE.value, protocol.CommandType.ESTOP.value],
        help="Send a single command and exit",
    )
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--heartbeat-interval", type=float, default=protocol.HEARTBEAT_INTERVAL_SECONDS)
    return parser


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )


def _format_status(report: protocol.StatusReport) -> str:
    last_by = report.last_command_by or "n/a"
    last_at = f"{report.last_command_at:.3f}s" if report.last_command_at else "n/a"
    return (
        f"State: {report.robot_state:<8} | last cmd by: {last_by:<12} | "
        f"last at: {last_at:<10} | connected clients: {report.connected_clients}"
    )


async def _interactive_shell(client: RemoteClient) -> None:
    loop = asyncio.get_running_loop()
    print("Commands: enable | disable | estop | status | quit")
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        command = line.strip().lower()
        if command in {"quit", "exit"}:
            print("Exiting client...")
            break
        if command == "status":
            if client.last_status:
                print(_format_status(client.last_status))
            else:
                print("No status received yet.")
            continue

        command_map = {
            protocol.CommandType.ENABLE.value: protocol.CommandType.ENABLE,
            protocol.CommandType.DISABLE.value: protocol.CommandType.DISABLE,
            protocol.CommandType.ESTOP.value: protocol.CommandType.ESTOP,
        }
        if command in command_map:
            try:
                client.send_command(command_map[command])
            except RuntimeError as exc:
                print(f"Failed to send command: {exc}")
        else:
            print("Unknown command. Available: enable | disable | estop | status | quit")


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.log_level)

    latest_status: Optional[protocol.StatusReport] = None

    def handle_status(report: protocol.StatusReport) -> None:
        nonlocal latest_status
        latest_status = report
        print(_format_status(report))

    def handle_error(message: str) -> None:
        print(f"[server] {message}")

    config = ClientConfig(
        server_host=args.host,
        server_port=args.port,
        client_id=args.client_id,
        heartbeat_interval=args.heartbeat_interval,
    )

    async def runner() -> None:
        client = RemoteClient(config, on_status=handle_status, on_error=handle_error)
        await client.connect()

        if args.command:
            client.send_command(protocol.CommandType(args.command))
            await asyncio.sleep(0.2)
        else:
            await _interactive_shell(client)

        await client.close()

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        _LOGGER.info("Client interrupted by user.")


if __name__ == "__main__":
    main()

