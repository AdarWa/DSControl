# DSControl - Remote FRC Driver Station Control

A lightweight, UDP-based system that lets laptop clients safely enable, disable, or e-stop a robot by talking to a server running on the official FRC Driver Station PC. Safety, low latency, and resilience are the guiding principles—if communications stop, the robot is forced safe immediately.

This setup is great for teams that use linux personal laptops and thus does not have the official Driver Station.

## Components

- **Server (`dscontrol.server`)**
  - Runs on the Driver Station PC.
  - Exposes a UDP endpoint that accepts `HELLO`, `HEARTBEAT`, and `COMMAND` messages.
  - Applies enable/disable/e-stop actions through `DriverStationController`, which prefers `pydirectinput-rgx` but falls back to a log-only simulation mode.
  - Broadcasts periodic `STATUS` frames to every connected client, including the active robot state and the last command metadata.
  - Enforces a watchdog: if every authorised client misses two heartbeats (250 ms timeout by default) or all clients disconnect, it disables the robot automatically.

- **Client (`dscontrol.client`)**
  - Connects to the server, sends `HELLO` retries and 10 Hz heartbeats.
  - Provides an interactive CLI (`dscontrol.client.cli`) for operators to send `enable`, `disable`, or `estop` commands and view live status updates.
  - Provides a GUI (`dscontrol.client.gui`) for operators to send `enable`, `disable`, or `estop` commands and view live status updates.
  - Can run in one-shot mode to send a single command from automation scripts.

Both components share the JSON-over-UDP protocol defined in `dscontrol/protocol.py`.

## Getting Started

### Requirements

- [uv](https://docs.astral.sh/uv/) 0.8 or newer (manages Python, virtual envs, and scripts).
- Python 3.10+ (uv will bootstrap/download if missing).
- Optional: [`pydirectinput-rgx`](https://pypi.org/project/pydirectinput-rgx) for real Driver Station key automation on Windows (`uv sync --extra server-control`).
- Optional: `fleet` and `pynput` for client GUI (`uv sync --extra gui-control`).
### Environment setup with uv

```bash
# inside the repository
uv sync                       # resolves deps and creates .venv (if needed)
```

- `uv sync` reads `pyproject.toml` and prepares a managed environment (`.venv/`).
- To include the optional automation backend: `uv sync --extra server-control`.
- To include the optional GUI client: `uv sync --extra gui-control`.

### Running the server

```bash
uv run dscontrol-server
```

Key behaviours:

- First client performs `HELLO` registration.
- A watchdog task enforces the heartbeat timeout; losing every client disables the robot.
- `DriverStationController` logs actions when automation backends are unavailable, enabling safe testing on non-Windows machines.

### Running the client

```bash
uv run dscontrol-cli --host 10.59.87.200 --port 8750 --client-id practice-laptop
```

Then use the interactive commands:

```
enable | disable | estop | status | quit
```

For scripting:

```bash
uv run dscontrol-cli --host 192.168.1.42 --command disable
```

Tip: append `--` to pass additional arguments directly to the scripts, e.g. `uv run dscontrol-server -- --help`.

### Running the GUI client

```
uv run dscontrol-gui
```

## Protocol Snapshot

Every UDP frame is UTF-8 JSON with a `type` field (`HELLO`, `HEARTBEAT`, `COMMAND`, `STATUS`, `ERROR`). The common helpers for building and parsing these messages live in `dscontrol/protocol.py`. Clients send 100 ms heartbeats; the server broadcasts status at 100 ms by default.

## Logging & Safety

- Server logs default to stdout but can mirror to a file via `--log-file`.
- All command applications note the client ID and backend success state.
- Watchdog and heartbeat failures emit warnings and immediately issue a disable command (`watchdog` pseudo-client).
- Control falls back to simulation if no automation backend exists, keeping development safe.

## Todo

- Integrate a slim VNC/web preview.
