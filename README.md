# DSControl — Remote FRC Driver Station Control

A lightweight, UDP-based system that lets laptop clients safely enable, disable, or e-stop a robot by talking to a server running on the official FRC Driver Station PC. Safety, low latency, and resilience are the guiding principles—if communications stop, the robot is forced safe immediately.

This setup is great for teams that use linux personal laptops and thus does not have the official Driver Station.

## Components

- **Server (`dscontrol.server`)**
  - Runs on the Driver Station PC.
  - Exposes a UDP endpoint that accepts `HELLO`, `HEARTBEAT`, and `COMMAND` messages.
  - Applies enable/disable/e-stop actions through `DriverStationController`, which prefers `pyautogui` but falls back to a log-only simulation mode.
  - Broadcasts periodic `STATUS` frames to every connected client, including the active robot state and the last command metadata.
  - Enforces a watchdog: if every authorised client misses two heartbeats (250 ms timeout by default) or all clients disconnect, it disables the robot automatically.

- **Client (`dscontrol.client`)**
  - Connects to the server, sends `HELLO` retries and 10 Hz heartbeats.
  - Provides an interactive CLI (`dscontrol-client`) for operators to send `enable`, `disable`, or `estop` commands and view live status updates.
  - Can run in one-shot mode to send a single command from automation scripts.

Both components share the JSON-over-UDP protocol defined in `dscontrol/protocol.py`.

## Getting Started

### Requirements

- [uv](https://docs.astral.sh/uv/) 0.8 or newer (manages Python, virtual envs, and scripts).
- Python 3.10+ (uv will bootstrap/download if missing).
- Optional: [`pyautogui`](https://pyautogui.readthedocs.io/) for real Driver Station key automation on Windows (`uv sync --extra server-control`).

### Environment setup with uv

```bash
# inside the repository
uv sync                       # resolves deps and creates .venv (if needed)
```

- `uv sync` reads `pyproject.toml` and prepares a managed environment (`.venv/`).
- To include the optional automation backend: `uv sync --extra server-control`.

### Running the server

```bash
uv run dscontrol-server --host 0.0.0.0 --port 8750 \
  --heartbeat-timeout 0.25 --status-interval 0.1 \
  --log-file logs/server.log --log-level INFO
```

Key behaviours:

- First client performs `HELLO` registration.
- A watchdog task enforces the heartbeat timeout; losing every client disables the robot.
- `DriverStationController` logs actions when automation backends are unavailable, enabling safe testing on non-Windows machines.

### Running the client

```bash
uv run dscontrol-client --host 10.59.87.200 --port 8750 --client-id practice-laptop
```

Then use the interactive commands:

```
enable | disable | estop | status | quit
```

For scripting:

```bash
uv run dscontrol-client --host 192.168.1.42 --command disable
```

Tip: append `--` to pass additional arguments directly to the scripts, e.g. `uv run dscontrol-server -- --help`.

## Protocol Snapshot

Every UDP frame is UTF-8 JSON with a `type` field (`HELLO`, `HEARTBEAT`, `COMMAND`, `STATUS`, `ERROR`). The common helpers for building and parsing these messages live in `dscontrol/protocol.py`. Clients send 100 ms heartbeats; the server broadcasts status at 100 ms by default.

## Logging & Safety

- Server logs default to stdout but can mirror to a file via `--log-file`.
- All command applications note the client ID and backend success state.
- Watchdog and heartbeat failures emit warnings and immediately issue a disable command (`watchdog` pseudo-client).
- Control falls back to simulation if no automation backend exists, keeping development safe.

## Extensibility Ideas

- Swap the automation backend for a Windows-specific `SendInput` implementation.
- Layer TCP alongside UDP for guaranteed command delivery.
- Integrate a slim VNC/web preview (stubs can live next to `DriverStationController`).

## Testing Notes

Local end-to-end execution requires UDP sockets; the provided development sandbox disallows opening sockets, so live server/client tests could not be run here. The orchestration logic has been validated by reasoning and by ensuring commands run under Python 3.12. When running on real hardware, verify:

1. Heartbeat loss forces a disable within 250 ms.
2. Manual Driver Station keyboards still override network commands.
3. Optional automation backend (`pyautogui` or Windows `SendInput`) issues the correct keystrokes.
