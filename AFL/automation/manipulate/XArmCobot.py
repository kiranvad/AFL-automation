from AFL.automation.APIServer.Driver import Driver
from xarm.wrapper import XArmAPI
import time 
from pathlib import Path
import json
import numpy as np

class XArmCobot(Driver):
    '''
        A class to control the XArm in Cobot mode.
    '''
    overrides = {}
    defaults = {
        'ip': '192.168.1.201',
        'initial_position': [400.0, 0.0, 400.0, -180, 0, 0],
        'gripper_open_position': 600,
        'gripper_closed_position': 110,
        'gripper_speed': 2000,
        'traj_dir': './afl/xarm_trajectories/'
    }
    def __init__(self,overrides={}):
        self._app = None

        Driver.__init__(self,name='XArmCobot',defaults=self.gather_defaults(),overrides=overrides)
        self.arm = XArmAPI(self.config['ip'])
        self.arm.motion_enable(True)
        self.arm.clean_error()
        self.arm.clean_warn()
        self.arm.set_mode(0)
        self.arm.set_state(0)
        self.traj_dir = Path(self.config['traj_dir']).resolve()

    def home(self):
        self.arm.set_position(*self.config['initial_position'], wait=True)
        self.log_debug("Arm homed to initial position: {}".format(self.config['initial_position']))
        return
    
    def _interpolate(self, a, b, steps):
        a = np.array(a)
        b = np.array(b)

        for i in range(steps):
            yield (a + (b - a) * i / steps).tolist()

    def play(self, filename):
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

        # Make the iniital move to the start of the trajectory in position control mode for safety
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

        dt = 0.02        # 50 Hz command rate (important for smoothness)
        interp_steps = 5 # smoothing factor between recorded points

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

        self.log_info("Recording... Ctrl+C to stop")

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
        code, state = self.arm.get_state()
        if code == 0:
            return {"state": state}
        else:
            self.log_error("Failed to get arm state with code: {}".format(code))
            return {"state": None}
        
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