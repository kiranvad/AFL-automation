from xarm.wrapper import XArmAPI
import time
import json

arm = XArmAPI("192.168.1.201")


def teach_and_save(arm, dt=0.1):

    filename = input("Output filename: ").strip()
    if not filename:
        filename = "trajectory.json"

    arm.clean_warn()
    arm.clean_error()

    arm.motion_enable(True)

    arm.set_state(4)
    time.sleep(0.5)

    arm.set_mode(2)
    arm.set_state(0)

    print("Recording... Ctrl+C to stop")

    traj = []
    last = None

    try:
        while True:
            code, angles = arm.get_servo_angle(is_radian=False)

            if code == 0 and angles != last:
                traj.append(angles)
                last = angles
                print(angles)

            time.sleep(dt)

    except KeyboardInterrupt:
        pass

    with open(filename, "w") as f:
        json.dump(traj, f, indent=2)

    arm.set_mode(0)
    arm.set_state(0)

    print(f"Saved {len(traj)} points to {filename}")

if __name__ == "__main__":
    teach_and_save(arm)