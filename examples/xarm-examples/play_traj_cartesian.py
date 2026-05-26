from xarm.wrapper import XArmAPI
import time
import json
import numpy as np

arm = XArmAPI("192.168.1.201")


def play_cartesian_trajectory(arm, filename):

    if not filename:
        print("No file provided.")
        return

    with open(filename, "r") as f:
        trajectory = json.load(f)

    if not trajectory or len(trajectory) < 2:
        print("Trajectory too short.")
        return

    arm.clean_warn()
    arm.clean_error()
    arm.motion_enable(True)

    arm.set_state(4)
    time.sleep(0.5)

    # Cartesian velocity mode
    arm.set_mode(5)
    arm.set_state(0)

    print(f"Playing {len(trajectory)} Cartesian points (velocity control)...")

    dt = 0.02         # 50 Hz
    interp_steps = 5  # smoothing between waypoints

    try:
        for i in range(len(trajectory) - 1):

            p1 = np.array(trajectory[i], dtype=float)
            p2 = np.array(trajectory[i + 1], dtype=float)

            delta = p2 - p1

            # velocity = delta / total_time
            total_time = dt * interp_steps
            vel = delta / total_time

            # Optional: clamp velocity (VERY important for safety)
            max_linear = 200.0   # mm/s
            max_angular = 100.0  # deg/s

            vel[:3] = np.clip(vel[:3], -max_linear, max_linear)
            vel[3:] = np.clip(vel[3:], -max_angular, max_angular)

            for _ in range(interp_steps):
                arm.vc_set_cartesian_velocity(
                    vel.tolist(),
                    is_radian=False
                )
                time.sleep(dt)

    except KeyboardInterrupt:
        print("Playback interrupted")

    finally:
        # Stop motion cleanly
        arm.vc_set_cartesian_velocity([0, 0, 0, 0, 0, 0], is_radian=False)
        time.sleep(0.1)

        arm.set_mode(0)
        arm.set_state(0)

        print("Playback finished and robot reset")


if __name__ == "__main__":
    filename = input("Trajectory file to play: ").strip()
    play_cartesian_trajectory(arm, filename)