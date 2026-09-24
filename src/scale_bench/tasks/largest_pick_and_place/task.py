"""Task identity and evaluation for picking and placing the largest object."""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

from scale_bench.skills.models import PickAndPlace, Pose
from scale_bench.tasks.common.fixed_target import (
    FixedTargetRigidObjectTask,
    PlacementResult,
)
from scale_bench.tasks.common.layout import TaskLayout
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

    def evaluate(self, observation: EvaluatorObservation) -> PlacementResult:
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

    def expert(
        self,
        *,
        source_layout: TaskLayout,
        target_layout: TaskLayout,
    ) -> Iterator[PickAndPlace]:
        """Generate a pick-and-place request for the target object only."""

        self.validate_asset_layout(source_layout)
        if target_layout.task_id != self.task_id:
            raise ValueError(
                f"layout task_id {target_layout.task_id!r} does not match "
                f"{self.task_id!r}"
            )
        try:
            target_placement = target_layout.assets[self.target_name]
        except KeyError as error:
            raise ValueError(
                f"target layout does not contain {self.target_name!r}"
            ) from error
        yield PickAndPlace(
            object_name=self.target_name,
            # The fixed target slot and upright placement branch are tuned for
            # the right Piper.  Selecting the nearer arm can complete the
            # grasp but fail the subsequent lift or placement.
            arm="right",
            target_object_pose_env=Pose(
                position_m=target_placement.position_m,
                orientation_xyzw=source_layout.assets[
                    self.target_name
                ].orientation_xyzw,
            ),
            # Let the opened fingers settle before retreat to limit lateral
            # drift from release impulses.
            release_settle_steps=10,
        )


__all__ = ["LargestPickAndPlace"]
