"""
Console entry point for running the Driver Station server.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
from typing import Optional

from .. import protocol
from .app import ServerConfig, run_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FRC Driver Station remote control server")
    defaults = ServerConfig()
    parser.add_argument("--host", default="0.0.0.0", help="IP address to bind (default: 0.0.0.0)")
    parser.add_argument(
        "--port", type=int, default=protocol.DEFAULT_PORT, help=f"UDP port to bind (default: {protocol.DEFAULT_PORT})"
    )
    parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=defaults.heartbeat_timeout,
        help="Seconds before a missed heartbeat disables the robot",
    )
    parser.add_argument(
        "--status-interval",
        type=float,
        default=defaults.status_interval,
        help="Seconds between status broadcasts",
    )
    parser.add_argument(
        "--log-file",
        type=pathlib.Path,
        default=None,
        help="Optional path to log file (default: stdout only)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Minimum logging level (default: INFO)",
    )

    # FMS integration options
    parser.add_argument(
        "--use-fms",
        action="store_true",
        help="Use FMS protocol instead of keystroke control",
    )
    parser.add_argument(
        "--team-id",
        type=int,
        default=5987,
        help="Team number for FMS mode (default: 5987)",
    )
    parser.add_argument(
        "--alliance-station",
        type=str,
        default="R1",
        choices=["R1", "R2", "R3", "B1", "B2", "B3"],
        help="Alliance station for FMS mode (default: R1)",
    )
    parser.add_argument(
        "--ds-address",
        type=str,
        default="127.0.0.1",
        help="Driver Station address for FMS mode (default: 127.0.0.1)",
    )

    parser.add_argument(
        "--enable-stream",
        action="store_true",
        help="Enables the FFMPEG stream of the DriverStation"
    )
    parser.add_argument(
        "--enable-pipeline",
        action="store_true",
        help="Enables the OCR detection pipeline of the DS state(requires FFMPEG stream)"
    )
    return parser


def _configure_logging(level: str, log_file: Optional[pathlib.Path]) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(file_handler)
        logging.getLogger(__name__).info("Logging to %s", log_file)


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.log_level, args.log_file)

    config = ServerConfig(
        host=args.host,
        port=args.port,
        heartbeat_timeout=args.heartbeat_timeout,
        status_interval=args.status_interval,
        use_fms=args.use_fms,
        team_id=args.team_id,
        alliance_station=args.alliance_station,
        ds_address=args.ds_address,
        enable_stream=args.enable_stream,
        enable_pipeline=args.enable_pipeline
    )

    if config.enable_pipeline and not config.enable_stream:
        raise ValueError("pipline cannot be enabled while stream is disabled; pass --enable-stream parameter")

    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Server interrupted by user.")


if __name__ == "__main__":
    main()
