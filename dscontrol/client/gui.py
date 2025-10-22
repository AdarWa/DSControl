"""
Graphical client built with Flet for interacting with the Driver Station server.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import threading
from typing import Optional

import flet as ft
import requests
from PIL import Image
from pynput import keyboard

COLOR_RED = "#D32F2F"
COLOR_GREEN = "#43A047"
COLOR_WHITE = "#FFFFFF"
COLOR_RED_ACCENT = "#C62828"
COLOR_CARD_BG = "rgba(69,90,100,0.06)"
NO_CONNECTION_COLOR = ft.Colors.YELLOW_400

from .. import protocol
from .app import ClientConfig, RemoteClient, DEFAULT_SETTINGS_DICT, read_settings, update_settings


def _format_timestamp(value: Optional[float]) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromtimestamp(value).strftime("%H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return f"{value:.3f}"

def mjpeg_to_base64(url, stop_event: Optional[threading.Event] = None):
    with requests.get(url, stream=True) as stream:
        bytes_buffer = b""
        for chunk in stream.iter_content(chunk_size=1024):
            if stop_event and stop_event.is_set():
                return
            bytes_buffer += chunk
            a = bytes_buffer.find(b'\xff\xd8')  # start of JPEG
            b = bytes_buffer.find(b'\xff\xd9')  # end of JPEG
            if a != -1 and b != -1:
                jpg = bytes_buffer[a:b+2]
                bytes_buffer = bytes_buffer[b+2:]
                img = Image.open(BytesIO(jpg))
                with BytesIO() as output:
                    img.save(output, format="PNG")
                    yield base64.b64encode(output.getvalue()).decode()
                if stop_event and stop_event.is_set():
                    return

@dataclass
class _UiState:
    connected: bool = False
    client_label: str = ""
    last_status: Optional[protocol.StatusReport] = None

class ClientGuiApp:

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.loop = asyncio.get_running_loop()
        self.client: Optional[RemoteClient] = None
        self.state = _UiState()

        self.status_queue: asyncio.Queue[protocol.StatusReport] = asyncio.Queue()
        self.error_queue: asyncio.Queue[str] = asyncio.Queue()

        self._status_task: Optional[asyncio.Task[None]] = None
        self._error_task: Optional[asyncio.Task[None]] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._pressed_keys: set[str] = set()
        self._active_hotkeys: set[str] = set()

        self.settings = read_settings()

        # Controls ---------------------------------------------------------
        self.host_field = ft.TextField(label="Server host", value=self.settings["server_host"])
        self.port_field = ft.TextField(label="Port", value=str(self.settings["server_port"]), width=120)
        self.client_id_field = ft.TextField(label="Client ID", value=self.settings["client_id"], width=200)

        self.connect_button = ft.ElevatedButton(text="Connect", icon="play_arrow", on_click=self._on_connect_click)
        self.enable_button = ft.FilledButton(text="Enable", icon="play_circle", on_click=self._make_command_handler(protocol.CommandType.ENABLE))
        self.disable_button = ft.FilledButton(text="Disable", icon="stop_circle", on_click=self._make_command_handler(protocol.CommandType.DISABLE))
        self.estop_button = ft.FilledButton(
            text="E-Stop",
            icon="power_settings_new",
            style=ft.ButtonStyle(color=COLOR_WHITE, bgcolor=COLOR_RED_ACCENT),
            on_click=self._make_command_handler(protocol.CommandType.ESTOP),
        )

        self.status_header = ft.Text("Disconnected", color=COLOR_RED, size=16, weight=ft.FontWeight.BOLD)
        self.robot_state_text = ft.Text("-", size=25, no_wrap=True, weight=ft.FontWeight.BOLD,color=NO_CONNECTION_COLOR)
        self.last_command_text = ft.Text("Last command: -")
        self.connected_clients_text = ft.Text("Connected clients: -")

        self.message_banner = ft.Text("", visible=False)

        self.video_image = ft.Image(expand=True, opacity=0.0, src_base64="dummy")
        self.stream_checkbox = ft.Checkbox(label="Enable stream", value=False, disabled=True, on_change=self._on_stream_toggle)

        self._stream_running = False
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_stop_event = threading.Event()

    async def initialize(self) -> None:
        self.page.title = "DSControl Client"
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.page.vertical_alignment = ft.MainAxisAlignment.START
        self.page.padding = 24

        self.enable_button.disabled = True
        self.disable_button.disabled = True
        self.estop_button.disabled = True

        controls = [
            ft.Text("Remote Driver Station", size=22, weight=ft.FontWeight.BOLD),
            ft.ResponsiveRow(
                [
                    ft.Container(self.host_field, col={"xs": 12, "md": 6}),
                    ft.Container(self.port_field, col={"xs": 6, "md": 2}),
                    ft.Container(self.client_id_field, col={"xs": 6, "md": 4}),
                ],
                spacing=12,
            ),
            ft.Row([self.connect_button]),
            ft.Container(
                ft.Column(
                    [
                        self.status_header,
                        self.robot_state_text,
                        self.last_command_text,
                        self.connected_clients_text,
                    ],
                    tight=True,
                ),
                padding=16,
                width=700,
                bgcolor=COLOR_CARD_BG,
                border_radius=8,
            ),
            ft.Row([self.enable_button, self.disable_button, self.estop_button], spacing=16),
            ft.Row(
                [
                    ft.Text("Stream", size=18, weight=ft.FontWeight.BOLD),
                    self.stream_checkbox,
                ],
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            self.video_image,
            self.message_banner,
        ]

        self.page.add(ft.Column(controls, tight=True, spacing=18))
        self.page.update()

        self.page.on_disconnect = lambda _: asyncio.create_task(self.shutdown())

        self._status_task = asyncio.create_task(self._status_consumer(), name="status-consumer")
        self._error_task = asyncio.create_task(self._error_consumer(), name="error-consumer")
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self._keyboard_listener.start()
        if self.stream_checkbox.value:
            self._start_stream()

    async def shutdown(self) -> None:
        self._stop_stream()

        if self._status_task:
            self._status_task.cancel()
        if self._error_task:
            self._error_task.cancel()

        if self.client:
            await self.client.close()
            self.client = None

        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

        for task in filter(None, [self._status_task, self._error_task]):
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _status_consumer(self) -> None:
        try:
            while True:
                report = await self.status_queue.get()
                self.state.last_status = report
                self.robot_state_text.value = report.ds_state or report.robot_state
                if report.ds_state:
                    self.robot_state_text.color = protocol.COLOR_DS_STATES_MAPPING.get(report.ds_state, NO_CONNECTION_COLOR)
                last_by = report.last_command_by or "-"
                ts = _format_timestamp(report.last_command_at)
                self.last_command_text.value = f"Last command: {last_by} @ {ts}"
                self.connected_clients_text.value = f"Connected clients: {report.connected_clients}"
                self.robot_state_text.update()
                self.last_command_text.update()
                self.connected_clients_text.update()
        except asyncio.CancelledError:
            pass

    async def _error_consumer(self) -> None:
        try:
            while True:
                message = await self.error_queue.get()
                self._show_message(message, error=True)
        except asyncio.CancelledError:
            pass

    def _handle_status(self, report: protocol.StatusReport) -> None:
        self.loop.call_soon_threadsafe(self.status_queue.put_nowait, report)

    def _handle_error(self, message: str) -> None:
        self.loop.call_soon_threadsafe(self.error_queue.put_nowait, message)

    async def _on_connect_click(self, event: ft.ControlEvent) -> None:
        if self.state.connected:
            await self._disconnect()
        else:
            await self._connect()

    async def _connect(self) -> None:
        host = self.host_field.value.strip() or DEFAULT_SETTINGS_DICT.server_host
        try:
            port = int(self.port_field.value.strip())
            if not (0 < port < 65536):
                raise ValueError
        except ValueError:
            self._show_message("Port must be between 1 and 65535.", error=True)
            return

        client_id = self.client_id_field.value.strip() or DEFAULT_SETTINGS_DICT.client_id
        config = ClientConfig(server_host=host, server_port=port, client_id=client_id)

        if self.client:
            await self.client.close()

        self.client = RemoteClient(config, on_status=self._handle_status, on_error=self._handle_error)

        self._set_busy(True)
        try:
            await self.client.connect()
        except Exception as exc:
            self._show_message(f"Failed to connect: {exc}", error=True)
            self.client = None
            self._set_busy(False)
            return

        self.settings = update_settings(config)

        self.state.connected = True
        self.state.client_label = f"{client_id} @ {host}:{port}"
        self._show_message(f"Connected to {host}:{port} as {client_id}", error=False)
        self._update_connection_ui()
        self._set_busy(False)
        self.stream_checkbox.disabled = False
        self.stream_checkbox.update()

    async def _disconnect(self) -> None:
        self._set_busy(True)
        if self.client:
            await self.client.close()
            self.client = None
        self.state.connected = False
        self.state.client_label = ""
        self._update_connection_ui()
        self._show_message("Disconnected.", error=False)
        self._set_busy(False)
        self.stream_checkbox.disabled = True
        self.stream_checkbox.update()
        self._stop_stream()

    def _update_connection_ui(self) -> None:
        if self.state.connected:
            self.status_header.value = f"Connected ({self.state.client_label})"
            self.status_header.color = COLOR_GREEN
            self.connect_button.text = "Disconnect"
            self.connect_button.icon = "stop_circle"
        else:
            self.status_header.value = "Disconnected"
            self.status_header.color = COLOR_RED
            self.connect_button.text = "Connect"
            self.connect_button.icon = "play_arrow"
            self.robot_state_text.value = "-"
            self.robot_state_text.color = NO_CONNECTION_COLOR
            self.last_command_text.value = "Last command: -"
            self.connected_clients_text.value = "Connected clients: -"

        self.enable_button.disabled = not self.state.connected
        self.disable_button.disabled = not self.state.connected
        self.estop_button.disabled = not self.state.connected

        self.status_header.update()
        self.connect_button.update()
        self.enable_button.update()
        self.disable_button.update()
        self.estop_button.update()
        self.robot_state_text.update()
        self.last_command_text.update()
        self.connected_clients_text.update()

    def _make_command_handler(self, command: protocol.CommandType):
        async def _handler(_: ft.ControlEvent) -> None:
            if not self.client:
                self._show_message("Not connected.", error=True)
                return
            try:
                self.client.send_command(command)
                self._show_message(f"Sent {command.value} command.", error=False)
            except Exception as exc:
                self._show_message(f"Failed to send command: {exc}", error=True)

        return _handler

    def _show_message(self, message: str, *, error: bool) -> None:
        self.message_banner.value = message
        self.message_banner.visible = True
        self.message_banner.color = COLOR_RED if error else COLOR_GREEN
        self.message_banner.update()

    def _set_busy(self, busy: bool) -> None:
        self.connect_button.disabled = busy
        self.enable_button.disabled = busy or not self.state.connected
        self.disable_button.disabled = busy or not self.state.connected
        self.estop_button.disabled = busy or not self.state.connected
        self.connect_button.update()
        self.enable_button.update()
        self.disable_button.update()
        self.estop_button.update()

    def _on_stream_toggle(self, _: ft.ControlEvent) -> None:
        if self.stream_checkbox.value:
            self._start_stream()
        else:
            self._stop_stream(clear_image=True)

    def _start_stream(self) -> None:
        if self._stream_running or not self.state.connected:
            return
        self.video_image.opacity = 1.0
        self.video_image.update()
        self._stream_stop_event.clear()
        self._stream_running = True
        self._stream_thread = threading.Thread(target=self._stream_worker, daemon=True)
        self._stream_thread.start()

    def _stop_stream(self, *, clear_image: bool = False) -> None:
        if not self._stream_running:
            if clear_image:
                self._clear_stream_image()
            return
        self.video_image.opacity = 0.0
        self.video_image.update()
        self._stream_running = False
        self._stream_stop_event.set()
        thread = self._stream_thread
        self._stream_thread = None
        if thread and thread.is_alive():
            thread.join(timeout=1)
        if clear_image:
            self._clear_stream_image()
        self.stream_checkbox.value = False
        self.stream_checkbox.update()

    def _stream_worker(self) -> None:
        while self._stream_running and not self._stream_stop_event.is_set():
            try:
                for frame in mjpeg_to_base64("http://"+self.host_field.value.strip() + ":" + str(int(self.port_field.value.strip())+1) + "/mjpeg", stop_event=self._stream_stop_event):
                    if self._stream_stop_event.is_set():
                        break
                    self.loop.call_soon_threadsafe(self._update_stream_image, frame)
                break
            except Exception as exc:
                if self._stream_stop_event.is_set():
                    break
                self.loop.call_soon_threadsafe(self._post_stream_error, f"Stream error: {exc}")
                if self._stream_stop_event.wait(2.0):
                    break
        self._stream_running = False
        self._stream_thread = None

    def _update_stream_image(self, frame_base64: str) -> None:
        self.video_image.src_base64 = frame_base64
        self.video_image.update()

    def _clear_stream_image(self) -> None:
        self.video_image.src_base64 = "dummy"
        self.video_image.update()

    def _post_stream_error(self, message: str) -> None:
        self._show_message(message, error=True)

    def _on_key_press(self, key: keyboard.Key) -> None:
        key_id = self._key_identifier(key)
        if not key_id:
            return
        self._pressed_keys.add(key_id)
        self._evaluate_hotkeys()

    def _on_key_release(self, key: keyboard.Key) -> None:
        key_id = self._key_identifier(key)
        if not key_id:
            return
        self._pressed_keys.discard(key_id)
        self._evaluate_hotkeys()

    def _evaluate_hotkeys(self) -> None:
        enable_combo = {"[", "]", "\\"}
        disable_key = {"enter"}

        if enable_combo.issubset(self._pressed_keys):
            if "enable" not in self._active_hotkeys:
                self._active_hotkeys.add("enable")
                self.loop.call_soon_threadsafe(self._handle_hotkey_command, protocol.CommandType.ENABLE)
        else:
            self._active_hotkeys.discard("enable")

        if disable_key.issubset(self._pressed_keys):
            if "disable" not in self._active_hotkeys:
                self._active_hotkeys.add("disable")
                self.loop.call_soon_threadsafe(self._handle_hotkey_command, protocol.CommandType.DISABLE)
        else:
            self._active_hotkeys.discard("disable")

    def _handle_hotkey_command(self, command: protocol.CommandType) -> None:
        if not self.client:
            self._show_message(f"Ignored {command.value} hotkey; client not connected.", error=True)
            return
        try:
            self.client.send_command(command)
            self._show_message(f"Sent {command.value} command via hotkey.", error=False)
        except Exception as exc:
            self._show_message(f"Failed to send command: {exc}", error=True)

    @staticmethod
    def _key_identifier(key: keyboard.Key) -> Optional[str]:
        if isinstance(key, keyboard.KeyCode):
            if key.char:
                char = key.char.lower()
                aliases = {"{": "[", "}": "]", "|": "\\"}
                return aliases.get(char, char)
            return None
        if key == keyboard.Key.enter:
            return "enter"
        return None


async def main_(page: ft.Page) -> None:
    app = ClientGuiApp(page)
    await app.initialize()


def run() -> None:
    ft.app(target=main_)

def main():
    run()


if __name__ == "__main__":
    run()
