import pytest

from AFL.automation.manipulate.xarmcobot import XArmCobot
from AFL.automation.manipulate.xarmutils import JointPose, StationRegistry, xArmStation


def station_definition():
    return {
        "entry_joint_angles": [-270, -16, -4, 13.1, -5, -94.6, -180],
        "linear_rail_location": 650,
    }


def test_joint_pose_accepts_xarm6_and_xarm7_joint_angles():
    assert JointPose((0, 1, 2, 3, 4, 5)).angles == (0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
    assert len(JointPose((0, 1, 2, 3, 4, 5, 6)).angles) == 7
    with pytest.raises(ValueError, match="six or seven"):
        JointPose((0, 1, 2))


def test_registry_loads_serializable_station_definition():
    definition = station_definition()
    registry = StationRegistry.from_definitions({"ot2": definition})

    assert registry.names() == ["ot2"]
    assert registry.definition("ot2") == definition
    assert registry.get("ot2").linear_rail_location == 650.0


def test_registry_rejects_duplicate_station():
    station = xArmStation("ot2", JointPose((0, 1, 2, 3, 4, 5)))
    registry = StationRegistry((station,))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(station)


class FakeArm:
    def __init__(self):
        self.joint_moves = []

    def set_servo_angle(self, **kwargs):
        self.joint_moves.append(kwargs)
        return 0


def test_cobot_prepares_station_by_moving_rail_then_entry_joints():
    driver = object.__new__(XArmCobot)
    driver.config = {"station_entry_speed": 30.0}
    driver.station_registry = StationRegistry.from_definitions({"ot2": station_definition()})
    driver.arm = FakeArm()
    driver.log_info = lambda message: None
    rail_moves = []
    driver.move_linear_rail = lambda position, speed=None, wait=True: rail_moves.append(
        (position, speed, wait)
    )

    result = driver.prepare_station("ot2")

    assert rail_moves == [(650.0, None, True)]
    assert driver.arm.joint_moves == [{
        "angle": [-270.0, -16.0, -4.0, 13.1, -5.0, -94.6, -180.0],
        "speed": 30.0,
        "is_radian": False,
        "wait": True,
    }]
    assert result["station"] == "ot2"


def test_station_trajectory_paths_and_teach_paths(tmp_path):
    driver = object.__new__(XArmCobot)
    driver.traj_dir = tmp_path
    driver.station_registry = StationRegistry.from_definitions({"ot2": station_definition()})

    assert driver._station_trajectory_filename("ot2", "pickup_vial.json") == "ot2/pickup_vial.json"
    assert driver._trajectory_filename("pickup_vial.json", station="ot2") == "ot2/pickup_vial.json"
    assert driver._trajectory_filename("freeform.json") == "freeform.json"
    with pytest.raises(ValueError, match="within its station directory"):
        driver._station_trajectory_filename("ot2", "../other_station/unsafe.json")
    with pytest.raises(KeyError, match="Unknown station"):
        driver._trajectory_filename("pickup_vial.json", station="missing")


def test_station_playback_prepares_before_playing():
    driver = object.__new__(XArmCobot)
    calls = []
    driver.prepare_station = lambda *args, **kwargs: calls.append("prepare")
    driver._station_trajectory_filename = lambda *args: "ot2/test.json"
    driver.play = lambda *args, **kwargs: calls.append("play")

    driver.play_station_trajectory("ot2", "test.json")

    assert calls == ["prepare", "play"]


class FakeGripperArm:
    def __init__(self):
        self.calls = []

    def set_gripper_position(self, position, **kwargs):
        self.calls.append(("set_gripper_position", position, kwargs))
        return 0

    def open_bio_gripper(self, **kwargs):
        self.calls.append(("open_bio_gripper", kwargs))
        return 0

    def close_bio_gripper(self, **kwargs):
        self.calls.append(("close_bio_gripper", kwargs))
        return 0


def gripper_driver(end_effector):
    driver = object.__new__(XArmCobot)
    driver.config = {
        "end_effector": end_effector,
        "gripper_open_position": 300,
        "gripper_closed_position": 110,
        "gripper_speed": 2000,
        "bio_gripper_speed": 800,
    }
    driver.arm = FakeGripperArm()
    driver._describe_api_code = lambda code: "failure"
    return driver


def test_xarm_finger_gripper_open_and_close_use_sdk_position_api():
    driver = gripper_driver("xarm_gripper")

    driver.open_gripper()
    driver.close_gripper()

    assert driver.arm.calls == [
        ("set_gripper_position", 300, {
            "speed": 2000, "wait": True, "auto_enable": True, "timeout": 5,
        }),
        ("set_gripper_position", 110, {
            "speed": 2000, "wait": True, "auto_enable": True, "timeout": 5,
        }),
    ]


def test_bio_gripper_open_and_close_use_sdk_bio_api():
    driver = gripper_driver("bio_gripper")

    driver.open_gripper()
    driver.close_gripper()

    assert driver.arm.calls == [
        ("open_bio_gripper", {"speed": 800, "wait": True, "timeout": 5}),
        ("close_bio_gripper", {"speed": 800, "wait": True, "timeout": 5}),
    ]


def test_gripper_commands_require_a_configured_end_effector():
    driver = gripper_driver("none")

    with pytest.raises(RuntimeError, match="No gripper is configured"):
        driver.open_gripper()


class FakeCartesianArm:
    def __init__(self, pose, get_code=0, set_code=0):
        self.pose = pose
        self.get_code = get_code
        self.set_code = set_code
        self.commands = []

    def get_position(self, is_radian):
        assert is_radian is False
        return self.get_code, self.pose

    def set_position(self, *pose, **kwargs):
        self.commands.append((pose, kwargs))
        return self.set_code


def test_relative_xyz_move_reads_pose_and_preserves_orientation():
    driver = object.__new__(XArmCobot)
    driver.config = {"cartesian_move_speed": 100.0, "cartesian_move_accel": 2000.0}
    driver.arm = FakeCartesianArm([100, 200, 300, 180, 0, 90])
    driver._describe_api_code = lambda code: "failure"
    driver.log_info = lambda message: None

    result = driver.move_relative_xyz(dx=5, dy=-10, dz=25)

    assert result == {
        "offset": [5.0, -10.0, 25.0],
        "target_pose": [105, 190, 325, 180, 0, 90],
    }
    assert driver.arm.commands == [
        ((105, 190, 325, 180, 0, 90), {
            "speed": 100.0, "mvacc": 2000.0, "radius": -1.0, "wait": True,
        })
    ]


def test_relative_xyz_move_rejects_failed_pose_query():
    driver = object.__new__(XArmCobot)
    driver.config = {"cartesian_move_speed": 100.0, "cartesian_move_accel": 2000.0}
    driver.arm = FakeCartesianArm(None, get_code=-2)
    driver._describe_api_code = lambda code: "not ready"

    with pytest.raises(RuntimeError, match="read current Cartesian pose"):
        driver.move_relative_xyz(dx=1)


def waypoint_driver():
    driver = object.__new__(XArmCobot)
    driver.config = {"cartesian_move_speed": 100.0, "cartesian_move_accel": 2000.0}
    driver.arm = FakeCartesianArm([0, 0, 0, 180, 0, 0])
    driver.log_info = lambda message: None
    driver._describe_api_code = lambda code: "failure"
    return driver


def test_cartesian_waypoints_sort_by_numeric_prefix_and_can_reverse():
    waypoints = {
        "entry": [0, 0, 0, 180, 0, 0],
        "10_to_vial": [10, 0, 0, 180, 0, 0],
        "1_entry": [1, 0, 0, 180, 0, 0],
        "2_above_vial": [2, 0, 0, 180, 0, 0],
        "exit": [99, 0, 0, 180, 0, 0],
    }
    driver = waypoint_driver()

    result = driver.play_cartesian_waypoints(waypoints, speed=25)

    assert result == {
        "reverse": False,
        "waypoints": ["entry", "1_entry", "2_above_vial", "10_to_vial"],
    }
    assert [command[0][0] for command in driver.arm.commands] == [0.0, 1.0, 2.0, 10.0]

    reverse_driver = waypoint_driver()
    reverse_driver.play_cartesian_waypoints(waypoints, reverse=True)
    assert [command[0][0] for command in reverse_driver.arm.commands] == [10.0, 2.0, 1.0, 0.0, 99.0]


def test_xyz_only_cartesian_waypoint_preserves_current_orientation():
    driver = waypoint_driver()
    driver.arm.pose = [0, 0, 0, 170, 10, -20]

    driver.play_cartesian_waypoints({
        "entry": [0, 0, 0], "1_move": [10, 20, 30], "exit": [50, 60, 70],
    })

    assert driver.arm.commands[0][0] == (0.0, 0.0, 0.0, 170, 10, -20)
    assert driver.arm.commands[1][0] == (10.0, 20.0, 30.0, 170, 10, -20)


@pytest.mark.parametrize("waypoints", [
    {"entry": [0, 0, 0, 0, 0, 0]},
    {"entry": [0, 0, 0], "1_": [0, 0, 0], "exit": [0, 0, 0]},
    {
        "entry": [0, 0, 0], "01_entry": [0, 0, 0],
        "1_other": [0, 0, 0], "exit": [0, 0, 0],
    },
])
def test_cartesian_waypoints_require_unique_numbered_keys(waypoints):
    with pytest.raises(ValueError):
        XArmCobot._ordered_cartesian_waypoints(waypoints)


def test_cartesian_waypoints_require_valid_entry_and_exit_poses():
    driver = waypoint_driver()
    with pytest.raises(ValueError, match="entry"):
        driver.play_cartesian_waypoints({"entry": None, "1_move": [1, 2, 3], "exit": [1, 2, 3]})
    with pytest.raises(ValueError, match="exit"):
        driver.play_cartesian_waypoints({"entry": [1, 2, 3], "1_move": [1, 2, 3], "exit": None})
