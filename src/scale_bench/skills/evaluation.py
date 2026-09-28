"""Observational skill outcomes; a failed check never controls execution."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SkillEvaluation:
    metrics: Mapping[str, float]
    thresholds: Mapping[str, float]
    failed_checks: tuple[str, ...]

    @property
    def success(self) -> bool:
        return not self.failed_checks


__all__ = ["SkillEvaluation"]
