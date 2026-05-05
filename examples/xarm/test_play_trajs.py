from xarm.wrapper import XArmAPI
import time
import json
import numpy as np

arm = XArmAPI("192.168.1.201")


def interpolate(a, b, steps):
    a = np.array(a)
    b = np.array(b)

    for i in range(steps):
        yield (a + (b - a) * i / steps).tolist()


def play_trajectory(arm):

    filename = input("Trajectory file to play: ").strip()
    if not filename:
        print("No file provided.")
        return

    with open(filename, "r") as f:
        trajectory = json.load(f)

    if not trajectory:
        print("Empty trajectory.")
        return

    arm.clean_warn()
    arm.clean_error()

    arm.motion_enable(True)

    # Stop previous motion safely
    arm.set_state(4)
    time.sleep(0.3)

    # Servo streaming mode
    arm.set_mode(1)
    arm.set_state(0)

    print(f"Playing {len(trajectory)} points (smoothed)...")

    dt = 0.02        # 50 Hz command rate (important for smoothness)
    interp_steps = 5 # smoothing factor between recorded points

    try:
        for i in range(len(trajectory) - 1):

            start = trajectory[i]
            end = trajectory[i + 1]

            for angles in interpolate(start, end, interp_steps):

                arm.set_servo_angle_j(
                    angles,
                    speed=40,
                    is_radian=False,
                    wait=False
                )

                time.sleep(dt)

    except KeyboardInterrupt:
        print("Playback interrupted")

    finally:
        # Always return to safe state
        arm.set_state(4)
        time.sleep(0.2)
        arm.set_mode(0)
        arm.set_state(0)

        print("Playback finished and robot reset")


if __name__ == "__main__":
    play_trajectory(arm)