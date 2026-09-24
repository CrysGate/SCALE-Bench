"""Configuration models for the bubble-tea-cup distractor task."""

from __future__ import annotations

from pydantic import Field, model_validator

from scale_bench.config.base import FiniteFloat, Name, Position2, PositiveFloat
from scale_bench.tasks.common.rigid_object import (
    RigidObjectAssetConfig,
    RigidObjectTaskConfig,
    TargetPlacementConfig,
)


class BubbleTeaCupAssetConfig(RigidObjectAssetConfig):
    """One named bubble tea cup asset in the task scene."""

    name: Name


class BubbleTeaCupTargetSlotConfig(TargetPlacementConfig):
    """Fixed tabletop destination and success tolerances for the target cup."""

    position_xy_m: Position2


class BubbleTeaCupPickAndPlaceConfig(RigidObjectTaskConfig):
    """One large target cup with two small and two medium distractors."""

    cups: tuple[BubbleTeaCupAssetConfig, ...] = Field(min_length=1)
    target_slot: BubbleTeaCupTargetSlotConfig
    target_source_y_max_m: FiniteFloat = 0.04
    release_retreat_height_m: PositiveFloat = 0.12

    @model_validator(mode="after")
    def _validate_asset_names(self) -> "BubbleTeaCupPickAndPlaceConfig":
        names = tuple(cup.name for cup in self.cups)
        if len(names) != len(set(names)):
            raise ValueError("bubble tea cup asset names must be unique")
        return self


__all__ = [
    "BubbleTeaCupAssetConfig",
    "BubbleTeaCupTargetSlotConfig",
    "BubbleTeaCupPickAndPlaceConfig",
]
