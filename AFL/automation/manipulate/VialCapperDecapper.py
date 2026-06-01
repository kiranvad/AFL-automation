import time
import threading

import RPi.GPIO as GPIO
import board
import busio
from adafruit_pca9685 import PCA9685
from adafruit_motor import servo

from AFL.automation.APIServer.Driver import Driver


class VialCapperDriver(Driver):
    """Driver for a simple stepper + servo-based vial capper/decapper.
    Designed for a stepper-driven Z-axis and a single servo gripper,
    but can be adapted to other configurations by changing the defaults and logic as needed.

    Hardware config is stored in defaults so the generated AFL config file captures
    the GPIO pins, motion calibration, and servo settings used by this driver.

    from AFL.automation.APIServer.Client import Client

    capper = Client(ip="192.168.1.50", port="5052", username="tester")

    print(capper.status())
    capper.move_down(distance_mm=10.0)
    capper.grip_close()
    capper.move_up(distance_mm=10.0)

    capper.rotate_screw(n_rotations=2, direction="tighten")
    capper.rotate_screw(n_rotations=1.5, direction="loosen")
    """
    defaults = {
        "step_pin": 20,
        "dir_pin": 21,
        "enable_pin": 16,
        "dir_up": 1,
        "dir_down": 0,
        "step_delay": 0.01,
        "steps_per_mm": 200,
        "z_travel_mm": 30.0,
        "motor_steps_per_rev": 48,
        "microstep": 16,
        "screw_dir_tighten": 1,
        "screw_dir_loosen": 0,
        "servo_channel": 0,
        "servo_min_pulse": 500,
        "servo_max_pulse": 2500,
        "gripper_open_angle": 120,
        "gripper_closed_angle": 55,
        "gripper_settle_s": 0.5,
        "pca9685_address": 0x40,
    }

    def __init__(self, name="VialCapperDriver", overrides=None):
        Driver.__init__(
            self,
            name=name,
            defaults=self.gather_defaults(),
            overrides=overrides,
        )

        self._lock = threading.Lock()
        self._z_position_steps = 0

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        GPIO.setup(self.config["step_pin"], GPIO.OUT)
        GPIO.setup(self.config["dir_pin"], GPIO.OUT)
        GPIO.setup(self.config["enable_pin"], GPIO.OUT)

        GPIO.output(self.config["enable_pin"], GPIO.LOW)

        i2c = busio.I2C(board.SCL, board.SDA)
        self.pca = PCA9685(i2c, address=self.config["pca9685_address"])
        self.pca.frequency = 50

        self.gripper = servo.Servo(
            self.pca.channels[self.config["servo_channel"]],
            min_pulse=self.config["servo_min_pulse"],
            max_pulse=self.config["servo_max_pulse"],
        )

        self.grip_open()

    def _step(self, direction, steps, step_delay=None):
        if step_delay is None:
            step_delay = self.config["step_delay"]

        GPIO.output(self.config["dir_pin"], GPIO.HIGH if direction else GPIO.LOW)

        for _ in range(int(steps)):
            GPIO.output(self.config["step_pin"], GPIO.HIGH)
            time.sleep(step_delay)
            GPIO.output(self.config["step_pin"], GPIO.LOW)
            time.sleep(step_delay)

        if direction == self.config["dir_up"]:
            self._z_position_steps += int(steps)
        else:
            self._z_position_steps -= int(steps)

    def _mm_to_steps(self, distance_mm):
        return int(round(float(distance_mm) * float(self.config["steps_per_mm"])))

    def _rotation_to_steps(self, n_rotations):
        steps_per_rotation = int(self.config["motor_steps_per_rev"]) * int(self.config["microstep"])
        return int(round(float(n_rotations) * steps_per_rotation))

    @Driver.unqueued()
    def status(self):
        return [
            f"z_position_steps={self._z_position_steps}",
            f"step_pin={self.config['step_pin']}",
            f"dir_pin={self.config['dir_pin']}",
            f"enable_pin={self.config['enable_pin']}",
            f"motor_steps_per_rev={self.config['motor_steps_per_rev']}",
            f"microstep={self.config['microstep']}",
            f"screw_dir_tighten={self.config['screw_dir_tighten']}",
            f"screw_dir_loosen={self.config['screw_dir_loosen']}",
            f"servo_channel={self.config['servo_channel']}",
        ]

    @Driver.queued()
    def enable_motor(self):
        GPIO.output(self.config["enable_pin"], GPIO.LOW)
        return "stepper enabled"

    @Driver.queued()
    def disable_motor(self):
        GPIO.output(self.config["enable_pin"], GPIO.HIGH)
        return "stepper disabled"

    @Driver.queued()
    def move_up(self, distance_mm=5.0):
        with self._lock:
            steps = self._mm_to_steps(distance_mm)
            self._step(self.config["dir_up"], steps)
        return f"moved up {distance_mm} mm"

    @Driver.queued()
    def move_down(self, distance_mm=5.0):
        with self._lock:
            steps = self._mm_to_steps(distance_mm)
            self._step(self.config["dir_down"], steps)
        return f"moved down {distance_mm} mm"

    @Driver.queued()
    def rotate_screw(self, n_rotations=1.0, direction="tighten"):
        with self._lock:
            if direction == "tighten":
                step_direction = self.config["screw_dir_tighten"]
            elif direction == "loosen":
                step_direction = self.config["screw_dir_loosen"]
            else:
                raise ValueError("direction must be 'tighten' or 'loosen'")

            steps = self._rotation_to_steps(n_rotations)
            self._step(step_direction, steps)

        return f"rotated screw {n_rotations} turns in {direction} direction"

    @Driver.queued()
    def grip_open(self):
        with self._lock:
            self.gripper.angle = self.config["gripper_open_angle"]
            time.sleep(self.config["gripper_settle_s"])
        return "gripper opened"

    @Driver.queued()
    def grip_close(self):
        with self._lock:
            self.gripper.angle = self.config["gripper_closed_angle"]
            time.sleep(self.config["gripper_settle_s"])
        return "gripper closed"

    @Driver.queued()
    def home(self):
        # Replace this with a real limit-switch homing routine if available.
        with self._lock:
            self._z_position_steps = 0
        return "logical home set"

    @Driver.queued()
    def cap_vial(self, approach_mm=20.0):
        with self._lock:
            self.gripper.angle = self.config["gripper_open_angle"]
            time.sleep(self.config["gripper_settle_s"])

            self._step(self.config["dir_down"], self._mm_to_steps(approach_mm))
            self.gripper.angle = self.config["gripper_closed_angle"]
            time.sleep(self.config["gripper_settle_s"])

        return "cap_vial sequence complete"

    @Driver.queued()
    def decap_vial(self, retract_mm=20.0):
        with self._lock:
            self.gripper.angle = self.config["gripper_closed_angle"]
            time.sleep(self.config["gripper_settle_s"])

            self._step(self.config["dir_up"], self._mm_to_steps(retract_mm))
            self.gripper.angle = self.config["gripper_open_angle"]
            time.sleep(self.config["gripper_settle_s"])

        return "decap_vial sequence complete"


_DEFAULT_PORT = 5052
_DEFAULT_CUSTOM_CONFIG = {
    "_classname": "AFL.automation.loading.VialCapperDriver.VialCapperDriver"
}


if __name__ == "__main__":
    from AFL.automation.shared.launcher import *