from dataclasses import dataclass
from typing import Dict, Any, Tuple
import json
import os
from typing import Optional


@dataclass
class Point:
    x: int
    y: int

    def to_dict(self) -> Dict[str, int]:
        return {"x": int(self.x), "y": int(self.y)}
    
    def to_tuple(self) -> Tuple[int,int]:
        return (self.x,self.y)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Point":
        return cls(
            x=int(data["x"]),
            y=int(data["y"])
        )
        


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> Dict[str, int]:
        return {
            "x": int(self.x),
            "y": int(self.y),
            "width": int(self.width),
            "height": int(self.height),
        }
    
    def to_tuple(self) -> Tuple[int,int,int,int]:
        return (self.x,self.y,self.width,self.height)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Region":
        return cls(
            x=int(data["x"]),
            y=int(data["y"]),
            width=int(data["width"]),
            height=int(data["height"])
        )

    

@dataclass
class CalibrationResult:
    ds_height: int
    status_region: Region
    enable_position: Point
    disable_position: Point
    mode_positions: Dict[str, Point]
    ds_origin: Point
    screen_size: Point
    taskbar_height: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ds_height": int(self.ds_height),
            "status_region": self.status_region.to_dict(),
            "enable_position": self.enable_position.to_dict(),
            "disable_position": self.disable_position.to_dict(),
            "mode_positions": {name: p.to_dict() for name, p in self.mode_positions.items()},
            "ds_origin": self.ds_origin.to_dict(),
            "screen_size": self.screen_size.to_dict(),
            "taskbar_height": int(self.taskbar_height),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationResult":
        return cls(
            ds_height=int(data["ds_height"]),
            status_region=Region.from_dict(data["status_region"]),
            enable_position=Point.from_dict(data["enable_position"]),
            disable_position=Point.from_dict(data["disable_position"]),
            mode_positions={name: Point.from_dict(p) for name, p in data["mode_positions"].items()},
            ds_origin=Point.from_dict(data["ds_origin"]),
            screen_size=Point.from_dict(data["screen_size"]),
            taskbar_height=int(data["taskbar_height"]),
        )


class CalibrationStorage:
    _instance: Optional["CalibrationResult"] = None
    _file_path: str = "calibration.json"

    @classmethod
    def save(cls, calibration: CalibrationResult) -> None:
        """Save the calibration to JSON (replaces existing file)."""
        cls._instance = calibration
        with open(cls._file_path, "w", encoding="utf-8") as f:
            json.dump(calibration.to_dict(), f, indent=2)

    @classmethod
    def load(cls) -> Optional[CalibrationResult]:
        """Load calibration from JSON, if exists."""
        if cls._instance is not None:
            return cls._instance

        if not os.path.exists(cls._file_path):
            return None

        with open(cls._file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            cls._instance = CalibrationResult.from_dict(data)
            return cls._instance

    @classmethod
    def get(cls) -> CalibrationResult:
        """Return the cached instance if available, otherwise load it."""
        _inst = cls._instance or cls.load()
        assert _inst
        return _inst

    @classmethod
    def clear(cls) -> None:
        """Forget the cached instance (and optionally delete the file)."""
        cls._instance = None
        if os.path.exists(cls._file_path):
            os.remove(cls._file_path)
