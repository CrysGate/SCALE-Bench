"""Configuration models for the bubble-tea-cup distractor task."""

from __future__ import annotations

from pydantic import model_validator

from scale_bench.config.base import FiniteFloat, Name, Position2
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

    target: BubbleTeaCupAssetConfig
    small_distractors: tuple[
        BubbleTeaCupAssetConfig,
        BubbleTeaCupAssetConfig,
    ]
    medium_distractors: tuple[
        BubbleTeaCupAssetConfig,
        BubbleTeaCupAssetConfig,
    ]
    target_slot: BubbleTeaCupTargetSlotConfig
    target_source_y_max_m: FiniteFloat = 0.04

    @model_validator(mode="after")
    def _validate_asset_names(self) -> "BubbleTeaCupPickAndPlaceConfig":
        assets = (
            self.target,
            *self.small_distractors,
            *self.medium_distractors,
        )
        names = tuple(asset.name for asset in assets)
        if len(names) != len(set(names)):
            raise ValueError("bubble tea cup asset names must be unique")
        return self


__all__ = [
    "BubbleTeaCupAssetConfig",
    "BubbleTeaCupTargetSlotConfig",
    "BubbleTeaCupPickAndPlaceConfig",
]
