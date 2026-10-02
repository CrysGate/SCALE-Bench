"""Select and restore batch appearance without importing Isaac Sim."""

import random

from scale_bench.config.models.appearance import (
    AppearanceConfig,
    MaterialPreset,
    SceneAppearance,
    SurfaceAppearance,
)
from scale_bench.config.models.scene import LightingConfig, SceneConfig, SurfaceConfig


def sample_appearance(scene: SceneConfig, pool: AppearanceConfig, seed: int) -> SceneConfig:
    """Sample once before environment creation; episode resets only change layout."""
    if seed < 0:
        raise ValueError("appearance seed must be non-negative")
    rng = random.Random(seed)
    table = rng.choice(pool.table_materials)
    ground = rng.choice(pool.ground_materials)
    light = rng.choice(pool.lighting)
    lighting = LightingConfig.model_validate({
        **light.model_dump(exclude={"name"}),
        "dome_rotation_z_world_rad": light.dome_rotation_z_world_rad
        + rng.uniform(*pool.dome_rotation_z_world_range_rad),
        "exposure": light.exposure + rng.uniform(*pool.exposure_offset_range),
    })
    return scene.model_copy(update={
        "table": _apply_material(scene.table, table),
        "ground": _apply_material(scene.ground, ground),
        "lighting": lighting,
    })


def _apply_material(surface: SurfaceConfig, preset: MaterialPreset) -> SurfaceConfig:
    return surface.model_copy(update={
        "material_path": preset.material_path,
        "uv_scale": tuple(
            size / texture_size
            for size, texture_size in zip(surface.size_m[:2], preset.texture_size_m)
        ),
    })


def capture_appearance(scene: SceneConfig) -> SceneAppearance:
    return SceneAppearance(
        table=SurfaceAppearance.model_validate(scene.table.model_dump(
            include={"material_path", "uv_scale"}
        )),
        ground=SurfaceAppearance.model_validate(scene.ground.model_dump(
            include={"material_path", "uv_scale"}
        )),
        lighting=scene.lighting,
    )


def restore_appearance(scene: SceneConfig, appearance: SceneAppearance) -> SceneConfig:
    """Restore recorded materials/lights while retaining replay geometry and cameras."""
    return scene.model_copy(update={
        "table": scene.table.model_copy(update=appearance.table.model_dump()),
        "ground": scene.ground.model_copy(update=appearance.ground.model_dump()),
        "lighting": appearance.lighting,
    })
