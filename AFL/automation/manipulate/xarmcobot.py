from AFL.automation.APIServer.Driver import Driver
from xarm.wrapper import XArmAPI
import time 
from pathlib import Path
import json
import numpy as np
import re
import math
from collections.abc import Mapping

from AFL.automation.manipulate.xarmutils import StationRegistry

XARM_API_CODE_DESCRIPTIONS = {
    0: "success",
    -1: "xArm API is not connected",
    -2: "xArm API is not ready",
    -3: "xArm API response timeout",
    -4: "xArm API command parse error",
    -5: "xArm API command execution failed",
    -6: "xArm API invalid parameter",
    -7: "xArm API state is not valid for this command",
    -8: "xArm API mode is not valid for this command",
    -9: "xArm API has an active error or warning",
}

XARM_MODE_DESCRIPTIONS = {
    0: "position mode",
    1: "servoj external trajectory planner mode",
    2: "manual free-drive mode",
    3: "reserved",
    4: "joint velocity control mode",
    5: "cartesian velocity control mode",
    6: "joint dynamic online planning mode",
    7: "cartesian dynamic online planning mode",
    11: "recorded trajectory playback mode",
}

XARM_STATE_FEEDBACK_DESCRIPTIONS = {
    1: "in motion",
    2: "ready",
    3: "paused",
    4: "stopped",
    5: "mode changed, requires set_state(0)",
    6: "decelerating stop",
}

XARM_STATE_SET_DESCRIPTIONS = {
    0: "set standby and clear errors; feedback usually becomes ready (2)",
    3: "pause current motion",
    4: "stop immediately",
    6: "decelerated stop in mode 0",
}

class XArmCobot(Driver):
    '''
        A class to control the XArm in Cobot mode.
    '''
    overrides = {}
    defaults = {
        'ip': '192.168.1.201',
        'initial_angles': [-270, -16.0, -4.0, 13.1, -5.0, -94.6, -180.0],
        'gripper_open_position': 300,
        'gripper_closed_position': 110,
        'gripper_speed': 2000,
        # SDK names: ``xarm_gripper`` is the standard xArm parallel/finger
        # gripper; ``bio_gripper`` is xArm's Bio Gripper.  ``none`` leaves
        # end-effector hardware untouched.
        'end_effector': 'none',
        'bio_gripper_speed': 0,
        'bio_gripper_force': None,
        'station_entry_speed': 30.0,
        'cartesian_move_speed': 100.0,
        'cartesian_move_accel': 2000.0,
        'traj_dir': '~/.afl/xarm_trajectories/',
        # The xArm linear rail is optional.  Leave this disabled for arm-only
        # installations: querying the rail otherwise attempts RS-485 traffic.
        'on_linear_rail': False,
        # xArm SDK linear-motor units are millimetres and millimetres/second.
        'linear_rail_speed': 50,
        # Homing moves the rail, so it is deliberately opt-in even when a rail
        # is fitted.  The SDK requires homing after the rail is powered on.
        'linear_rail_home_on_init': False,
        'linear_rail_home_timeout': 10,
        'linear_rail_move_timeout': 100,
        # Mapping of station names to xarmutils station definitions.  The
        # definitions are deliberately calibration-specific and therefore
        # empty by default.
        'stations': {},
    }
    def __init__(self,overrides={}):
        self._app = None

        Driver.__init__(self,name='XArmCobot', defaults=self.gather_defaults(),overrides=overrides)
        try:
            self.arm = XArmAPI(self.config['ip'])
        except Exception as e:
            raise RuntimeError(f"Failed to initialize XArmAPI: {e}")

        self.arm.motion_enable(True)
        self.arm.clean_error()
        self.arm.clean_warn()
        self.arm.set_mode(0)
        self.arm.set_state(0)
        self.traj_dir = Path(self.config['traj_dir']).resolve()
        self.station_registry = StationRegistry.from_definitions(self.config['stations'])

        if self.config['on_linear_rail']:
            self._initialize_linear_rail()
        self._initialize_end_effector()

    def set_config(self, **kwargs):
        """Persist configuration and atomically refresh station calibrations."""
        station_registry = None
        if 'stations' in kwargs:
            station_registry = StationRegistry.from_definitions(kwargs['stations'])
        super().set_config(**kwargs)
        if station_registry is not None:
            self.station_registry = station_registry
        if any(key in kwargs for key in (
            'end_effector', 'gripper_speed', 'bio_gripper_speed', 'bio_gripper_force'
        )):
            self._initialize_end_effector()

    def _describe_api_code(self, code):
        return XARM_API_CODE_DESCRIPTIONS.get(code, f"unknown API code {code}")

    def _describe_mode(self, mode):
        return XARM_MODE_DESCRIPTIONS.get(mode, f"unknown mode {mode}")

    def _describe_feedback_state(self, state):
        return XARM_STATE_FEEDBACK_DESCRIPTIONS.get(state, f"unknown feedback state {state}")

    def _describe_set_state(self, state):
        return XARM_STATE_SET_DESCRIPTIONS.get(state, f"unknown set-state value {state}")

    def _require_linear_rail(self):
        if not self.config['on_linear_rail']:
            raise RuntimeError(
                "This xArm is not configured with a linear rail. "
                "Set on_linear_rail=True to enable rail commands."
            )

    def _check_linear_rail_code(self, operation, code):
        if code != 0:
            raise RuntimeError(
                f"Failed to {operation}, code={self._describe_api_code(code)} ({code})"
            )

    @staticmethod
    def _cartesian_waypoint_pose(name, values):
        if not isinstance(values, (list, tuple)) or len(values) not in (3, 6):
            raise ValueError(
                "Cartesian waypoint '{}' must contain [x, y, z] or "
                "[x, y, z, roll, pitch, yaw]".format(name)
            )
        try:
            pose = [float(value) for value in values]
        except (TypeError, ValueError):
            raise ValueError("Cartesian waypoint '{}' contains a non-numeric value".format(name))
        if not all(math.isfinite(value) for value in pose):
            raise ValueError("Cartesian waypoint '{}' values must be finite".format(name))
        return pose

    @classmethod
    def _ordered_cartesian_waypoints(cls, waypoints, reverse=False):
        """Validate and order ``<number>_<name>`` Cartesian waypoint mappings."""
        if not isinstance(waypoints, Mapping) or not waypoints:
            raise ValueError("waypoints must be a non-empty dictionary")
        missing_reserved = {'entry', 'exit'}.difference(waypoints)
        if missing_reserved:
            raise ValueError(
                "waypoints must include reserved key(s): {}".format(
                    ", ".join(sorted(missing_reserved))
                )
            )
        entry_pose = cls._cartesian_waypoint_pose('entry', waypoints['entry'])
        exit_pose = cls._cartesian_waypoint_pose('exit', waypoints['exit'])
        parsed = []
        sequence_numbers = set()
        for key, angles in waypoints.items():
            if key in ('entry', 'exit'):
                continue
            if not isinstance(key, str):
                raise ValueError("Waypoint keys must use the format '<number>_<name>'")
            match = re.fullmatch(r"(\d+)_([^\s].*)", key)
            if match is None:
                raise ValueError(
                    "Waypoint '{}' must use the format '<number>_<name>', for example '1_entry'".format(key)
                )
            sequence_number = int(match.group(1))
            if sequence_number in sequence_numbers:
                raise ValueError("Waypoint sequence number {} is duplicated".format(sequence_number))
            sequence_numbers.add(sequence_number)
            pose = cls._cartesian_waypoint_pose(key, angles)
            parsed.append((sequence_number, key, pose))
        if not parsed:
            raise ValueError("waypoints must include at least one numbered '<number>_<name>' waypoint")
        parsed.sort(key=lambda item: item[0], reverse=reverse)
        return entry_pose, exit_pose, parsed

    @Driver.queued()
    def play_cartesian_waypoints(self, waypoints, reverse=False, speed=None, accel=None, wait=True):
        """Play numbered Cartesian waypoints in sequence or reverse sequence.

        ``waypoints`` must map keys such as ``'1_entry'`` and ``'20_to_vial'``
        to either XYZ millimetre coordinates or a full six-value xArm Cartesian
        pose ``[x, y, z, roll, pitch, yaw]`` in millimetres/degrees. XYZ-only
        points retain the arm's current orientation. The mapping must also
        define ``entry`` and ``exit`` poses. Forward playback commands
        ``entry`` then the numbered points in ascending order. Reverse playback
        runs the numbered points in descending order, returns through ``entry``,
        and commands ``exit`` last.
        """
        entry_pose, exit_pose, ordered_waypoints = self._ordered_cartesian_waypoints(
            waypoints, reverse=reverse
        )
        if reverse:
            ordered_waypoints.extend(((None, 'entry', entry_pose), (None, 'exit', exit_pose)))
        else:
            ordered_waypoints.insert(0, (None, 'entry', entry_pose))
        if speed is None:
            speed = self.config['cartesian_move_speed']
        if accel is None:
            accel = self.config['cartesian_move_accel']
        played = []
        for _, name, waypoint in ordered_waypoints:
            if len(waypoint) == 3:
                query_code, current_pose = self.arm.get_position(is_radian=False)
                if query_code != 0 or current_pose is None or len(current_pose) < 6:
                    raise RuntimeError(
                        "Failed to read Cartesian orientation for waypoint '{}', code={} ({})".format(
                            name, self._describe_api_code(query_code), query_code
                        )
                    )
                target_pose = waypoint + list(current_pose[3:6])
            else:
                target_pose = waypoint
            self.log_info("Moving to Cartesian waypoint '{}'".format(name))
            code = self.arm.set_position(
                *target_pose, speed=speed, mvacc=accel, radius=-1.0, wait=wait
            )
            if code != 0:
                raise RuntimeError(
                    "Failed to move to Cartesian waypoint '{}', code={} ({})".format(
                        name, self._describe_api_code(code), code
                    )
                )
            played.append(name)
        return {"reverse": reverse, "waypoints": played}

    @Driver.queued()
    def move_relative_xyz(self, dx=0.0, dy=0.0, dz=0.0, speed=None, accel=None, wait=True):
        """Move the TCP by XYZ offsets while preserving its current orientation.

        The current Cartesian pose is read from the arm immediately before the
        move.  The offsets and resulting target are in millimetres in the same
        xArm Cartesian frame returned by ``get_position``.
        """
        try:
            dx, dy, dz = float(dx), float(dy), float(dz)
        except (TypeError, ValueError):
            raise ValueError("dx, dy, and dz must be numeric millimetre offsets")
        if speed is None:
            speed = self.config['cartesian_move_speed']
        if accel is None:
            accel = self.config['cartesian_move_accel']

        code, current_pose = self.arm.get_position(is_radian=False)
        if code != 0:
            raise RuntimeError(
                "Failed to read current Cartesian pose, code={} ({})".format(
                    self._describe_api_code(code), code
                )
            )
        if current_pose is None or len(current_pose) < 6:
            raise RuntimeError("xArm returned an incomplete Cartesian pose: {}".format(current_pose))

        target_pose = list(current_pose[:6])
        target_pose[0] += dx
        target_pose[1] += dy
        target_pose[2] += dz
        code = self.arm.set_position(
            *target_pose, speed=speed, mvacc=accel, radius=-1.0, wait=wait
        )
        if code != 0:
            raise RuntimeError(
                "Failed to move TCP by [{}, {}, {}] mm, code={} ({})".format(
                    dx, dy, dz, self._describe_api_code(code), code
                )
            )
        self.log_info("Moved TCP to Cartesian pose {}".format(target_pose))
        return {"offset": [dx, dy, dz], "target_pose": target_pose}

    def _end_effector_name(self):
        name = self.config['end_effector']
        aliases = {'finger_gripper': 'xarm_gripper'}
        name = aliases.get(name, name)
        if name not in ('none', 'xarm_gripper', 'bio_gripper'):
            raise ValueError(
                "end_effector must be 'none', 'xarm_gripper', or 'bio_gripper'"
            )
        return name

    def _check_end_effector_code(self, operation, code):
        if code != 0:
            raise RuntimeError(
                "Failed to {}, code={} ({})".format(
                    operation, self._describe_api_code(code), code
                )
            )

    def _initialize_end_effector(self):
        """Enable the configured SDK gripper without commanding it to move."""
        end_effector = self._end_effector_name()
        if end_effector == 'none':
            return
        if end_effector == 'xarm_gripper':
            self._check_end_effector_code(
                'enable xArm Gripper', self.arm.set_gripper_enable(True)
            )
            self._check_end_effector_code(
                'set xArm Gripper position mode', self.arm.set_gripper_mode(0)
            )
            self._check_end_effector_code(
                'set xArm Gripper speed', self.arm.set_gripper_speed(self.config['gripper_speed'])
            )
        else:
            self._check_end_effector_code(
                'clear Bio Gripper errors', self.arm.clean_bio_gripper_error()
            )
            self._check_end_effector_code(
                'enable Bio Gripper', self.arm.set_bio_gripper_enable(True, wait=True)
            )
            if self.config['bio_gripper_speed']:
                self._check_end_effector_code(
                    'set Bio Gripper speed',
                    self.arm.set_bio_gripper_speed(self.config['bio_gripper_speed']),
                )
            if self.config['bio_gripper_force'] is not None:
                self._check_end_effector_code(
                    'set Bio Gripper force',
                    self.arm.set_bio_gripper_force(self.config['bio_gripper_force']),
                )

    def _require_gripper(self):
        end_effector = self._end_effector_name()
        if end_effector == 'none':
            raise RuntimeError("No gripper is configured; set end_effector before commanding it")
        return end_effector

    @Driver.queued()
    def open_gripper(self, wait=True, timeout=5):
        """Open the configured xArm Gripper or Bio Gripper."""
        end_effector = self._require_gripper()
        if end_effector == 'xarm_gripper':
            code = self.arm.set_gripper_position(
                self.config['gripper_open_position'],
                speed=self.config['gripper_speed'],
                wait=wait,
                auto_enable=True,
                timeout=timeout,
            )
        else:
            code = self.arm.open_bio_gripper(
                speed=self.config['bio_gripper_speed'], wait=wait, timeout=timeout
            )
        self._check_end_effector_code('open {}'.format(end_effector), code)

    @Driver.queued()
    def close_gripper(self, wait=True, timeout=5):
        """Close the configured xArm Gripper or Bio Gripper."""
        end_effector = self._require_gripper()
        if end_effector == 'xarm_gripper':
            code = self.arm.set_gripper_position(
                self.config['gripper_closed_position'],
                speed=self.config['gripper_speed'],
                wait=wait,
                auto_enable=True,
                timeout=timeout,
            )
        else:
            code = self.arm.close_bio_gripper(
                speed=self.config['bio_gripper_speed'], wait=wait, timeout=timeout
            )
        self._check_end_effector_code('close {}'.format(end_effector), code)

    @Driver.unqueued()
    def list_stations(self):
        """Return configured xArm station names."""
        return self.station_registry.names()

    @Driver.unqueued()
    def station_definition(self, station):
        """Return the serializable calibration definition for one station."""
        return self.station_registry.definition(station)

    @Driver.queued()
    def prepare_station(self, station, speed=None, rail_speed=None):
        """Move the rail, when required, then move to a station entry joint pose."""
        station_definition = self.station_registry.get(station)
        if speed is None:
            speed = self.config['station_entry_speed']
        if station_definition.linear_rail_location is not None:
            self.move_linear_rail(
                station_definition.linear_rail_location, speed=rail_speed, wait=True
            )
        code = self.arm.set_servo_angle(
            angle=list(station_definition.entry_joint_angles.angles),
            speed=speed,
            is_radian=False,
            wait=True,
        )
        if code != 0:
            raise RuntimeError(
                "Failed to enter station '{}', code={} ({})".format(
                    station, self._describe_api_code(code), code
                )
            )
        self.log_info("Station '{}' prepared at its entry joint pose".format(station))
        return {
            "station": station,
            "linear_rail_location": station_definition.linear_rail_location,
            "entry_joint_angles": list(station_definition.entry_joint_angles.angles),
        }

    def _station_trajectory_filename(self, station, filename):
        station_dir = (self.traj_dir / station).resolve()
        trajectory_path = (station_dir / filename).resolve()
        if station_dir not in trajectory_path.parents:
            raise ValueError("Station trajectory filename must remain within its station directory")
        return str(trajectory_path.relative_to(self.traj_dir))

    def _trajectory_filename(self, filename, station=None):
        if station is None:
            return filename
        self.station_registry.get(station)
        return self._station_trajectory_filename(station, filename)

    @Driver.unqueued()
    def list_station_trajectories(self, station):
        """List ``*.json`` trajectories stored in ``traj_dir/<station>/``."""
        self.station_registry.get(station)
        station_dir = (self.traj_dir / station).resolve()
        if not station_dir.exists():
            return []
        return sorted(path.name for path in station_dir.glob("*.json"))

    @Driver.queued()
    def play_station_trajectory(self, station, filename, speed=None, rail_speed=None,
                                dt=0.02, interp_steps=5):
        """Prepare a station, then play one trajectory stored for that station."""
        self.prepare_station(station, speed=speed, rail_speed=rail_speed)
        station_filename = self._station_trajectory_filename(station, filename)
        return self.play(station_filename, dt=dt, interp_steps=interp_steps)

    def _initialize_linear_rail(self):
        """Prepare the optional rail without moving it unless configured to home."""
        self._check_linear_rail_code(
            "clear linear-rail errors", self.arm.clean_linear_motor_error()
        )
        if self.config['linear_rail_home_on_init']:
            self.home_linear_rail()
        else:
            self._check_linear_rail_code(
                "enable linear rail", self.arm.set_linear_motor_enable(True)
            )
            self._check_linear_rail_code(
                "set linear-rail speed",
                self.arm.set_linear_motor_speed(self.config['linear_rail_speed']),
            )

    @Driver.queued()
    def home_linear_rail(self, wait=True, timeout=None):
        """Home the configured linear rail and enable it for subsequent moves."""
        self._require_linear_rail()
        if timeout is None:
            timeout = self.config['linear_rail_home_timeout']
        self._check_linear_rail_code(
            "home linear rail",
            self.arm.set_linear_motor_back_origin(wait=wait, timeout=timeout, auto_enable=True),
        )
        self._check_linear_rail_code(
            "set linear-rail speed",
            self.arm.set_linear_motor_speed(self.config['linear_rail_speed']),
        )
        self.log_info("Linear rail homed and enabled")

    @Driver.queued()
    def move_linear_rail(self, position, speed=None, wait=True, timeout=None):
        """Move the configured linear rail to ``position`` in millimetres."""
        self._require_linear_rail()
        if speed is None:
            speed = self.config['linear_rail_speed']
        if timeout is None:
            timeout = self.config['linear_rail_move_timeout']
        self._check_linear_rail_code(
            f"move linear rail to {position} mm",
            self.arm.set_linear_motor_pos(
                position, speed=speed, wait=wait, timeout=timeout, auto_enable=True
            ),
        )
        self.log_debug(f"Linear rail moved to {position} mm at {speed} mm/s")

    @Driver.queued()
    def stop_linear_rail(self):
        """Stop the configured linear rail."""
        self._require_linear_rail()
        self._check_linear_rail_code("stop linear rail", self.arm.set_linear_motor_stop())

    @Driver.unqueued()
    def linear_rail_status(self):
        """Return the xArm SDK status for the configured linear rail."""
        self._require_linear_rail()
        queries = {
            'position': self.arm.get_linear_motor_pos,
            'status': self.arm.get_linear_motor_status,
            'error': self.arm.get_linear_motor_error,
            'enabled': self.arm.get_linear_motor_is_enabled,
            'on_zero': self.arm.get_linear_motor_on_zero,
        }
        rail_status = {}
        for name, query in queries.items():
            code, value = query()
            self._check_linear_rail_code(f"query linear-rail {name}", code)
            rail_status[name] = value
        return rail_status
    
    def home(self, wait=True, speed=30):
        joint_home = self.config['initial_angles']
    
        code = self.arm.set_servo_angle(
            angle=joint_home,
            speed=speed,
            is_radian=False,
            wait=wait,
        )
        if code != 0:
            raise RuntimeError(f"Failed to home arm in joint space, code={self._describe_api_code(code)}")
    
        self.log_debug(f"Arm homed to joint angles: {joint_home}")
        return
    
    def _interpolate(self, a, b, steps):
        a = np.array(a)
        b = np.array(b)

        for i in range(steps):
            yield (a + (b - a) * i / steps).tolist()

    def _load_trajectory(self, filename):
        with open(self.traj_dir / filename, "r") as f:
            trajectory = json.load(f)
        if not isinstance(trajectory, list) or not trajectory:
            raise ValueError("Trajectory must contain one or more joint-angle poses")
        return trajectory

    def play(self, filename, dt=0.02, interp_steps=5):
        """Play a joint trajectory from the robot's already prepared entry pose."""
        if not filename:
            self.log_error("No file provided for trajectory.")
            return

        try:
            trajectory = self._load_trajectory(filename)
        except ValueError:
            self.log_error("Empty trajectory.")
            return

        self.arm.clean_warn()
        self.arm.clean_error()
        self.arm.motion_enable(True)

        self.arm.set_state(4) # reset
        time.sleep(1.0)

        # Station playback is explicitly pre-positioned with prepare_station.
        # Do not calculate or command a Cartesian start move here: trajectories
        # are recorded to start at the station's entry joint pose.
        self.arm.set_mode(0)
        self.arm.set_state(0) # ready
        time.sleep(1.0)

        # Servo mode
        self.arm.set_mode(1)
        self.arm.set_state(0) # ready
        time.sleep(1.0)

        self.log_debug(f"Playing {len(trajectory)} points (smoothed)...")

        try:
            for i in range(len(trajectory) - 1):

                start = trajectory[i]
                end = trajectory[i + 1]

                for angles in self._interpolate(start, end, interp_steps):

                    self.arm.set_servo_angle_j(
                        angles,
                        speed=40,
                        is_radian=False,
                        wait=False
                    )

                    time.sleep(dt)

        except KeyboardInterrupt:
            self.log_debug("Playback interrupted")

        finally:
            # return to safe state
            time.sleep(1.0)
            self.arm.set_mode(0)
            self.arm.set_state(0)

            self.log_debug("Playback finished and robot reset")

    def teach(self, filename, dt=0.1, station=None):
        """Record a trajectory, optionally saving it in a configured station directory."""
        filename = self._trajectory_filename(filename, station=station)
        self.arm.clean_warn()
        self.arm.clean_error()

        self.arm.motion_enable(True)

        self.arm.set_state(4)
        time.sleep(0.5)

        self.arm.set_mode(2)
        self.arm.set_state(0)

        self.log_info("Recording... Ctrl+C to stop from terminal or intruppt in a jupyter notebook")

        traj = []
        last = None

        try:
            while True:
                code, angles = self.arm.get_servo_angle(is_radian=False)

                if code == 0 and angles != last:
                    traj.append(angles)
                    last = angles
                    print(angles)

                time.sleep(dt)

        except KeyboardInterrupt:
            pass
        
        self.traj_dir.mkdir(parents=True, exist_ok=True)

        output_path = self.traj_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(traj, f, indent=2)

        self.arm.set_mode(0)
        self.arm.set_state(0)

        self.log_info(f"Saved {len(traj)} points to {filename}")
    
    def status(self):
        state_code, state = self.arm.get_state()
        if state_code != 0:
            return f"xArm status unavailable: state query failed with {self._describe_api_code(state_code)}"

        # The xArm Python SDK exposes mode as a report-stream property; unlike
        # state, it has no get_mode() method (including SDK 1.17.x).
        try:
            mode = self.arm.mode
        except (AttributeError, RuntimeError):
            return (
                f"xArm state: {self._describe_feedback_state(state)} ({state}); "
                "mode unavailable (enable the xArm report stream to read mode)"
            )

        return (
            f"xArm is {self._describe_feedback_state(state)} "
            f"in {self._describe_mode(mode)}"
        )
    
    def disconnect(self):
        self.arm.disconnect()
        self.log_debug("Arm disconnected")

    def list_trajectories(self):
        traj_dir = self.traj_dir
        if not traj_dir.exists():
            self.log_warning(f"Trajectory directory {traj_dir} does not exist.")
            return []
    
        traj_files = list(traj_dir.glob("*.json"))
        traj_names = [f.stem for f in traj_files]
        self.log_debug(f"Found trajectories: {traj_names}")
        return traj_names
    
if __name__ == "__main__":
    from AFL.automation.shared.launcher import *
