"""Expected manipulation planning and execution failures."""

from __future__ import annotations

from enum import StrEnum

from .models import Arm


class SkillError(RuntimeError):
    """A failure that should terminate only the affected episode."""


class FailureCode(StrEnum):
    IK_FAILED = "IK_FAILED"
    START_STATE_INFEASIBLE = "START_STATE_INFEASIBLE"
    PLANNER_NO_RESULT = "PLANNER_NO_RESULT"
    PLANNER_NO_SUCCESSFUL_TRAJECTORY = "PLANNER_NO_SUCCESSFUL_TRAJECTORY"
    TRACKING_FAILED = "TRACKING_FAILED"
    CONTACT_FAILED = "CONTACT_FAILED"
    GRASP_FAILED = "GRASP_FAILED"
    RELEASE_FAILED = "RELEASE_FAILED"


class SegmentError(SkillError):
    """Machine-readable failure of a single planning or physical transition."""

    def __init__(self, arm: Arm, stage: str, code: FailureCode, reason: str) -> None:
        self.arm = arm
        self.stage = stage
        self.code = code
        self.reason = reason
        super().__init__(f"{arm} arm {stage}: {code}: {reason}")


class PlanningError(SegmentError):
    """A failed motion segment with its arm and operation stage."""

    @property
    def retryable(self) -> bool:
        return self.code in {
            FailureCode.PLANNER_NO_RESULT,
            FailureCode.PLANNER_NO_SUCCESSFUL_TRAJECTORY,
        }


class StartStateError(PlanningError):
    """Explicit collision sources allow skills to resolve intentional contact."""

    def __init__(self, arm: Arm, stage: str, violations: tuple[str, ...]) -> None:
        self.violations = violations
        super().__init__(
            arm, stage, FailureCode.START_STATE_INFEASIBLE,
            "start state is infeasible: " + "; ".join(violations),
        )


__all__ = ["FailureCode", "PlanningError", "SegmentError", "SkillError", "StartStateError"]
