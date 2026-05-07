from xarm.wrapper import XArmAPI
from test_play_trajs import play_trajectory

arm = XArmAPI("192.168.1.201")

arm.motion_enable(True)
arm.clean_error()
arm.clean_warn()
arm.set_mode(0)
arm.set_state(0)

INIT_CONFIG = {
    'joint1': -1.2,
    'joint2': -14.2,
    'joint3': 2.8,
    'joint4': 58.1,
    'joint5': 0,
    'joint6': 74.4,
    'joint7': 1.5,
}
joint_names = [f'joint{i}' for i in range(1, 8)]
INIT_CONFIG_VALUES = [INIT_CONFIG[name] for name in joint_names]

def home():
    arm.set_servo_angle(angle=INIT_CONFIG_VALUES, is_radian=False, speed=20, wait=True)

home()
arm.set_gripper_enable(True)
arm.set_gripper_position(600, wait=True)

input("Ready to start? Press Enter")
# 1. Go to pickup position above the slide
print("Playing pickup trajectory")
arm.playback_trajectory(filename = './moveto_vial.traj')

# 2. Enable vial gripper (attach vial)
print("Vial gripper ON: Collecting the vial from 8B2")
arm.set_position(z=-20, relative=True, wait=True)
arm.set_gripper_position(100, wait=True)
arm.set_position(z=60, relative=True, wait=True)
home()
# 3. Play the shaking trajectory
play_trajectory(arm, './shake_vial.json')

print("Returnng the vial to 1A1")
arm.playback_trajectory(filename = './return_vial.traj')
arm.set_position(z=-20, relative=True, wait=True)

print("Vial gripper OFF: Releasing the vial")
arm.set_gripper_position(600, wait=True)

print("Moving the arm to home position.")
home()

