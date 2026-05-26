from AFL.automation.APIServer.Driver import Driver
from xarm.wrapper import XArmAPI
import time 
from pathlib import Path
import json
import numpy as np

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
        'initial_angles': [-90.0, -43.4, 0.0, 25.0, 5.0, 60.0, 0.0],
        'gripper_open_position': 600,
        'gripper_closed_position': 110,
        'gripper_speed': 2000,
        'traj_dir': './afl/xarm_trajectories/'
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

    def _describe_api_code(self, code):
        return XARM_API_CODE_DESCRIPTIONS.get(code, f"unknown API code {code}")

    def _describe_mode(self, mode):
        return XARM_MODE_DESCRIPTIONS.get(mode, f"unknown mode {mode}")

    def _describe_feedback_state(self, state):
        return XARM_STATE_FEEDBACK_DESCRIPTIONS.get(state, f"unknown feedback state {state}")

    def _describe_set_state(self, state):
        return XARM_STATE_SET_DESCRIPTIONS.get(state, f"unknown set-state value {state}")
    
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

    def play(self, filename, dt=0.02, interp_steps=5):
        if not filename:
            self.log_error("No file provided for trajectory.")
            return

        with open(self.traj_dir / filename, "r") as f:
            trajectory = json.load(f)

        if not trajectory:
            self.log_error("Empty trajectory.")
            return

        self.arm.clean_warn()
        self.arm.clean_error()
        self.arm.motion_enable(True)

        self.arm.set_state(4) # reset
        time.sleep(1.0)

        # Make the iniital move to the start of the trajectory 
        # in position control mode for safety
        self.arm.set_mode(0)
        self.arm.set_state(0) # ready
        time.sleep(1.0)

        _, pose_start = self.arm.get_forward_kinematics(trajectory[0])
        _, pose_current = self.arm.get_position(is_radian=False)
        self.log_debug(f"Moving to trajectory start position: {pose_start}"
                        f" from current position: {pose_current}")
        self.arm.set_position(*pose_start, wait=True)

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

    def teach(self, filename, dt=0.1):
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
        mode_code, mode = self.arm.get_mode()
    
        if state_code != 0:
            return f"xArm status unavailable: state query failed with {self._describe_api_code(state_code)}"
    
        if mode_code != 0:
            return (
                f"xArm state: {self._describe_feedback_state(state)} ({state}); "
                f"mode unavailable: {self._describe_api_code(mode_code)}"
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