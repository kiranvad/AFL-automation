from xarm.wrapper import XArmAPI

arm = XArmAPI("192.168.1.201")

arm.motion_enable(True)
arm.clean_error()
arm.clean_warn()
arm.set_mode(0)
arm.set_state(0)
arm.move_gohome(wait=True)

input("Ready to start? Press Enter")

# 1. Go to pickup position above the slide
print("Playing pickup trajectory")
arm.playback_trajectory(filename = 'pickup.json')

# 2. Vacuum ON (attach slide)
print("Vacuum ON: Collecting the glass slide from 8D1")
arm.set_vacuum_gripper(True, wait=False)

# 3. Return the glass lide to the pickup position (lift up)
print("Playing drop-off trajectory")
arm.playback_trajectory(filename = 'dropoff.json')

# 4. Vacuum OFF
print("Vacuum OFF: Releasing the glass slide")
arm.set_vacuum_gripper(False, wait=False)

print("Done. Moving the arm to home position.")

arm.move_gohome(wait=True)
