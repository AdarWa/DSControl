"""
Abstractions for interfacing with the FRC Driver Station application.

The default implementation prefers native automation libraries if available
(`pyautogui` on any platform, `ctypes` with the Win32 API on Windows). When
no automation backend is available the controller falls back to logging the
requested actions so the integration can still be developed and tested on
non-Windows machines.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from typing import Optional
from .stream_server import X,Y
import time

_LOGGER = logging.getLogger(__name__)

KEY_PRESS_INTERVAL = 0.2 # seconds


def _load_pyautogui():
    try:
        import pydirectinput  # type: ignore

        return pydirectinput
    except Exception:  # pragma: no cover - absence is expected on headless hosts
        return None


PY_AUTO_GUI = _load_pyautogui()


@dataclass
class ControlResult:
    success: bool
    message: str
    backend: str


class DriverStationController:
    """
    Issues enable/disable/e-stop commands to the local Driver Station.

    Automation shortcuts:
      - Enable: [ + ] + \\ (customisable)
      - Disable: Enter
      - E-stop: Space

    The exact key bindings used by the official DS can vary by season; adjust
    `ENABLE_COMBO`, `DISABLE_KEY`, and `ESTOP_COMBO` if a different mapping is
    required.
    """

    ENABLE_COMBO = ["[", "]", "\\"]
    DISABLE_KEY = "enter"
    ESTOP_COMBO = ["space"]
    DS_WINDOW_REFERENCE = (X,Y)
    RELATIVE_DISABLE_POS = (0,0)
    RELATIVE_ENABLE_POS = (0,0)

    def __init__(self, backend_preference: Optional[str] = None) -> None:
        self._backend = backend_preference or self._select_backend()

    @staticmethod
    def _select_backend() -> str:
        if PY_AUTO_GUI:
            return "pyautogui"
        if platform.system() == "Windows":
            return "windows-stub"
        return "log-only"

    def enable(self) -> ControlResult:
        return self._send_keys(self.ENABLE_COMBO, "enable")

    def disable(self) -> ControlResult:
        return self._send_keys([self.DISABLE_KEY], "disable")

    def estop(self) -> ControlResult:
        return self._send_keys(self.ESTOP_COMBO, "estop")
    
    def click_relative(self,reference: tuple, point: tuple) -> None:
        assert PY_AUTO_GUI
        refX,refY = reference
        x,y = point
        PY_AUTO_GUI.leftClick(refX+x, refY+y)

    # Internal helpers -----------------------------------------------------

    def _send_keys(self, keys: list[str], action: str) -> ControlResult:
        backend = self._backend
        if backend == "pyautogui" and PY_AUTO_GUI:
            try:
                _LOGGER.debug("Sending %s via pyautogui: %s", action, keys)
                if action == "enable":
                    self.click_relative(self.DS_WINDOW_REFERENCE, self.RELATIVE_ENABLE_POS)
                elif action == "disable":
                    self.click_relative(self.DS_WINDOW_REFERENCE, self.RELATIVE_DISABLE_POS)
                if len(keys) == 1:
                    PY_AUTO_GUI.keyDown(keys[0])
                    time.sleep(KEY_PRESS_INTERVAL)
                    PY_AUTO_GUI.keyUp(keys[0])
                else:
                    for key in keys:
                        PY_AUTO_GUI.keyDown(key)
                    time.sleep(KEY_PRESS_INTERVAL)
                    for key in keys:
                        PY_AUTO_GUI.keyUp(key)
                return ControlResult(True, f"{action} sent via pyautogui", backend)
            except Exception as exc:  # pragma: no cover - depends on environment
                _LOGGER.exception("pyautogui failed to send %s command: %s", action, exc)
                return ControlResult(False, f"pyautogui failure: {exc}", backend)

        # Fallback: log the request to help manual integration on Windows later.
        _LOGGER.warning(
            "DriverStationController running in '%s' mode; action '%s' not issued to DS.",
            backend,
            action,
        )
        if backend == "log-only":
            return ControlResult(True, f"{action} simulated (log-only backend)", backend)
        return ControlResult(False, f"{action} not sent (backend={backend})", backend)
