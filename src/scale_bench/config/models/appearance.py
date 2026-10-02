"""Material and HDRI pools sampled once for an entire collection batch."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from scale_bench.config.base import (
    AssetReference,
    FiniteFloat,
    FrozenModel,
    Name,
    OptionalAssetReference,
    PositiveFloat,
    require_unique,
)
from scale_bench.config.models.scene import LightingConfig


class MaterialPreset(FrozenModel):
    name: Name
    material_path: AssetReference
    texture_size_m: tuple[PositiveFloat, PositiveFloat]


class LightingPreset(LightingConfig):
    name: Name


class AppearanceConfig(FrozenModel):
    table_materials: Annotated[tuple[MaterialPreset, ...], Field(min_length=1)]
    ground_materials: Annotated[tuple[MaterialPreset, ...], Field(min_length=1)]
    lighting: Annotated[tuple[LightingPreset, ...], Field(min_length=1)]
    dome_rotation_z_world_range_rad: tuple[FiniteFloat, FiniteFloat]
    exposure_offset_range: tuple[FiniteFloat, FiniteFloat]

    @model_validator(mode="after")
    def _validate_pools(self) -> Self:
        for field in ("table_materials", "ground_materials", "lighting"):
            require_unique(tuple(preset.name for preset in getattr(self, field)), field)
        for field in ("dome_rotation_z_world_range_rad", "exposure_offset_range"):
            lower, upper = getattr(self, field)
            if lower > upper:
                raise ValueError(f"{field} must be ordered from minimum to maximum")
        return self


class SurfaceAppearance(FrozenModel):
    # Baseline scenes may deliberately use an untextured cuboid.
    material_path: OptionalAssetReference
    uv_scale: tuple[PositiveFloat, PositiveFloat]


class SceneAppearance(FrozenModel):
    """Resolved appearance stored in HDF5, including the default scene's appearance."""

    table: SurfaceAppearance
    ground: SurfaceAppearance
    lighting: LightingConfig
