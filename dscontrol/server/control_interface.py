"""
Abstractions for interfacing with the FRC Driver Station application.

The default implementation prefers native automation libraries if available
(`pyautogui` on any platform, `ctypes` with the Win32 API on Windows). When
no automation backend is available the controller falls back to logging the
requested actions so the integration can still be developed and tested on
non-Windows machines.

The controller also supports FMS mode, which uses UDP packets to control the
Driver Station directly, mimicking the Field Management System protocol.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from typing import Optional
from .win_utils import activate_driverstation_window
from .calibration.calibration_storage import CalibrationStorage
from enum import Enum
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

class RobotMode(Enum):
    TELEOP = "teleoperated"
    AUTO = "autonomous"
    PRACTICE = "practice"
    TEST = "test"

class DriverStationController:
    """
    Issues enable/disable/e-stop commands to the local Driver Station.

    Supports two control modes:
    1. Keystroke mode (default): Sends keyboard shortcuts to the DS application
       - Enable: [ + ] + \\ (customisable)
       - Disable: Enter
       - E-stop: Space

    2. FMS mode: Sends UDP packets mimicking the Field Management System
       - Uses the fms.DriverStationConnection to control the DS directly

    The exact key bindings used by the official DS can vary by season; adjust
    `ENABLE_COMBO`, `DISABLE_KEY`, and `ESTOP_COMBO` if a different mapping is
    required.
    """

    ENABLE_COMBO = ["[", "]", "\\"]
    DISABLE_KEY = "enter"
    ESTOP_COMBO = ["space"]
    DS_WINDOW_REFERENCE = CalibrationStorage.get().ds_origin.to_tuple()
    RELATIVE_DISABLE_POS = CalibrationStorage.get().disable_position.to_tuple()
    RELATIVE_ENABLE_POS = CalibrationStorage.get().enable_position.to_tuple()
    RELATIVE_MODE_POSES = CalibrationStorage.get().mode_positions

    def __init__(
        self,
        backend_preference: Optional[str] = None,
        use_fms: bool = False,
        team_id: int = 5987,
        alliance_station: str = "R1",
        ds_address: str = "127.0.0.1",
    ) -> None:
        self._use_fms = use_fms
        self._fms_connection: Optional[object] = None

        if use_fms:
            self._backend = "fms"
            self._init_fms(team_id, alliance_station, ds_address)
        else:
            self._backend = backend_preference or self._select_backend()

    def _init_fms(self, team_id: int, alliance_station: str, ds_address: str) -> None:
        """Initialize FMS connection."""
        try:
            from .fms import DriverStationConnection, AlliancePosition

            # Map string to AlliancePosition enum
            alliance_map = {
                "R1": AlliancePosition.R1,
                "R2": AlliancePosition.R2,
                "R3": AlliancePosition.R3,
                "B1": AlliancePosition.B1,
                "B2": AlliancePosition.B2,
                "B3": AlliancePosition.B3,
            }
            alliance_pos = alliance_map.get(alliance_station, AlliancePosition.R1)

            self._fms_connection = DriverStationConnection(team_id, alliance_pos, ds_address)
            _LOGGER.info(
                "FMS mode initialized: team=%d, station=%s, address=%s",
                team_id,
                alliance_station,
                ds_address,
            )
        except Exception as exc:
            _LOGGER.exception("Failed to initialize FMS connection: %s", exc)
            self._backend = "log-only"
            self._use_fms = False

    def click_relative(self,reference: tuple, point: tuple) -> None:
        assert PY_AUTO_GUI
        refX,refY = reference
        x,y = point
        PY_AUTO_GUI.leftClick(refX+x, refY+y)

    @staticmethod
    def _select_backend() -> str:
        if PY_AUTO_GUI:
            return "pyautogui"
        if platform.system() == "Windows":
            return "windows-stub"
        return "log-only"

    def enable(self) -> ControlResult:
        if self._use_fms and self._fms_connection:
            return self._fms_enable()
        return self._send_keys(self.ENABLE_COMBO, "enable")

    def disable(self) -> ControlResult:
        if self._use_fms and self._fms_connection:
            return self._fms_disable()
        return self._send_keys([self.DISABLE_KEY], "disable")

    def estop(self) -> ControlResult:
        if self._use_fms and self._fms_connection:
            return self._fms_estop()
        return self._send_keys(self.ESTOP_COMBO, "estop")

    # FMS control methods --------------------------------------------------

    def _fms_enable(self) -> ControlResult:
        """Enable robot via FMS protocol."""
        try:
            self._fms_connection.enable_robot()
            _LOGGER.debug("Sent enable via FMS protocol")
            return ControlResult(True, "enable sent via FMS", "fms")
        except Exception as exc:
            _LOGGER.exception("FMS enable failed: %s", exc)
            return ControlResult(False, f"FMS enable failure: {exc}", "fms")

    def _fms_disable(self) -> ControlResult:
        """Disable robot via FMS protocol."""
        try:
            self._fms_connection.disable_robot()
            _LOGGER.debug("Sent disable via FMS protocol")
            return ControlResult(True, "disable sent via FMS", "fms")
        except Exception as exc:
            _LOGGER.exception("FMS disable failed: %s", exc)
            return ControlResult(False, f"FMS disable failure: {exc}", "fms")

    def _fms_estop(self) -> ControlResult:
        """E-stop robot via FMS protocol."""
        try:
            self._fms_connection.estop_robot()
            _LOGGER.debug("Sent estop via FMS protocol")
            return ControlResult(True, "estop sent via FMS", "fms")
        except Exception as exc:
            _LOGGER.exception("FMS estop failed: %s", exc)
            return ControlResult(False, f"FMS estop failure: {exc}", "fms")

    def set_mode(self, mode: RobotMode) -> ControlResult:
        activate_driverstation_window()
        self.click_relative(self.DS_WINDOW_REFERENCE, self.RELATIVE_MODE_POSES[mode.value].to_tuple())
        return ControlResult(True, f"sent {mode} mode using {self._backend}",self._backend)

    # Internal helpers -----------------------------------------------------

    def _send_keys(self, keys: list[str], action: str) -> ControlResult:
        backend = self._backend
        if backend == "pyautogui" and PY_AUTO_GUI:
            try:
                _LOGGER.debug("Sending %s via pyautogui: %s", action, keys)
                if action == "enable":
                    activate_driverstation_window()
                    self.click_relative(self.DS_WINDOW_REFERENCE, self.RELATIVE_ENABLE_POS)
                elif action == "disable":
                    activate_driverstation_window()
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
