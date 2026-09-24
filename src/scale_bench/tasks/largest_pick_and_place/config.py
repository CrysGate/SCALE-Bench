"""Configuration models for picking and placing the largest object."""

from __future__ import annotations

from pydantic import Field, model_validator

from scale_bench.config.base import FiniteFloat, Name, Position2, PositiveFloat
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
    target_source_y_max_m: FiniteFloat = 0.04
    release_retreat_height_m: PositiveFloat = 0.12

    @model_validator(mode="after")
    def _validate_asset_names(self) -> "LargestPickAndPlaceConfig":
        names = tuple(object_asset.name for object_asset in self.objects)
        if len(names) != len(set(names)):
            raise ValueError("object asset names must be unique")
        return self


__all__ = [
    "PickObjectConfig",
    "TargetSlotConfig",
    "LargestPickAndPlaceConfig",
]
