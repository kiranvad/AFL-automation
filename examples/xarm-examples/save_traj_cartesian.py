from xarm.wrapper import XArmAPI
import time
import json

arm = XArmAPI("192.168.1.201")

def teach_and_save_cartesian(arm, dt=0.1):

    filename = input("Output filename: ").strip()
    if not filename:
        filename = "trajectory_cartesian.json"

    arm.clean_warn()
    arm.clean_error()

    arm.motion_enable(True)

    arm.set_state(4)
    time.sleep(0.5)

    # Mode 2 is fine for teaching (manual guidance / drag)
    arm.set_mode(2)
    arm.set_state(0)

    print("Recording Cartesian poses... Ctrl+C to stop")

    traj = []
    last = None

    try:
        while True:
            code, pose = arm.get_position(is_radian=False)
            # pose = [x, y, z, roll, pitch, yaw]

            if code == 0 and pose != last:
                traj.append(pose)
                last = pose
                print(pose)

            time.sleep(dt)

    except KeyboardInterrupt:
        pass

    with open(filename, "w") as f:
        json.dump(traj, f, indent=2)

    arm.set_mode(0)
    arm.set_state(0)

    print(f"Saved {len(traj)} Cartesian points to {filename}")

if __name__ == "__main__":
    teach_and_save_cartesian(arm)