"""Render a task's delivery mat and center mark in all camera observations."""

import isaaclab.sim as sim_utils
from isaaclab.assets import AssetBaseCfg

from scale_bench.config.models.scene import SceneConfig
from scale_bench.tasks.largest_pick_and_place.task import LargestPickAndPlaceTask, TargetMatConfig


def build_target_mat_assets(
    task: LargestPickAndPlaceTask,
    scene_config: SceneConfig,
) -> dict[str, AssetBaseCfg]:
    """Use non-colliding markings so expert and evaluator share tabletop height."""

    target_position_env_xy_m, = task.config.target_positions_env_xy_m
    target_mat_size_xy_m: tuple[float, float] = task.target_mat_size_xy_m
    for axis in range(2):
        table_lower_env_m: float = (
            scene_config.table.position_m[axis] - scene_config.table.size_m[axis] / 2.0
        )
        table_upper_env_m: float = (
            scene_config.table.position_m[axis] + scene_config.table.size_m[axis] / 2.0
        )
        if not (
            table_lower_env_m
            <= target_position_env_xy_m[axis] - target_mat_size_xy_m[axis] / 2.0
            < target_position_env_xy_m[axis] + target_mat_size_xy_m[axis] / 2.0
            <= table_upper_env_m
        ):
            raise ValueError("target mat must fit on the tabletop")

    mat: TargetMatConfig = task.config.target_mat
    center_size_m: float = 2.0 * task.config.position_tolerance_m
    center_width_m: float = center_size_m / 6.0
    parts: tuple[tuple[str, tuple[float, float], tuple[float, float, float], int], ...] = (
        ("target_mat", target_mat_size_xy_m, mat.color_rgb, 0),
        ("target_mat_center_x", (center_size_m, center_width_m), mat.center_color_rgb, 1),
        ("target_mat_center_y", (center_width_m, center_size_m), mat.center_color_rgb, 1),
    )
    return {
        name: AssetBaseCfg(
            prim_path=f"{{ENV_REGEX_NS}}/Task/TargetMat/{name}",
            init_state=AssetBaseCfg.InitialStateCfg(
                pos=(
                    *target_position_env_xy_m,
                    scene_config.table_top_z_m + mat.surface_offset_m * (layer + 0.5),
                ),
            ),
            spawn=sim_utils.CuboidCfg(
                size=(*size_xy_m, mat.surface_offset_m),
                collision_props=sim_utils.PhysxCollisionPropertiesCfg(collision_enabled=False),
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=color_rgb, roughness=1.0),
            ),
        )
        for name, size_xy_m, color_rgb, layer in parts
    }
