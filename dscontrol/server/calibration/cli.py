"""
Interactive calibration utility for Driver Station screen regions.

The tool guides the operator through a series of clicks on the live Driver
Station window to compute the relative coordinates that other components use.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple
from .calibration_storage import Region,Point,CalibrationResult,CalibrationStorage

from ..win_utils import get_screen_size, get_taskbar_size

try:
    import win32api
    import win32con
except ImportError as exc:  # pragma: no cover - dependency guard
    raise RuntimeError(
        "Calibration tool requires the 'pywin32' package. Install the "
        "optional 'server-control' extras or add pywin32 to your environment."
    ) from exc



class ClickCollector:
    """
    Lightweight helper that waits for left-clicks and returns their positions.
    """

    def __init__(self, poll_interval: float = 0.02) -> None:
        self.poll_interval = poll_interval

    def wait_for_left_click(self, prompt: str) -> Point:
        """
        Block until the operator performs a left-click, returning its location.
        Esc may be pressed to abort the calibration early.
        """
        print(f"\n{prompt}")
        print("  → Left-click to capture. Press ESC to cancel.")

        while True:
            if self._escape_pressed():
                raise KeyboardInterrupt("Calibration cancelled by operator.")

            if self._left_held():
                x, y = win32api.GetCursorPos()
                self._wait_for_release()
                print(f"    captured at ({x}, {y})")
                return Point(x=int(x), y=int(y))

            time.sleep(self.poll_interval)

    def _escape_pressed(self) -> bool:
        return bool(win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000)

    def _left_held(self) -> bool:
        return bool(win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000)

    def _wait_for_release(self) -> None:
        while self._left_held():
            time.sleep(self.poll_interval)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate Driver Station capture regions via mouse clicks.")
    return parser


def _relative_point(point: Point, origin: Point) -> Point:
    return Point(x=point.x - origin.x, y=point.y - origin.y)


def _collect_status_region(collector: ClickCollector, ds_origin: Point) -> Region:
    top_left = collector.wait_for_left_click(
        "Step 2a - Move the cursor to the TOP-LEFT corner of the status indicator region and click."
    )
    bottom_right = collector.wait_for_left_click(
        "Step 2b - Move the cursor to the BOTTOM-RIGHT corner of the status indicator region and click."
    )

    tl_rel = _relative_point(top_left, ds_origin)
    br_rel = _relative_point(bottom_right, ds_origin)

    x1, y1 = tl_rel.x, tl_rel.y
    x2, y2 = br_rel.x, br_rel.y

    x = min(x1, x2)
    y = min(y1, y2)
    width = abs(x2 - x1)
    height = abs(y2 - y1)

    if width == 0 or height == 0:
        raise ValueError("Status region must have non-zero width and height.")

    return Region(x=x, y=y, width=width, height=height)


def _collect_mode_positions(
    collector: ClickCollector,
    ds_origin: Point,
    modes: Iterable[Tuple[str, str]],
) -> Dict[str, Point]:
    mode_points: Dict[str, Point] = {}
    for key, label in modes:
        capture = collector.wait_for_left_click(
            f"Step 4 ({label}) - Click the center of the '{label}' mode button."
        )
        mode_points[key] = _relative_point(capture, ds_origin)
    return mode_points


def run_calibration() -> CalibrationResult:
    screen_width, screen_height = get_screen_size()
    taskbar_height = get_taskbar_size()
    collector = ClickCollector()

    print("Driver Station Layout Calibration\n")
    print("Every capture is relative to the Driver Station's bottom-docked window.")

    top_edge = collector.wait_for_left_click(
        "Step 1 - Hover over the TOP EDGE of the Driver Station window (just above the tabs) and click."
    )
    ds_origin = Point(x=0, y=top_edge.y)

    ds_height = screen_height - taskbar_height - ds_origin.y
    if ds_height <= 0:
        raise ValueError(
            f"Computed Driver Station height is {ds_height}. "
            "Verify that the top edge was clicked correctly."
        )

    status_region = _collect_status_region(collector, ds_origin)

    enable_point = _relative_point(
        collector.wait_for_left_click("Step 3a - Click the center of the ENABLE button."), ds_origin
    )
    disable_point = _relative_point(
        collector.wait_for_left_click("Step 3b - Click the center of the DISABLE button."), ds_origin
    )

    modes = [
        ("teleoperated", "Teleoperated"),
        ("autonomous", "Autonomous"),
        ("practice", "Practice"),
        ("test", "Test"),
    ]
    mode_positions = _collect_mode_positions(collector, ds_origin, modes)

    result = CalibrationResult(
        ds_height=ds_height,
        status_region=status_region,
        enable_position=enable_point,
        disable_position=disable_point,
        mode_positions=mode_positions,
        ds_origin=ds_origin,
        screen_size=Point(screen_width, screen_height),
        taskbar_height=taskbar_height,
    )

    print("\nCalibration complete.")
    print(f"  Driver Station height: {result.ds_height}px")
    print(
        "  Status region (relative): "
        f"x={result.status_region.x}, y={result.status_region.y}, "
        f"w={result.status_region.width}, h={result.status_region.height}"
    )
    print(
        f"  Enable button (relative): x={result.enable_position.x}, y={result.enable_position.y}"
    )
    print(
        f"  Disable button (relative): x={result.disable_position.x}, y={result.disable_position.y}"
    )
    for key, label in modes:
        point = result.mode_positions[key]
        print(f"  {label} button (relative): x={point.x}, y={point.y}")

    return result


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    _ = parser.parse_args(argv)

    try:
        result = run_calibration()
    except KeyboardInterrupt as exc:
        parser.exit(1, f"\n{exc}\n")
    except Exception as exc:
        parser.exit(1, f"\nFailed to complete calibration: {exc}\n")

    CalibrationStorage.save(result)

    print(f"\nSaved calibration data to {Path(CalibrationStorage._file_path).absolute}")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main(sys.argv[1:])
