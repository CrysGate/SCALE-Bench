"""Pick-and-place task with small and medium cup distractors."""

from .config import (
    BubbleTeaCupAssetConfig,
    BubbleTeaCupPickAndPlaceConfig,
    BubbleTeaCupTargetSlotConfig,
)
from .task import BubbleTeaCup800gPickAndPlace

__all__ = [
    "BubbleTeaCup800gPickAndPlace",
    "BubbleTeaCupAssetConfig",
    "BubbleTeaCupPickAndPlaceConfig",
    "BubbleTeaCupTargetSlotConfig",
]
