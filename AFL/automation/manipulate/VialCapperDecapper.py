from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional

from AFL.automation.APIServer.Client import Client
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.motors import ServoMotor, StepperMotor


class VialCapperDecapper(Driver):
    """
    AFL driver for coordinated vial capping and decapping workflows.

    This driver combines a servo gripper, a stepper-driven cap rotation stage,
    and an xArm client. During threaded capping and decapping, the xArm is
    assumed to move only in the Z direction while the stepper rotates the cap.
    The axial Z travel is computed from the vial thread pitch and applied in
    small segments so the cap follows the thread safely.

    Parameters
    ----------
    servo_motor : ServoMotor, optional
        Pre-configured servo helper used to grip and release the cap.
    stepper_motor : StepperMotor, optional
        Pre-configured stepper helper used to rotate the cap.
    xarm_client : Client, optional
        AFL client connected to a running xArm server. The xArm is expected to
        support queued ``move`` and ``move_axis`` commands.
    overrides : dict, optional
        Driver configuration overrides merged with :attr:`defaults`.
    name : str, default="VialCapperDecapper"
        Driver name used by the AFL server.

    Notes
    -----
    The driver uses the following default configuration keys.

    ``servo`` : dict
        Default servo helper configuration forwarded to :class:`ServoMotor`.
    ``stepper`` : dict
        Default stepper helper configuration forwarded to :class:`StepperMotor`.
    ``grip_map`` : dict
        Mapping from vial type name to servo grip angle in degrees.
    ``vial_spec`` : dict
        Threaded vial geometry and motion settings used for all sequences.
        User-provided values update these defaults in the same way keyword
        arguments update a base dictionary.
    ``vial_spec['vial_diameter_mm']`` : float or None
        Outer vial diameter in millimeters. Stored for documentation and future
        validation.
    ``vial_spec['cap_diameter_mm']`` : float or None
        Outer cap diameter in millimeters. Stored for documentation and future
        validation.
    ``vial_spec['thread_pitch_mm_per_turn']`` : float, default=1.5
        Axial travel in millimeters for one full cap rotation.
    ``vial_spec['thread_turns']`` : float, default=1.5
        Total number of turns used for a full cap or decap sequence when not
        overridden per call.
    ``vial_spec['rotation_segment_turns']`` : float, default=0.25
        Rotation increment per coordinated step. Smaller values produce more
        frequent Z updates.
    ``xarm_grip_location`` : str or None
        Named xArm location where the vial engages the gripper.
    ``xarm_safe_location`` : str or None
        Named xArm location used as the safe approach and retreat waypoint for
        the full sequence.
    ``xarm_move_timeout`` : float, default=300
        Timeout in seconds used while waiting for queued xArm moves.
    ``xarm_approach_from_below`` : bool, default=True
        If ``True``, the xArm presents the vial to the gripper from below.
    ``xarm_remove_by_lowering`` : bool, default=True
        If ``True``, the xArm removes the vial from the gripper by lowering it.
    ``xarm_return_to_safe_after_rotation`` : bool, default=True
        If ``True``, the xArm returns to the safe location after threaded
        rotation completes.
    ``servo_speed`` : float, default=90.0
        Default servo speed in degrees per second.
    ``stepper_speed`` : float, default=1.0
        Default stepper speed in revolutions per second.
    ``pre_grip_delay`` : float, default=0.0
        Delay in seconds inserted before the servo closes on the cap.
    ``post_grip_delay`` : float, default=0.0
        Delay in seconds inserted after the servo closes and before threaded
        motion begins.
    ``auto_open_after_unscrew`` : bool, default=False
        If ``True``, open the servo automatically after decapping.
    ``auto_open_after_screw`` : bool, default=True
        If ``True``, open the servo automatically after capping.
    ``require_cap_presence_for_screw`` : bool, default=True
        If ``True``, require held-cap metadata before running a cap sequence.
    ``log_level`` : int or str, default=logging.INFO
        Logging level applied to the driver logger.

    Attributes
    ----------
    servo : ServoMotor
        Servo helper used for cap gripping.
    stepper : StepperMotor
        Stepper helper used for cap rotation.
    xarm_client : Client or None
        Client used to issue xArm motion commands.
    held_cap : dict or None
        Metadata describing the currently held cap after decapping.
    last_sequence : dict or None
        Summary of the most recent cap or decap sequence.

    Examples
    --------
    Create a driver with default helpers and attach an xArm client later.

    >>> driver = VialCapperDecapper(overrides={
    ...     "vial_spec": {
    ...         "thread_pitch_mm_per_turn": 1.5,
    ...         "thread_turns": 1.25,
    ...         "rotation_segment_turns": 0.25,
    ...     }
    ... })
    Run a decap sequence using the configured vial specification.

    >>> driver.decap(vial_location="capper_nest")
    """

    defaults = {
        "servo": dict(ServoMotor.DEFAULTS),
        "stepper": dict(StepperMotor.DEFAULTS),
        "grip_map": {},
        "vial_spec": {
            "vial_diameter_mm": None,
            "cap_diameter_mm": None,
            "thread_pitch_mm_per_turn": 1.5,
            "thread_turns": 1.5,
            "rotation_segment_turns": 0.25,
        },
        "xarm_grip_location": None,
        "xarm_safe_location": None,
        "xarm_move_timeout": 300,
        "xarm_approach_from_below": True,
        "xarm_remove_by_lowering": True,
        "xarm_return_to_safe_after_rotation": True,
        "servo_speed": 90.0,
        "stepper_speed": 1.0,
        "pre_grip_delay": 0.0,
        "post_grip_delay": 0.0,
        "auto_open_after_unscrew": False,
        "auto_open_after_screw": True,
        "require_cap_presence_for_screw": True,
        "log_level": logging.INFO,
    }

    def __init__(
        self,
        servo_motor: Optional[ServoMotor] = None,
        stepper_motor: Optional[StepperMotor] = None,
        xarm_client: Optional[Client] = None,
        overrides: Optional[Dict[str, Any]] = None,
        name: str = "VialCapperDecapper",
    ) -> None:
        """
        Initialize the vial capper and decapper driver.

        Parameters
        ----------
        servo_motor : ServoMotor, optional
            Pre-configured servo helper used to grip and release caps.
        stepper_motor : StepperMotor, optional
            Pre-configured stepper helper used to rotate caps.
        xarm_client : Client, optional
            AFL client connected to a running xArm server.
        overrides : dict, optional
            Driver configuration overrides merged with :attr:`defaults`.
        name : str, default="VialCapperDecapper"
            Driver name registered with the AFL server.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> driver.connected
        False
        """
        self._app = None
        self._data = None
        Driver.__init__(self, name=name, defaults=self.gather_defaults(), overrides=overrides)

        self.logger.setLevel(self.config["log_level"])
        self.servo = servo_motor or ServoMotor(**self.config["servo"])
        self.stepper = stepper_motor or StepperMotor(**self.config["stepper"])
        self.xarm_client = xarm_client

        self.connected = False
        self.held_cap: Optional[Dict[str, Any]] = None
        self.last_sequence: Optional[Dict[str, Any]] = None

    @property
    def app(self):
        """
        Return the attached AFL application object.

        Returns
        -------
        object
            Application object propagated to helper components.
        """
        return self._app

    @app.setter
    def app(self, app):
        """
        Attach an AFL application object to the driver and helpers.

        Parameters
        ----------
        app : object
            Application object to propagate to the owned motor helpers.
        """
        self._app = app
        for helper in (self.servo, self.stepper):
            if helper is not None and hasattr(helper, "app"):
                helper.app = app

    @property
    def data(self):
        """
        Return the attached AFL data object.

        Returns
        -------
        object
            Data object propagated to helper components.
        """
        return self._data

    @data.setter
    def data(self, data):
        """
        Attach an AFL data object to the driver and helpers.

        Parameters
        ----------
        data : object
            Data object to propagate to the owned motor helpers.
        """
        self._data = data
        for helper in (self.servo, self.stepper):
            if helper is not None and hasattr(helper, "data"):
                helper.data = data

    @Driver.unqueued()
    def attach_xarm_client(self, xarm_client: Client) -> str:
        """
        Attach a running xArm client to the driver.

        Parameters
        ----------
        xarm_client : Client
            AFL client connected to the xArm server used for vial positioning and
            Z-axis thread following.

        Returns
        -------
        str
            Confirmation message indicating that the client was attached.

        Examples
        --------
        >>> driver.attach_xarm_client(client)
        'Attached provided xArm client'
        """
        self.xarm_client = xarm_client
        self.logger.debug("Attached xArm client: %s", xarm_client)
        return "Attached provided xArm client"

    @Driver.unqueued()
    def connect(self) -> str:
        """
        Connect the underlying stepper helper.

        Returns
        -------
        str
            Confirmation string indicating that the driver is connected.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> driver.connect()
        'connected'
        """
        self.logger.debug("Connecting stepper motor for vial capper")
        self.stepper.connect()
        self.connected = True
        self.log_info("VialCapperDecapper connected")
        return "connected"

    @Driver.unqueued()
    def home(self, open_gripper: bool = True) -> Dict[str, Any]:
        """
        Reset the driver to its software home state.

        Parameters
        ----------
        open_gripper : bool, default=True
            If ``True``, open the servo gripper before resetting the tracked
            stepper position.

        Returns
        -------
        dict
            Current driver status after homing.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> isinstance(driver.home(open_gripper=False), dict)
        True
        """
        self.logger.debug("Homing vial capper with open_gripper=%s", open_gripper)
        if open_gripper:
            self.servo.open(speed=self.config["servo_speed"])
        self.stepper.home()
        self.last_sequence = {"action": "home", "open_gripper": open_gripper}
        self.log_info("VialCapperDecapper homed")
        return self.status()

    @Driver.unqueued()
    def set_grip_angle(self, vial_type: str, angle: int) -> Dict[str, int]:
        """
        Store a servo grip angle for a named vial type.

        Parameters
        ----------
        vial_type : str
            Vial type name used as the lookup key in ``grip_map``.
        angle : int
            Servo angle in degrees used to grip that vial type.

        Returns
        -------
        dict
            Updated grip-angle mapping.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> driver.set_grip_angle("sample_vial", 72)["sample_vial"]
        72
        """
        grip_map = dict(self.config["grip_map"])
        grip_map[vial_type] = angle
        self.config["grip_map"] = grip_map
        return grip_map

    @Driver.unqueued()
    def set_vial_spec(self, **spec: Any) -> Dict[str, Any]:
        """
        Update the vial specification used for threaded motion planning.

        Parameters
        ----------
        **spec : Any
            Vial specification fields to store. Supported keys include
            ``vial_diameter_mm`` for the vial outer diameter,
            ``cap_diameter_mm`` for the cap outer diameter,
            ``thread_pitch_mm_per_turn`` for axial travel per full turn,
            ``thread_turns`` for total turns in the sequence, and
            ``rotation_segment_turns`` for the turn increment used in each
            coordinated Z-motion segment.

        Returns
        -------
        dict
            Updated vial specification.

        Notes
        -----
        The threaded capping sequence assumes the xArm only needs to move in the
        Z direction while the stepper rotates the cap. The axial Z increment for
        each segment is computed from ``thread_pitch_mm_per_turn`` and
        ``rotation_segment_turns``.

        Examples
        --------
        >>> driver.set_vial_spec(
        ...     vial_diameter_mm=17.0,
        ...     cap_diameter_mm=18.0,
        ...     thread_turns=1.75,
        ... )
        """
        self.config["vial_spec"] = {**dict(self.config["vial_spec"]), **spec}
        return self.config["vial_spec"]

    @Driver.unqueued()
    def clear_held_cap(self) -> None:
        """
        Clear any stored metadata for a currently held cap.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> driver.clear_held_cap()
        """
        self.held_cap = None

    @Driver.unqueued()
    def status(self) -> Dict[str, Any]:
        """
        Return the current driver, helper, and xArm state.

        Returns
        -------
        dict
            Summary of connection state, held-cap metadata, helper status, and
            configured xArm locations.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> isinstance(driver.status(), dict)
        True
        """
        return {
            "connected": self.connected,
            "held_cap": self.held_cap,
            "last_sequence": self.last_sequence,
            "servo": self.servo.status(),
            "stepper": self.stepper.status(),
            "xarm_client_attached": self.xarm_client is not None,
            "xarm_grip_location": self.config["xarm_grip_location"],
            "xarm_safe_location": self.config["xarm_safe_location"],
            "vial_spec": self.config["vial_spec"],
        }

    @Driver.queued()
    def decap(
        self,
        grip_angle: Optional[int] = None,
        rotations: Optional[float] = None,
        servo_speed: Optional[float] = None,
        stepper_speed: Optional[float] = None,
        vial_location: Optional[str] = None,
        approach_location: Optional[str] = None,
        cap_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run a decapping sequence.

        Parameters
        ----------
        grip_angle : int, optional
            Explicit servo grip angle used for the cap.
        rotations : float, optional
            Override for the total number of thread turns.
        servo_speed : float, optional
            Servo speed in degrees per second.
        stepper_speed : float, optional
            Stepper speed in revolutions per second.
        vial_location : str, optional
            Named xArm grip location for the vial.
        approach_location : str, optional
            Named xArm safe approach and retreat location.
        cap_id : str, optional
            Identifier stored with the held-cap metadata.
        metadata : dict, optional
            Additional metadata stored in the sequence summary.

        Returns
        -------
        dict
            Driver status after the decap sequence completes.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> isinstance(driver.decap(), dict)
        True
        """
        return self.run_sequence(
            action="decap",
            grip_angle=grip_angle,
            rotations=rotations,
            servo_speed=servo_speed,
            stepper_speed=stepper_speed,
            vial_location=vial_location,
            approach_location=approach_location,
            cap_id=cap_id,
            metadata=metadata,
        )

    @Driver.queued()
    def cap(
        self,
        grip_angle: Optional[int] = None,
        rotations: Optional[float] = None,
        servo_speed: Optional[float] = None,
        stepper_speed: Optional[float] = None,
        vial_location: Optional[str] = None,
        approach_location: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run a capping sequence.

        Parameters
        ----------
        grip_angle : int, optional
            Explicit servo grip angle used for the cap.
        rotations : float, optional
            Override for the total number of thread turns.
        servo_speed : float, optional
            Servo speed in degrees per second.
        stepper_speed : float, optional
            Stepper speed in revolutions per second.
        vial_location : str, optional
            Named xArm grip location for the vial.
        approach_location : str, optional
            Named xArm safe approach and retreat location.
        metadata : dict, optional
            Additional metadata stored in the sequence summary.

        Returns
        -------
        dict
            Driver status after the cap sequence completes.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> isinstance(driver.cap(), dict)
        True
        """
        return self.run_sequence(
            action="cap",
            grip_angle=grip_angle,
            rotations=rotations,
            servo_speed=servo_speed,
            stepper_speed=stepper_speed,
            vial_location=vial_location,
            approach_location=approach_location,
            metadata=metadata,
        )

    @Driver.queued()
    def run_sequence(
        self,
        action: str,
        grip_angle: Optional[int] = None,
        rotations: Optional[float] = None,
        servo_speed: Optional[float] = None,
        stepper_speed: Optional[float] = None,
        vial_location: Optional[str] = None,
        approach_location: Optional[str] = None,
        cap_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a coordinated cap or decap sequence.

        Parameters
        ----------
        action : {"cap", "decap"}
            Sequence type to execute.
        grip_angle : int, optional
            Explicit servo angle used to grip the cap.
        rotations : float, optional
            Override for the total number of thread turns to execute. When not
            provided, ``vial_spec['thread_turns']`` is used.
        servo_speed : float, optional
            Servo speed in degrees per second. Defaults to ``servo_speed`` from
            the driver configuration.
        stepper_speed : float, optional
            Stepper speed in revolutions per second. Defaults to
            ``stepper_speed`` from the driver configuration.
        vial_location : str, optional
            Named xArm grip location where the vial is held during the threaded
            sequence. Defaults to ``xarm_grip_location``.
        approach_location : str, optional
            Named safe approach location used before entering the capping area
            and after the threaded motion completes. Defaults to
            ``xarm_safe_location``.
        cap_id : str, optional
            Identifier stored with held-cap metadata after decapping.
        metadata : dict, optional
            Additional metadata stored in the sequence summary.

        Returns
        -------
        dict
            Driver status after the sequence completes.

        Notes
        -----
        During the threaded portion of the sequence, the xArm is assumed to move
        only along the Z axis. Lateral positioning is handled before the threaded
        motion begins, and the same safe location is used for both approach and
        retreat.

        Examples
        --------
        >>> driver.run_sequence(action="decap")
        >>> driver.run_sequence(action="cap")
        """
        if not self.connected:
            self.connect()

        if action not in {"cap", "decap"}:
            raise ValueError(f"Unsupported action: {action}")

        resolved_grip_angle = self._resolve_grip_angle(grip_angle=grip_angle)
        resolved_vial_spec = self._resolve_vial_spec(rotations=rotations)
        resolved_rotations = resolved_vial_spec["thread_turns"]
        resolved_servo_speed = self.config["servo_speed"] if servo_speed is None else servo_speed
        resolved_stepper_speed = self.config["stepper_speed"] if stepper_speed is None else stepper_speed
        resolved_grip_location = self.config["xarm_grip_location"] if vial_location is None else vial_location
        resolved_safe_location = self.config["xarm_safe_location"] if approach_location is None else approach_location

        self.logger.debug(
            "Starting %s sequence with grip_angle=%s rotations=%s servo_speed=%s stepper_speed=%s grip_location=%s safe_location=%s vial_spec=%s",
            action,
            resolved_grip_angle,
            resolved_rotations,
            resolved_servo_speed,
            resolved_stepper_speed,
            resolved_grip_location,
            resolved_safe_location,
            resolved_vial_spec,
        )

        if any(value is not None for value in (resolved_grip_location, resolved_safe_location)):
            self._require_xarm_client()

        stage_result = self._stage_vial_for_capper(
            grip_location=resolved_grip_location,
            safe_location=resolved_safe_location,
        )
        self.logger.debug("Stage result for %s: %s", action, stage_result)

        if self.config["pre_grip_delay"] > 0:
            self.logger.debug("Sleeping pre-grip delay: %s s", self.config["pre_grip_delay"])
            time.sleep(self.config["pre_grip_delay"])

        self.logger.debug("Closing servo to grip angle %s at speed %s", resolved_grip_angle, resolved_servo_speed)
        self.servo.set_angle(resolved_grip_angle, speed=resolved_servo_speed)

        if self.config["post_grip_delay"] > 0:
            self.logger.debug("Sleeping post-grip delay: %s s", self.config["post_grip_delay"])
            time.sleep(self.config["post_grip_delay"])

        motion_result = self._coordinate_threaded_rotation_and_xarm(
            action=action,
            vial_spec=resolved_vial_spec,
            stepper_speed=resolved_stepper_speed,
            grip_location=resolved_grip_location,
            safe_location=resolved_safe_location,
        )
        self.logger.debug("Motion result for %s: %s", action, motion_result)

        if action == "decap":
            self.held_cap = {
                "cap_id": cap_id,
                "grip_angle": resolved_grip_angle,
                "rotations": resolved_rotations,
                "metadata": {} if metadata is None else metadata,
            }
            self.logger.debug("Stored held cap metadata: %s", self.held_cap)
            if self.config["auto_open_after_unscrew"]:
                self.logger.debug("Auto-opening servo after decap at speed %s", resolved_servo_speed)
                self.servo.open(speed=resolved_servo_speed)
        else:
            if self.config["require_cap_presence_for_screw"] and self.held_cap is None:
                raise RuntimeError("No held cap is available for capping")
            if self.config["auto_open_after_screw"]:
                self.logger.debug("Auto-opening servo after cap at speed %s", resolved_servo_speed)
                self.servo.open(speed=resolved_servo_speed)
            self.logger.debug("Clearing held cap metadata after cap")
            self.held_cap = None

        clear_result = self._clear_capper(safe_location=resolved_safe_location)
        self.logger.debug("Clear result for %s: %s", action, clear_result)
        self.last_sequence = {
            "action": action,
            "grip_angle": resolved_grip_angle,
            "rotations": resolved_rotations,
            "vial_spec": resolved_vial_spec,
            "servo_speed": resolved_servo_speed,
            "stepper_speed": resolved_stepper_speed,
            "stage_result": stage_result,
            "motion_result": motion_result,
            "clear_result": clear_result,
            "xarm_grip_location": resolved_grip_location,
            "xarm_safe_location": resolved_safe_location,
            "metadata": {} if metadata is None else metadata,
        }
        self.log_info(f"Completed {action} sequence")
        return self.status()

    def _resolve_grip_angle(self, grip_angle: Optional[int]) -> int:
        """
        Resolve the servo angle used to grip the cap.

        Parameters
        ----------
        grip_angle : int, optional
            Explicit grip angle override.

        Returns
        -------
        int
            Provided grip angle when available, otherwise the servo helper's
            configured closed angle.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> isinstance(driver._resolve_grip_angle(None), int)
        True
        """
        if grip_angle is not None:
            return grip_angle
        return self.servo.close_angle

    def _resolve_vial_spec(self, rotations: Optional[float]) -> Dict[str, Any]:
        """
        Resolve the vial specification used for threaded motion planning.

        Parameters
        ----------
        rotations : float, optional
            Explicit override for the total number of thread turns.

        Returns
        -------
        dict
            Fully resolved vial specification. The result always includes
            ``vial_diameter_mm``, ``cap_diameter_mm``,
            ``thread_pitch_mm_per_turn``, ``thread_turns``, and
            ``rotation_segment_turns``.

        Raises
        ------
        ValueError
            Raised when the resolved thread pitch, total turns, or segment size is
            not positive.
        """
        vial_spec = dict(self.config["vial_spec"])

        if rotations is not None:
            vial_spec["thread_turns"] = rotations

        if vial_spec["thread_pitch_mm_per_turn"] is None or vial_spec["thread_pitch_mm_per_turn"] <= 0:
            raise ValueError("thread_pitch_mm_per_turn must be greater than zero")
        if vial_spec["thread_turns"] is None or vial_spec["thread_turns"] <= 0:
            raise ValueError("thread_turns must be greater than zero")
        if vial_spec["rotation_segment_turns"] is None or vial_spec["rotation_segment_turns"] <= 0:
            raise ValueError("rotation_segment_turns must be greater than zero")

        self.logger.debug("Resolved vial specification: %s", vial_spec)
        return vial_spec

    def _require_xarm_client(self) -> Client:
        """
        Return the attached xArm client or raise an error.

        Returns
        -------
        Client
            Attached AFL client used for xArm motion commands.

        Raises
        ------
        RuntimeError
            Raised when no xArm client has been attached.
        """
        if self.xarm_client is None:
            raise RuntimeError("An xArm client must be attached before using location-based capping sequences")
        return self.xarm_client

    def _move_xarm(self, location: str, above: bool) -> Dict[str, Any]:
        """
        Queue and wait for a named xArm move.

        Parameters
        ----------
        location : str
            Named xArm location to move to.
        above : bool
            Motion mode flag forwarded to the xArm server to indicate whether the
            move should approach above or below the named location.

        Returns
        -------
        dict
            Summary containing the target location, approach mode, and queue
            UUID.

        Raises
        ------
        RuntimeError
            Raised when no xArm client is attached or when the xArm server does
            not return a queue UUID.
        """
        client = self._require_xarm_client()
        self.logger.debug("Queueing xArm move to location=%s above=%s", location, above)
        response = client.enqueue(task_name="move", interactive=True, location=location, above=above)
        uuid = response.get("uuid")
        if uuid is None:
            raise RuntimeError(f"xArm move command did not return a queue uuid for location {location}")
        self.logger.debug("Waiting for xArm move uuid=%s location=%s above=%s", uuid, location, above)
        client.wait(uuid, timeout=self.config["xarm_move_timeout"])
        self.logger.debug("Completed xArm move uuid=%s location=%s above=%s", uuid, location, above)
        return {"location": location, "above": above, "uuid": uuid}

    def _move_xarm_axis(
        self,
        location: Optional[str],
        axis: str,
        delta_mm: float,
        require_location: bool = False,
    ) -> Dict[str, Any]:
        """
        Move the xArm incrementally along a single axis.

        Parameters
        ----------
        location : str, optional
            Named reference location used by the xArm server for the incremental
            move.
        axis : str
            Axis to move. Threaded capping sequences use only ``"z"``.
        delta_mm : float
            Signed incremental travel in millimeters.
        require_location : bool, default=False
            If ``True``, raise an error when ``location`` is not provided.

        Returns
        -------
        dict
            Summary of the queued xArm axis move.

        Raises
        ------
        RuntimeError
            Raised when no xArm client is attached, when a required location is
            missing, or when the xArm server does not return a queue UUID.
        """
        client = self._require_xarm_client()
        if location is None and require_location:
            raise RuntimeError("A grip location is required for threaded xArm axial moves")

        self.logger.debug(
            "Queueing xArm axis move location=%s axis=%s delta_mm=%s require_location=%s",
            location,
            axis,
            delta_mm,
            require_location,
        )
        response = client.enqueue(
            task_name="move_axis",
            interactive=True,
            location=location,
            axis=axis,
            delta_mm=delta_mm,
        )
        uuid = response.get("uuid")
        if uuid is None:
            raise RuntimeError(f"xArm axis move command did not return a queue uuid for axis {axis}")
        self.logger.debug("Waiting for xArm axis move uuid=%s axis=%s delta_mm=%s", uuid, axis, delta_mm)
        client.wait(uuid, timeout=self.config["xarm_move_timeout"])
        self.logger.debug("Completed xArm axis move uuid=%s axis=%s delta_mm=%s", uuid, axis, delta_mm)
        return {
            "location": location,
            "axis": axis,
            "delta_mm": delta_mm,
            "uuid": uuid,
        }

    def _stage_vial_for_capper(
        self,
        grip_location: Optional[str],
        safe_location: Optional[str],
    ) -> Dict[str, Any]:
        """
        Move the xArm from the safe location into the grip location.

        Parameters
        ----------
        grip_location : str, optional
            Named xArm location where the vial engages the gripper.
        safe_location : str, optional
            Named xArm location used as the safe approach waypoint.

        Returns
        -------
        dict
            Summary of the staging locations and queued xArm moves.

        Notes
        -----
        When ``xarm_approach_from_below`` is enabled, the final move into the
        grip location uses ``above=False``.
        """
        self.logger.debug(
            "Staging vial for capper with safe_location=%s grip_location=%s approach_from_below=%s",
            safe_location,
            grip_location,
            self.config["xarm_approach_from_below"],
        )
        moves = []
        if safe_location is not None:
            moves.append(self._move_xarm(safe_location, above=True))
        if grip_location is not None:
            if self.config["xarm_approach_from_below"]:
                moves.append(self._move_xarm(grip_location, above=False))
            else:
                moves.append(self._move_xarm(grip_location, above=True))
                moves.append(self._move_xarm(grip_location, above=False))
        return {
            "grip_location": grip_location,
            "safe_location": safe_location,
            "moves": moves,
        }

    def _coordinate_threaded_rotation_and_xarm(
        self,
        action: str,
        vial_spec: Dict[str, Any],
        stepper_speed: float,
        grip_location: Optional[str],
        safe_location: Optional[str],
    ) -> Dict[str, Any]:
        """
        Coordinate segmented threaded rotation with Z-axis xArm motion.

        Parameters
        ----------
        action : {"cap", "decap"}
            Threaded action to execute.
        vial_spec : dict
            Resolved vial specification containing thread pitch, total turns, and
            segment size.
        stepper_speed : float
            Stepper speed in revolutions per second.
        grip_location : str, optional
            Named xArm location where the vial remains during the threaded
            sequence.
        safe_location : str, optional
            Named safe location used after the threaded sequence completes.

        Returns
        -------
        dict
            Segment-by-segment summary of the coordinated rotation and Z-axis
            motion.

        Notes
        -----
        This method assumes the xArm only needs to move in Z while the vial is
        being capped or decapped. The axial travel for each segment is computed
        as ``rotation_turns * thread_pitch_mm_per_turn``.
        """
        if action == "cap" and self.config["require_cap_presence_for_screw"] and self.held_cap is None:
            raise RuntimeError("No held cap is available for capping")

        total_turns = float(vial_spec["thread_turns"])
        segment_turns = float(vial_spec["rotation_segment_turns"])
        thread_pitch = float(vial_spec["thread_pitch_mm_per_turn"])
        segment_count = max(1, int(math.ceil(total_turns / segment_turns)))
        remaining_turns = total_turns
        segments = []

        self.logger.debug(
            "Coordinating threaded motion action=%s total_turns=%s segment_turns=%s thread_pitch=%s stepper_speed=%s grip_location=%s safe_location=%s",
            action,
            total_turns,
            segment_turns,
            thread_pitch,
            stepper_speed,
            grip_location,
            safe_location,
        )

        for segment_index in range(segment_count):
            current_turns = min(segment_turns, remaining_turns)
            axial_travel_mm = current_turns * thread_pitch
            self.logger.debug(
                "Thread segment %s/%s action=%s current_turns=%s axial_travel_mm=%s remaining_before=%s",
                segment_index + 1,
                segment_count,
                action,
                current_turns,
                axial_travel_mm,
                remaining_turns,
            )
            if action == "decap":
                self.logger.debug("Stepper rotate_ccw turns=%s speed=%s", current_turns, stepper_speed)
                self.stepper.rotate_ccw(current_turns, speed=stepper_speed)
                xarm_move = self._move_xarm_axis(
                    location=grip_location,
                    axis="z",
                    delta_mm=axial_travel_mm,
                    require_location=segment_index == 0,
                )
            else:
                xarm_move = self._move_xarm_axis(
                    location=grip_location,
                    axis="z",
                    delta_mm=-axial_travel_mm,
                    require_location=segment_index == 0,
                )
                self.logger.debug("Stepper rotate_cw turns=%s speed=%s", current_turns, stepper_speed)
                self.stepper.rotate_cw(current_turns, speed=stepper_speed)

            segments.append(
                {
                    "segment_index": segment_index,
                    "rotation_turns": current_turns,
                    "axial_travel_mm": axial_travel_mm,
                    "xarm_move": xarm_move,
                }
            )
            remaining_turns -= current_turns
            self.logger.debug("Completed thread segment %s remaining_turns=%s", segment_index + 1, remaining_turns)

        retreat_moves = []
        if action == "decap" and grip_location is not None:
            if self.config["xarm_remove_by_lowering"]:
                self.logger.debug("Retreating after decap by lowering at grip_location=%s", grip_location)
                retreat_moves.append(self._move_xarm(grip_location, above=False))
            else:
                self.logger.debug("Retreating after decap upward at grip_location=%s", grip_location)
                retreat_moves.append(self._move_xarm(grip_location, above=True))
        if safe_location is not None and self.config["xarm_return_to_safe_after_rotation"]:
            self.logger.debug("Returning xArm to safe location after rotation: %s", safe_location)
            retreat_moves.append(self._move_xarm(safe_location, above=True))

        return {
            "action": action,
            "vial_spec": vial_spec,
            "segment_count": segment_count,
            "segments": segments,
            "retreat_moves": retreat_moves,
        }

    def _clear_capper(self, safe_location: Optional[str]) -> Dict[str, Any]:
        """
        Move the xArm away from the capping station after a sequence.

        Parameters
        ----------
        safe_location : str, optional
            Named safe retreat location used after the sequence completes.

        Returns
        -------
        dict
            Summary of the retreat moves issued to the xArm.

        Examples
        --------
        >>> driver = VialCapperDecapper()
        >>> isinstance(driver._clear_capper(None), dict)
        True
        """
        moves = []
        if safe_location is not None:
            moves.append(self._move_xarm(safe_location, above=True))
        return {
            "safe_location": safe_location,
            "moves": moves,
        }


_DEFAULT_PORT = 5057
_DEFAULT_CUSTOM_CONFIG = {
    "_classname": "AFL.automation.manipulate.VialCapperDecapper.VialCapperDecapper",
    "_args": [],
    "xarm_client": {
        "_classname": "AFL.automation.APIServer.Client.Client",
        "host": "localhost:5050",
    },
}


if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
