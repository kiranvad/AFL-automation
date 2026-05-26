from xarm.wrapper import XArmAPI
import time 
from test_play_trajs import play_trajectory 
from pathlib import Path

arm = XArmAPI("192.168.1.201")

arm.motion_enable(True)
arm.clean_error()
arm.clean_warn()
arm.set_mode(0)
arm.set_state(0)


INITIAL_POSITION = [400.0, 0.0, 400.0, -180, 0, 0]
GRIPPER_OPEN_POSITION = 600
GRIPPER_CLOSED_POSITION = 110
GRIPPER_SPEED = 2000
def home_arm(arm):
    arm.set_mode(0)
    arm.set_state(0)
    arm.set_position(*INITIAL_POSITION, wait=True)
    time.sleep(1.0)

    return 

print("Initiating the arm and gripper positions...")
arm.set_gripper_enable(True)
arm.set_gripper_position(GRIPPER_OPEN_POSITION, wait=True, speed=GRIPPER_SPEED)

input("Ready to start? Press Enter: \n")

TRAJ_DIR = Path('./trajs')

print("Playing pickup trajectory")
play_trajectory(arm, TRAJ_DIR / 'pick_vial_from_home.json')

print("Vial gripper ON: Collecting the vial from 8B2")
arm.set_gripper_position(GRIPPER_CLOSED_POSITION, wait=True, speed=GRIPPER_SPEED)

print("Returning the vial to home position")
play_trajectory(arm, TRAJ_DIR / 'return_vial_to_home.json')

for i in range(3):
    print("Shaking the vial for {}/{}...".format(i + 1, 3))
    play_trajectory(arm, TRAJ_DIR / 'shake_vial.json') 
    # only reset to safe state after the last shake    
    time.sleep(1.0)

print("Moving the arm to destination 1A1.")
play_trajectory(arm, TRAJ_DIR / 'move_vial_to_1.json')
_, pose_current = arm.get_position(is_radian=False)
print(f"Current pose: {pose_current}")
pose_current[2] += 10.0 # move the vial relatively up to drop it
print(f"Moving the vial up to drop it at: {pose_current}")
arm.set_position(*pose_current, wait=True) # move the vial up to drop it

print("Vial gripper OFF: Releasing the vial")
arm.set_gripper_position(GRIPPER_OPEN_POSITION, wait=True, speed=GRIPPER_SPEED)

print("Moving the arm to home position.")
play_trajectory(arm, TRAJ_DIR / 'move_arm_home.json')
print("Done! Returning the arm to home position and disconnecting...")
home_arm(arm)

arm.disconnect()
