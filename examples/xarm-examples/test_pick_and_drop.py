from xarm.wrapper import XArmAPI
import time
import json
import numpy as np

arm = XArmAPI("192.168.1.201")

arm.motion_enable(True)
arm.clean_error()
arm.clean_warn()
arm.set_mode(0)
arm.set_state(0)

def interpolate(a, b, steps):
    a = np.array(a)
    b = np.array(b)

    for i in range(steps):
        yield (a + (b - a) * i / steps).tolist()

def play_trajectory(arm, filename):

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


def pick_and_place():
    
    input("Ready to start? Press Enter")

    # 1. Go to pickup position above the slide
    print("Playing pickup trajectory")
    play_trajectory(arm, "./pickup.json")

    # 2. Vacuum ON (attach slide)
    print("Vacuum ON: Collecting the glass slide from 8D1")
    arm.set_vacuum_gripper(True, wait=False)

    # 3. Return the glass lide to the pickup position (lift up)
    print("Playing drop-off trajectory")
    play_trajectory(arm, "./dropoff.json")

    # 8. Vacuum OFF
    print("Vacuum OFF: Releasing the glass slide")
    arm.set_vacuum_gripper(False, wait=False)

    print("Done. Moving the arm to home position.")

    arm.move_gohome(wait=True)


if __name__ == "__main__":
    pick_and_place()