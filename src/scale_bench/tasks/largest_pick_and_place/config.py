"""Configuration models for picking and placing the largest object."""

from __future__ import annotations

from pydantic import Field, model_validator

from scale_bench.config.base import Name, Position2
from scale_bench.tasks.common.rigid_object import (
    RigidObjectAssetConfig,
    RigidObjectTaskConfig,
    TargetPlacementConfig,
)


class PickObjectConfig(RigidObjectAssetConfig):
    """One named rigid object asset in the task scene."""

    name: Name


class TargetSlotConfig(TargetPlacementConfig):
    """Fixed tabletop destination and success tolerances for the largest object."""

    position_xy_m: Position2


class LargestPickAndPlaceConfig(RigidObjectTaskConfig):
    """Objects and placement settings for the largest-object task."""

    objects: tuple[PickObjectConfig, ...] = Field(min_length=1)
    target_slot: TargetSlotConfig


__all__ = [
    "PickObjectConfig",
    "TargetSlotConfig",
    "LargestPickAndPlaceConfig",
]
