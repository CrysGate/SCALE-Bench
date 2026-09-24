"""Pick and place the largest object in the scene."""

from .config import (
    PickObjectConfig,
    LargestPickAndPlaceConfig,
    TargetSlotConfig,
)
from .task import LargestPickAndPlace

__all__ = [
    "LargestPickAndPlace",
    "PickObjectConfig",
    "LargestPickAndPlaceConfig",
    "TargetSlotConfig",
]
