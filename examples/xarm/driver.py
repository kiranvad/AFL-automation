from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.APIServer.Driver import Driver

try:
    from xarm.wrapper import XArmAPI
except ImportError as error:
    print(f"Failed to import XArmAPI: {error}")
    XArmAPI = None


class XArmTrajectoryDriver(Driver):
    """Driver example for connecting to an xArm and managing JSON trajectories.
    """

    defaults = {
        "robot_ip": "192.168.1.201",
        "trajectory_dir": "~/.afl/xarm_trajectories",
        "recording_dt": 0.1,
        "playback_dt": 0.02,
        "playback_interp_steps": 5,
        "joint_speed": 40.0,
        "joint_acceleration": 200.0,
        "is_radian": False,
        "home_joint_angles": [-1.2, -14.2, 2.8, 58.1, 0.0, 74.4, 1.5],
        "home_speed": 20.0,
        "home_gripper_position": 600,
    }

    def __init__(self, overrides: Optional[Dict] = None, data=None):
        Driver.__init__(
            self,
            name="XArmTrajectoryDriver",
            defaults=self.gather_defaults(),
            overrides=overrides,
        )
        self.data = data
        self.arm = None
        self.connected_ip = None
        self.active_trajectory_name = None
        self.current_trajectory = self._new_trajectory_payload(name=None)

    def _require_sdk(self):
        if XArmAPI is None:
            raise ImportError(
                "xArm Python SDK is not installed. Install the package that provides xarm.wrapper.XArmAPI."
            )

    def _require_connection(self):
        if self.arm is None:
            raise RuntimeError("xArm is not connected. Call connect first.")
        return self.arm

    def _trajectory_dir(self, folder: Optional[str] = None) -> Path:
        target = folder or self.config["trajectory_dir"]
        path = Path(target).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _trajectory_path(self, name: str, folder: Optional[str] = None) -> Path:
        safe_name = name.strip()
        if not safe_name:
            raise ValueError("Trajectory name must not be empty.")
        if not safe_name.endswith(".json"):
            safe_name = f"{safe_name}.json"
        return self._trajectory_dir(folder) / safe_name

    def _new_trajectory_payload(self, name: Optional[str]) -> Dict[str, object]:
        return {
            "name": name,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "robot_ip": self.connected_ip or self.config["robot_ip"],
            "waypoints": [],
        }

    def _normalize_joint_angles(self, angles: List[float]) -> List[float]:
        if len(angles) < 5:
            raise ValueError("Expected at least 5 joint angles for xArm trajectory playback.")
        return [float(value) for value in angles]

    def _normalize_waypoint(
        self,
        angles: List[float],
        speed: Optional[float] = None,
        mvacc: Optional[float] = None,
        wait: bool = False,
    ) -> Dict[str, object]:
        return {
            "angles": self._normalize_joint_angles(angles),
            "speed": float(speed if speed is not None else self.config["joint_speed"]),
            "mvacc": float(
                mvacc if mvacc is not None else self.config["joint_acceleration"]
            ),
            "wait": bool(wait),
            "is_radian": bool(self.config["is_radian"]),
        }

    def _append_waypoint(self, waypoint: Dict[str, object]):
        self.current_trajectory["waypoints"].append(waypoint)

    def _prepare_arm(self):
        arm = self._require_connection()
        arm.clean_warn()
        arm.clean_error()
        arm.motion_enable(True)
        return arm

    def _set_safe_mode(self):
        arm = self._require_connection()
        arm.set_mode(0)
        arm.set_state(0)

    def _home_waypoint(self) -> Dict[str, object]:
        return self._normalize_waypoint(
            angles=self.config["home_joint_angles"],
            speed=self.config["home_speed"],
            mvacc=self.config["joint_acceleration"],
            wait=True,
        )

    def _execute_waypoint(self, waypoint: Dict[str, object], wait_override: Optional[bool] = None):
        arm = self._prepare_arm()
        wait = waypoint["wait"] if wait_override is None else bool(wait_override)
        code = arm.set_servo_angle(
            angle=waypoint["angles"],
            speed=waypoint["speed"],
            mvacc=waypoint["mvacc"],
            is_radian=waypoint["is_radian"],
            wait=wait,
        )
        if code != 0:
            raise RuntimeError(f"xArm move failed with code {code}")
        return waypoint

    def _interpolate(self, start: List[float], end: List[float], steps: int) -> List[List[float]]:
        if steps <= 1:
            return [end]
        points = []
        for index in range(steps):
            fraction = index / float(steps)
            points.append(
                [
                    start_value + (end_value - start_value) * fraction
                    for start_value, end_value in zip(start, end)
                ]
            )
        points.append(end)
        return points

    @Driver.unqueued()
    def connect(self, ip_address: Optional[str] = None):
        """Connect to the xArm using the provided IP address or configured default."""
        self._require_sdk()
        target_ip = ip_address or self.config["robot_ip"]
        if self.arm is not None and self.connected_ip == target_ip:
            return {"connected": True, "ip_address": self.connected_ip}

        if self.arm is not None:
            self.disconnect()

        arm = XArmAPI(target_ip)
        arm.motion_enable(True)
        arm.clean_error()
        arm.clean_warn()
        arm.set_mode(0)
        arm.set_state(0)

        self.arm = arm
        self.connected_ip = target_ip
        self.config["robot_ip"] = target_ip
        self.current_trajectory["robot_ip"] = target_ip
        return {"connected": True, "ip_address": target_ip}

    @Driver.unqueued()
    def disconnect(self):
        """Disconnect from the current xArm session."""
        if self.arm is not None:
            try:
                self.arm.disconnect()
            finally:
                self.arm = None
                self.connected_ip = None
        return {"connected": False}

    @Driver.unqueued()
    def status(self):
        """Return connection and trajectory state for the xArm driver."""
        return {
            "connected": self.arm is not None,
            "ip_address": self.connected_ip or self.config["robot_ip"],
            "trajectory_dir": str(self._trajectory_dir()),
            "active_trajectory_name": self.active_trajectory_name,
            "buffered_waypoints": len(self.current_trajectory["waypoints"]),
        }

    @Driver.unqueued()
    def list_trajectories(self, folder: Optional[str] = None):
        """List saved trajectory JSON files in the selected folder."""
        directory = self._trajectory_dir(folder)
        return sorted(path.name for path in directory.glob("*.json"))

    @Driver.unqueued()
    def get_current_trajectory(self):
        """Return the currently buffered trajectory payload."""
        return self.current_trajectory

    @Driver.queued()
    def start_trajectory(self, name: str, folder: Optional[str] = None):
        """Reset the in-memory trajectory buffer and set the active trajectory name."""
        self._trajectory_dir(folder)
        self.active_trajectory_name = name
        self.current_trajectory = self._new_trajectory_payload(name=name)
        return {
            "active_trajectory_name": self.active_trajectory_name,
            "trajectory_dir": str(self._trajectory_dir(folder)),
        }

    @Driver.queued()
    def reset_trajectory(self, name: Optional[str] = None):
        """Clear the in-memory trajectory buffer, optionally setting a new name."""
        self.active_trajectory_name = name
        self.current_trajectory = self._new_trajectory_payload(name=name)
        return self.current_trajectory

    @Driver.queued()
    def move_joints(
        self,
        angles: List[float],
        speed: Optional[float] = None,
        mvacc: Optional[float] = None,
        wait: bool = True,
        record: bool = True,
    ):
        """Move the arm to a joint-angle waypoint and optionally record it."""
        waypoint = self._normalize_waypoint(angles=angles, speed=speed, mvacc=mvacc, wait=wait)
        self._execute_waypoint(waypoint)
        if record:
            self._append_waypoint(waypoint)
        return waypoint

    @Driver.queued()
    def home(self, record: bool = False):
        """Move the arm to the configured home joint angles and open the gripper."""
        arm = self._require_connection()
        waypoint = self._home_waypoint()
        self._execute_waypoint(waypoint, wait_override=True)

        enable_code = arm.set_gripper_enable(True)
        if enable_code != 0:
            raise RuntimeError(f"xArm gripper enable failed with code {enable_code}")

        gripper_code = arm.set_gripper_position(
            int(self.config["home_gripper_position"]),
            wait=True,
        )
        if gripper_code != 0:
            raise RuntimeError(f"xArm gripper move failed with code {gripper_code}")

        if record:
            self._append_waypoint(waypoint)

        return {
            "home_angles": waypoint["angles"],
            "speed": waypoint["speed"],
            "gripper_enabled": True,
            "gripper_position": int(self.config["home_gripper_position"]),
            "recorded": bool(record),
        }

    @Driver.queued()
    def record_current_pose(
        self,
        speed: Optional[float] = None,
        mvacc: Optional[float] = None,
        wait: bool = False,
    ):
        """Read the current joint angles from the robot and append them to the trajectory buffer."""
        arm = self._require_connection()
        code, angles = arm.get_servo_angle(is_radian=bool(self.config["is_radian"]))
        if code != 0:
            raise RuntimeError(f"xArm get_servo_angle failed with code {code}")
        waypoint = self._normalize_waypoint(angles=angles, speed=speed, mvacc=mvacc, wait=wait)
        self._append_waypoint(waypoint)
        return waypoint

    @Driver.queued()
    def teach_trajectory(
        self,
        name: str,
        folder: Optional[str] = None,
        duration: Optional[float] = None,
        dt: Optional[float] = None,
    ):
        """Record live joint angles into a trajectory JSON file until duration expires or interrupted."""
        arm = self._require_connection()
        sample_dt = float(dt if dt is not None else self.config["recording_dt"])
        self.active_trajectory_name = name
        self.current_trajectory = self._new_trajectory_payload(name=name)

        arm.clean_warn()
        arm.clean_error()
        arm.motion_enable(True)
        arm.set_state(4)
        time.sleep(0.5)
        arm.set_mode(2)
        arm.set_state(0)

        start_time = time.time()
        last_angles = None
        try:
            while True:
                code, angles = arm.get_servo_angle(is_radian=bool(self.config["is_radian"]))
                if code == 0 and angles != last_angles:
                    waypoint = self._normalize_waypoint(
                        angles=angles,
                        speed=self.config["joint_speed"],
                        mvacc=self.config["joint_acceleration"],
                        wait=False,
                    )
                    self._append_waypoint(waypoint)
                    last_angles = list(angles)
                if duration is not None and (time.time() - start_time) >= float(duration):
                    break
                time.sleep(sample_dt)
        finally:
            self._set_safe_mode()

        return self._save_trajectory(name=name, folder=folder)

    def _save_trajectory(self, name: Optional[str] = None, folder: Optional[str] = None):
        """Save the current trajectory buffer as JSON in the selected folder."""
        target_name = name or self.active_trajectory_name
        if not target_name:
            raise ValueError("No trajectory name provided and no active trajectory is set.")
        self.current_trajectory["name"] = target_name
        self.current_trajectory["robot_ip"] = self.connected_ip or self.config["robot_ip"]
        path = self._trajectory_path(target_name, folder)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(self.current_trajectory, handle, indent=2)
        self.active_trajectory_name = target_name
        return {
            "saved": True,
            "name": target_name,
            "path": str(path),
            "waypoint_count": len(self.current_trajectory["waypoints"]),
        }

    @Driver.queued()
    def load_trajectory(self, name: str, folder: Optional[str] = None):
        """Load a trajectory JSON file from the selected folder into memory."""
        path = self._trajectory_path(name, folder)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if "waypoints" not in payload or not isinstance(payload["waypoints"], list):
            raise ValueError("Trajectory JSON must contain a 'waypoints' list.")
        self.current_trajectory = payload
        self.active_trajectory_name = str(payload.get("name") or name)
        return {
            "loaded": True,
            "name": self.active_trajectory_name,
            "path": str(path),
            "waypoint_count": len(self.current_trajectory["waypoints"]),
        }

    @Driver.queued()
    def play_trajectory(
        self,
        name: Optional[str] = None,
        folder: Optional[str] = None,
        dt: Optional[float] = None,
        interp_steps: Optional[int] = None,
    ):
        """Play a saved or currently loaded trajectory using smoothed servo streaming."""
        arm = self._require_connection()
        if name is not None:
            self.load_trajectory(name=name, folder=folder)

        waypoints = self.current_trajectory.get("waypoints", [])
        if not waypoints:
            raise ValueError("Current trajectory is empty.")

        playback_dt = float(dt if dt is not None else self.config["playback_dt"])
        smoothing_steps = int(
            interp_steps if interp_steps is not None else self.config["playback_interp_steps"]
        )

        arm.clean_warn()
        arm.clean_error()
        arm.motion_enable(True)
        arm.set_state(4)
        time.sleep(0.3)
        arm.set_mode(1)
        arm.set_state(0)

        try:
            if len(waypoints) == 1:
                self._execute_waypoint(waypoints[0], wait_override=False)
                time.sleep(playback_dt)
            else:
                for index in range(len(waypoints) - 1):
                    start = self._normalize_joint_angles(waypoints[index]["angles"])
                    end = self._normalize_joint_angles(waypoints[index + 1]["angles"])
                    for angles in self._interpolate(start, end, smoothing_steps):
                        code = arm.set_servo_angle_j(
                            angles,
                            speed=waypoints[index + 1].get("speed", self.config["joint_speed"]),
                            is_radian=bool(self.config["is_radian"]),
                            wait=False,
                        )
                        if code != 0:
                            raise RuntimeError(f"xArm playback failed with code {code}")
                        time.sleep(playback_dt)
        finally:
            time.sleep(0.2)
            self._set_safe_mode()

        return {
            "played": True,
            "name": self.active_trajectory_name,
            "waypoint_count": len(waypoints),
        }



def build_server(
    host: str = "127.0.0.1",
    port: int = 5052,
    overrides: Optional[Dict] = None,
    data=None,
):
    server = APIServer("XArmTrajectory", data=data)
    server.add_standard_routes()
    server.create_queue(XArmTrajectoryDriver(overrides=overrides, data=data))
    return server, host, port


if __name__ == "__main__":
    server, host, port = build_server()
    server.run(host=host, port=port, debug=False, use_reloader=False)
