"""Robot layout, joints, actuators, gripper, TCP, and camera configuration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated, Self, TypeAlias

from pydantic import Field, StrictBool, field_validator, model_validator

from scale_bench.config.base import (
    AssetReference,
    CameraConvention,
    ConfigReference,
    FiniteFloat,
    FrozenModel,
    Name,
    NonNegativeFloat,
    OptionalAssetReference,
    PositiveFloat,
    Position2,
    Position3,
    Quaternion,
    require_unique,
    require_unit_quaternion,
)


RelativePrimPath = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*$")]
PrimName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
JointNames = Annotated[tuple[Name, ...], Field(min_length=1)]
ActuatorValue: TypeAlias = NonNegativeFloat | dict[str, NonNegativeFloat] | None


class RobotMountConfig(FrozenModel):
    """Base XY position and orientation in env; Z follows the tabletop."""

    position_xy_m: Position2
    orientation_xyzw: Quaternion

    @model_validator(mode="after")
    def _validate_orientation(self) -> Self:
        require_unit_quaternion(self.orientation_xyzw, "orientation_xyzw")
        return self


class RobotMountsConfig(FrozenModel):
    left: RobotMountConfig
    right: RobotMountConfig


class TaskObjectPlacementArea(FrozenModel):
    """Tabletop sampling bounds in env for this robot's dual-arm layout."""

    x_range_m: tuple[FiniteFloat, FiniteFloat]
    y_range_m: tuple[FiniteFloat, FiniteFloat]

    @field_validator("x_range_m", "y_range_m")
    @classmethod
    def _validate_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        if value[0] >= value[1]:
            raise ValueError("lower bound must be less than upper bound")
        return value


class TcpConfig(FrozenModel):
    parent_frame: Name
    position_m: Position3 = (0.0, 0.0, 0.0)
    orientation_xyzw: Quaternion = (0.0, 0.0, 0.0, 1.0)

    @model_validator(mode="after")
    def _validate_quaternion(self) -> Self:
        require_unit_quaternion(self.orientation_xyzw, "orientation_xyzw")
        return self


class MountedCameraConfig(FrozenModel):
    profile_path: ConfigReference
    parent_prim_path: RelativePrimPath
    sensor_prim_name: PrimName
    position_m: Position3 = (0.0, 0.0, 0.0)
    orientation_xyzw: Quaternion = (0.0, 0.0, 0.0, 1.0)
    convention: CameraConvention = "opengl"

    @model_validator(mode="after")
    def _validate_quaternion(self) -> Self:
        require_unit_quaternion(self.orientation_xyzw, "orientation_xyzw")
        return self


class KinematicsConfig(FrozenModel):
    base_body: Name
    arm_joint_names: JointNames
    ee_body: Name
    tcp: TcpConfig

    @model_validator(mode="after")
    def _validate_joint_names(self) -> Self:
        require_unique(self.arm_joint_names, "arm_joint_names")
        return self


class ImplicitActuatorConfig(FrozenModel):
    joint_names: JointNames
    stiffness: ActuatorValue = None
    damping: ActuatorValue = None
    effort_limit_sim: ActuatorValue = None
    velocity_limit_sim: ActuatorValue = None

    @model_validator(mode="after")
    def _validate_joint_names(self) -> Self:
        require_unique(self.joint_names, "actuator joint_names")
        return self


class RevoluteGripperApertureConfig(FrozenModel):
    """Symmetric finger linkage: offset + sum(cosine*cos(q) + sine*sin(q)).

    Robotiq's two outer-knuckle angles are in radians; the coefficients are
    the URDF linkage lengths and the inner pad offset, in metres.
    """

    joint_names: tuple[Name, Name]
    offset_m: FiniteFloat
    cosine_m: FiniteFloat
    sine_m: FiniteFloat


class ParallelJawGripperConfig(FrozenModel):
    joint_names: JointNames
    command_joint_names: JointNames
    finger_body_names: tuple[Name, Name]
    min_aperture_m: NonNegativeFloat
    max_aperture_m: PositiveFloat
    # Prismatic fingers use linear multipliers. Revolute linkages instead
    # supply revolute_aperture; None means the existing prismatic model.
    aperture_joint_multipliers: dict[str, FiniteFloat] = Field(default_factory=dict)
    revolute_aperture: RevoluteGripperApertureConfig | None = None
    minimum_grasp_aperture_m: PositiveFloat
    closed_positions: dict[str, FiniteFloat]
    open_positions: dict[str, FiniteFloat]

    @model_validator(mode="after")
    def _validate_gripper(self) -> Self:
        require_unique(self.joint_names, "gripper joint_names")
        require_unique(self.command_joint_names, "gripper command_joint_names")
        if self.finger_body_names[0] == self.finger_body_names[1]:
            raise ValueError("finger_body_names must contain two different bodies")
        if self.max_aperture_m <= self.min_aperture_m:
            raise ValueError("max_aperture_m must be greater than min_aperture_m")
        if not (
            self.min_aperture_m
            < self.minimum_grasp_aperture_m
            < self.max_aperture_m
        ):
            raise ValueError(
                "minimum_grasp_aperture_m must be inside the aperture range"
            )

        state_joints = set(self.joint_names)
        command_joints = set(self.command_joint_names)
        if self.revolute_aperture is not None:
            require_unique(self.revolute_aperture.joint_names, "aperture joint_names")
            if not set(self.revolute_aperture.joint_names) <= state_joints:
                raise ValueError("revolute aperture references unknown gripper joints")
            if self.aperture_joint_multipliers:
                raise ValueError("revolute aperture cannot use prismatic multipliers")
        elif set(self.aperture_joint_multipliers) != state_joints:
            raise ValueError(
                "aperture_joint_multipliers must exactly cover gripper joint_names"
            )
        if not command_joints <= state_joints:
            raise ValueError("command_joint_names must be a subset of joint_names")
        for field_name in ("closed_positions", "open_positions"):
            if set(getattr(self, field_name)) != command_joints:
                raise ValueError(
                    f"{field_name} keys must exactly match command_joint_names"
                )
        unchanged = [
            joint_name
            for joint_name in self.command_joint_names
            if self.closed_positions[joint_name] == self.open_positions[joint_name]
        ]
        if unchanged:
            raise ValueError(
                "open and closed positions must differ for command joints: "
                f"{unchanged}"
            )
        return self

    def aperture_m(self, joint_positions: Mapping[str, float]) -> float:
        """Return the finger opening for one full gripper joint state.

        ``joint_positions`` covers the measured command and mimic joints.
        Prismatic joint states are in metres; revolute states are in radians.
        """

        if self.revolute_aperture is not None:
            linkage = self.revolute_aperture
            aperture_m = linkage.offset_m + sum(
                linkage.cosine_m * math.cos(joint_positions[name])
                + linkage.sine_m * math.sin(joint_positions[name])
                for name in linkage.joint_names
            )
            return min(self.max_aperture_m, max(self.min_aperture_m, aperture_m))
        return self.min_aperture_m + sum(
            joint_positions[name] * self.aperture_joint_multipliers[name]
            for name in self.joint_names
        )


class RobotConfig(FrozenModel):
    """Complete simulator-independent robot description."""

    name: Name
    usd_path: AssetReference
    urdf_path: OptionalAssetReference = None
    curobo_config_path: ConfigReference
    robot_mounts: RobotMountsConfig
    task_object_placement_area: TaskObjectPlacementArea
    fixed_base: StrictBool = True
    disable_gravity: StrictBool = False
    self_collisions: StrictBool = False
    initial_joint_positions: dict[str, FiniteFloat]
    kinematics: KinematicsConfig
    actuators: dict[str, ImplicitActuatorConfig]
    gripper: ParallelJawGripperConfig
    camera: MountedCameraConfig | None = None

    @model_validator(mode="after")
    def _validate_joint_contract(self) -> Self:
        arm_joints = set(self.kinematics.arm_joint_names)
        gripper_joints = set(self.gripper.joint_names)
        if overlap := arm_joints & gripper_joints:
            raise ValueError(f"arm and gripper joints overlap: {sorted(overlap)}")

        declared_joints = arm_joints | gripper_joints
        initial_joints = set(self.initial_joint_positions)
        if initial_joints != declared_joints:
            raise ValueError(
                "initial_joint_positions must exactly cover arm and gripper joints; "
                f"missing={sorted(declared_joints - initial_joints)}, "
                f"unexpected={sorted(initial_joints - declared_joints)}"
            )

        actuated_joints: set[str] = set()
        for actuator_name, actuator in self.actuators.items():
            overlap = actuated_joints & set(actuator.joint_names)
            if overlap:
                raise ValueError(
                    f"actuator {actuator_name!r} overlaps another actuator: "
                    f"{sorted(overlap)}"
                )
            actuated_joints.update(actuator.joint_names)

        if unknown := actuated_joints - declared_joints:
            raise ValueError(f"actuators reference unknown joints: {sorted(unknown)}")
        required = arm_joints | set(self.gripper.command_joint_names)
        if missing := required - actuated_joints:
            raise ValueError(f"joints have no actuator: {sorted(missing)}")
        return self
