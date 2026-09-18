"""Calibrated station definitions for an xArm workspace.

Stations deliberately describe only the information needed to prepare the arm
for a station-specific trajectory: a joint-space entry pose and, when fitted,
a linear-rail location. They do not plan or validate Cartesian motion.
"""

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence, Tuple


def _finite_float(value, field_name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("{} must be a number".format(field_name))
    if not math.isfinite(value):
        raise ValueError("{} must be finite".format(field_name))
    return value


@dataclass(frozen=True)
class JointPose:
    """A six- or seven-axis xArm entry pose, in degrees."""

    angles: Tuple[float, ...]

    def __post_init__(self):
        if not isinstance(self.angles, Sequence) or isinstance(self.angles, (str, bytes)):
            raise ValueError("JointPose angles must be a sequence")
        if len(self.angles) not in (6, 7):
            raise ValueError("JointPose must contain six or seven joint angles")
        object.__setattr__(
            self, "angles", tuple(_finite_float(angle, "joint angle") for angle in self.angles)
        )

    @classmethod
    def from_definition(cls, definition):
        return cls(definition)

    def to_definition(self):
        return list(self.angles)


class xArmStation:
    """Base class for a station entered from a calibrated xArm joint pose."""

    def __init__(self, name, entry_joint_angles, linear_rail_location=None):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Station name must be a non-empty string")
        if not isinstance(entry_joint_angles, JointPose):
            raise TypeError("Station entry_joint_angles must be a JointPose")
        if linear_rail_location is not None:
            linear_rail_location = _finite_float(linear_rail_location, "linear_rail_location")
        self.name = name
        self.entry_joint_angles = entry_joint_angles
        self.linear_rail_location = linear_rail_location

    @classmethod
    def from_definition(cls, name, definition):
        if not isinstance(definition, Mapping):
            raise ValueError("Station '{}' must be a mapping".format(name))
        try:
            return cls(
                name=name,
                entry_joint_angles=JointPose.from_definition(definition["entry_joint_angles"]),
                linear_rail_location=definition.get("linear_rail_location"),
            )
        except KeyError as exc:
            raise ValueError("Station '{}' is missing '{}'".format(name, exc.args[0]))

    def to_definition(self):
        definition = {
            "entry_joint_angles": self.entry_joint_angles.to_definition(),
        }
        if self.linear_rail_location is not None:
            definition["linear_rail_location"] = self.linear_rail_location
        return definition


class StationRegistry:
    """A collection of named station calibrations."""

    def __init__(self, stations: Iterable[xArmStation] = ()):
        self._stations = {}
        for station in stations:
            self.register(station)

    @classmethod
    def from_definitions(cls, definitions):
        if definitions is None:
            return cls()
        if not isinstance(definitions, Mapping):
            raise ValueError("stations configuration must be a mapping of names to definitions")
        stations = []
        for name, definition in definitions.items():
            if not isinstance(definition, Mapping):
                raise ValueError("Station '{}' must be a mapping".format(name))
            stations.append(xArmStation.from_definition(name, definition))
        return cls(stations)

    def register(self, station):
        if not isinstance(station, xArmStation):
            raise TypeError("Only xArmStation instances may be registered")
        if station.name in self._stations:
            raise ValueError("Station '{}' is already registered".format(station.name))
        self._stations[station.name] = station

    def names(self):
        return sorted(self._stations)

    def get(self, name):
        try:
            return self._stations[name]
        except KeyError:
            raise KeyError("Unknown station '{}'".format(name))

    def definition(self, name):
        return self.get(name).to_definition()


__all__ = [
    "JointPose", "StationRegistry", "xArmStation",
]
