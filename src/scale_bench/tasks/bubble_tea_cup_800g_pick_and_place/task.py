"""Task identity and evaluation for the 800g bubble tea cup task."""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

from scale_bench.skills.models import PickAndPlace, Pose
from scale_bench.tasks.common.fixed_target import (
    FixedTargetRigidObjectTask,
    PlacementResult,
)
from scale_bench.tasks.common.layout import TaskLayout
from scale_bench.tasks.common.placement import PlacementContext
from scale_bench.tasks.common.task import EvaluatorObservation

from .config import BubbleTeaCupPickAndPlaceConfig


class BubbleTeaCup800gPickAndPlace(FixedTargetRigidObjectTask):
    """Move the 800g target cup while leaving four cups as distractors."""

    TASK_ID: ClassVar[str] = "bubble_tea_cup_800g_pick_and_place"

    def __init__(self, config: BubbleTeaCupPickAndPlaceConfig) -> None:
        assets = {cup.name: cup for cup in config.cups}
        super().__init__(
            config,
            assets,
            target_positions_env_xy_m=(config.target_slot.position_xy_m,),
            target_placement_config=config.target_slot,
        )

    @property
    def target_name(self) -> str:
        """Select the largest cup by height, as defined by asset metadata."""

        return max(self.assets, key=lambda name: self.metadata[name].size[2])

    @property
    def target_object_order(self) -> tuple[str, ...]:
        """Return the large target cup, excluding distractors."""

        return (self.target_name,)

    def generate_layout(
        self,
        context: PlacementContext,
        seed: int,
    ) -> TaskLayout:
        """Sample a layout with the manipulated cup inside the front reach zone.

        The scene placement area is shared by several tabletop tasks and is
        intentionally wide.  A Piper mounted at the back edge cannot reliably
        reach the rear-most samples, so retry deterministic layout seeds until
        the target cup is in the front zone.  The requested seed remains the
        public layout identity even when a retry is used internally.
        """

        max_target_y_m = self.config.target_source_y_max_m
        last_sampling_error: RuntimeError | None = None
        for retry in range(32):
            try:
                layout = super().generate_layout(context, seed + retry)
            except RuntimeError as error:
                # Five cups can exhaust the sampler in the narrower shared
                # scene. Retry the whole layout, not just the reach-zone test.
                last_sampling_error = error
                continue
            if layout.assets[self.target_name].position_m[1] <= max_target_y_m:
                return layout.model_copy(update={"seed": seed})
        raise RuntimeError(
            "could not sample a reachable target-cup layout after 32 retries; "
            f"requested seed={seed}, target_source_y_max_m={max_target_y_m}"
        ) from last_sampling_error

    def evaluate(self, observation: EvaluatorObservation) -> PlacementResult:
        """Evaluate only the 800g target cup; distractors are ignored."""

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
        """Generate a pick-and-place request for the target cup only."""

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
            # Let the opened fingers settle clear of the cup before the
            # vertical retreat starts; this prevents release impulses from
            # becoming lateral drift on the tabletop.
            release_settle_steps=10,
            retreat_axis_env=(0.0, 0.0, 1.0),
            retreat_distance_m=self.config.release_retreat_height_m,
        )


__all__ = ["BubbleTeaCup800gPickAndPlace"]
