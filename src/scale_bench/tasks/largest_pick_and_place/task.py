"""Task identity and evaluation for picking and placing the largest object."""

from __future__ import annotations

from typing import ClassVar

from scale_bench.tasks.common.fixed_target import (
    FixedTargetRigidObjectTask,
    PlacementResult,
)
from scale_bench.tasks.common.task import EvaluatorObservation

from .config import LargestPickAndPlaceConfig


class LargestPickAndPlace(FixedTargetRigidObjectTask):
    """Move the largest object to a fixed slot."""

    TASK_ID: ClassVar[str] = "largest_pick_and_place"

    def __init__(self, config: LargestPickAndPlaceConfig) -> None:
        assets = {asset.name: asset for asset in config.objects}
        super().__init__(
            config,
            assets,
            target_positions_env_xy_m=(config.target_slot.position_xy_m,),
            target_placement_config=config.target_slot,
        )

    @property
    def target_name(self) -> str:
        """Select the largest object by height, as defined by asset metadata."""

        return max(self.assets, key=lambda name: self.metadata[name].size[2])

    @property
    def target_object_order(self) -> tuple[str, ...]:
        """Return the large target object, excluding distractors."""

        return (self.target_name,)

    def evaluate(
        self,
        observation: EvaluatorObservation,
    ) -> PlacementResult:
        """Evaluate placement of the largest object."""

        status = self._placement_statuses(observation)[0]
        return PlacementResult(
            success=status.placed,
            progress=float(status.placed),
            metrics={
                "position_error_m": status.position_error_m,
                "height_error_m": status.height_error_m,
                "upright_error_rad": status.upright_error_rad,
            },
            failure_reason=(
                None
                if status.placed
                else f"{self.target_name} is outside the fixed target slot"
            ),
            statuses=(status,),
        )


__all__ = ["LargestPickAndPlace"]
