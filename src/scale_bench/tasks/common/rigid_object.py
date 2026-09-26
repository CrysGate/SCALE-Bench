"""Reusable rigid-object collections, independent of task rules."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from scale_bench.config.base import (
    AssetReference,
    FrozenModel,
    Name,
    NonNegativeFloat,
    PositiveFloat,
    UnitIntervalFloat,
    require_unique,
)


class RigidObjectAssetConfig(FrozenModel):
    """One scene instance; multiple instances may reference the same asset."""

    name: Name
    usd_path: AssetReference
    metadata_path: AssetReference


class RigidObjectPhysicsConfig(FrozenModel):
    restitution: UnitIntervalFloat
    linear_damping: NonNegativeFloat = 0.1
    angular_damping: NonNegativeFloat = 0.1
    sleep_threshold: NonNegativeFloat = 0.005
    stabilization_threshold: NonNegativeFloat = 0.001


class ObjectSetConfig(FrozenModel):
    """Asset instances and nouns shared by selection and manipulation tasks."""

    name: Name
    singular: Name
    plural: Name
    physics: RigidObjectPhysicsConfig
    objects: tuple[RigidObjectAssetConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_names(self) -> Self:
        require_unique(tuple(asset.name for asset in self.objects), "object names")
        return self


class RigidObjectMetadata(BaseModel):
    """Asset-aligned dimensions in metres and physical material properties."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    size: tuple[PositiveFloat, PositiveFloat, PositiveFloat]
    mass: PositiveFloat
    friction: NonNegativeFloat


def load_rigid_object_metadata(asset: RigidObjectAssetConfig) -> RigidObjectMetadata:
    path = Path(asset.metadata_path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        physics = document.get("physics") if isinstance(document, dict) else None
        return RigidObjectMetadata.model_validate(physics)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError(f"Could not load asset metadata {path}:\n{error}") from error


class RigidObjects:
    """Resolved asset data used by layout, goals, spawning, and grasp lookup."""

    def __init__(self, config: ObjectSetConfig) -> None:
        self.config = config
        self._assets = {asset.name: asset for asset in config.objects}
        self._metadata = {
            name: load_rigid_object_metadata(asset)
            for name, asset in self._assets.items()
        }

    @property
    def assets(self) -> Mapping[str, RigidObjectAssetConfig]:
        return MappingProxyType(self._assets)

    @property
    def metadata(self) -> Mapping[str, RigidObjectMetadata]:
        return MappingProxyType(self._metadata)

    @property
    def sizes_m(self) -> dict[str, tuple[float, float, float]]:
        return {name: metadata.size for name, metadata in self.metadata.items()}
