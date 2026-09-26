"""Isaac Lab cuboid spawner with face-varying texture coordinates."""

from __future__ import annotations

from collections.abc import Callable

import isaaclab.sim as sim_utils
from isaaclab.utils.configclass import configclass
from pxr import Gf, Sdf, Usd, UsdGeom

from scale_bench.config.models.scene import PbrMaterialConfig
from scale_bench.isaaclab.spawners.pbr import bind_pbr_material


def spawn_uv_cuboid(
    prim_path: str,
    cfg: UvCuboidCfg,
    translation: tuple[float, float, float] | None = None,
    orientation: tuple[float, float, float, float] | None = None,
    **kwargs,
) -> Usd.Prim:
    """Spawn an Isaac Lab cuboid, then add one UV island to each face."""

    if len(cfg.uv_scale) != 2 or any(scale <= 0.0 for scale in cfg.uv_scale):
        raise ValueError(
            f"UV scale must contain two positive values, got {cfg.uv_scale}."
        )

    root_prim = sim_utils.spawn_cuboid(
        prim_path,
        cfg,
        translation=translation,
        orientation=orientation,
        **kwargs,
    )

    stage = sim_utils.get_current_stage()
    spawned_paths = sim_utils.find_matching_prim_paths(prim_path)
    if not spawned_paths:
        raise RuntimeError(f"No cuboids were spawned for path: '{prim_path}'.")

    for spawned_path in spawned_paths:
        cube_prim = stage.GetPrimAtPath(f"{spawned_path}/geometry/mesh")
        if not cube_prim.IsA(UsdGeom.Cube):
            raise RuntimeError(
                f"Expected a UsdGeom.Cube at '{cube_prim.GetPath()}', "
                f"got '{cube_prim.GetTypeName()}'."
            )
        if cfg.pbr is None:
            _author_cube_uvs(cube_prim, cfg.uv_scale)
        else:
            _author_pbr_mesh(cube_prim, cfg.size, cfg.pbr)

    return root_prim


def _author_cube_uvs(cube_prim: Usd.Prim, uv_scale: tuple[float, float]) -> None:
    """Author the 24 face-varying UV values required by ``UsdGeom.Cube``."""

    uv_u, uv_v = uv_scale
    face_uvs = [
        Gf.Vec2f(0.0, 0.0),
        Gf.Vec2f(uv_u, 0.0),
        Gf.Vec2f(uv_u, uv_v),
        Gf.Vec2f(0.0, uv_v),
    ]
    uv_primvar = UsdGeom.PrimvarsAPI(cube_prim).CreatePrimvar(
        "st",
        Sdf.ValueTypeNames.TexCoord2fArray,
        UsdGeom.Tokens.faceVarying,
    )
    uv_primvar.Set(face_uvs * 6)


def _author_pbr_mesh(
    cube_prim: Usd.Prim, size_m: tuple[float, float, float], spec: PbrMaterialConfig,
) -> None:
    """Keep the cuboid transform/collision and give each face metre-scaled UVs."""
    half_size = UsdGeom.Cube(cube_prim).GetSizeAttr().Get() / 2
    cube_prim.SetTypeName("Mesh")
    mesh = UsdGeom.Mesh(cube_prim)
    mesh.CreatePointsAttr([
        Gf.Vec3f(x, y, z) * half_size
        for x, y, z in ((-1,-1,-1), (1,-1,-1), (1,1,-1), (-1,1,-1),
                        (-1,-1,1), (1,-1,1), (1,1,1), (-1,1,1))
    ])
    mesh.CreateFaceVertexCountsAttr([4] * 6)
    mesh.CreateFaceVertexIndicesAttr([0,3,2,1, 4,5,6,7, 0,1,5,4, 1,2,6,5, 2,3,7,6, 3,0,4,7])
    mesh.CreateSubdivisionSchemeAttr("none")
    x_m, y_m, z_m = size_m
    texture_u_m, texture_v_m = spec.texture_size_m
    uv_values = []
    for width_m, height_m in ((y_m,x_m), (x_m,y_m), (x_m,z_m), (y_m,z_m), (x_m,z_m), (y_m,z_m)):
        u, v = width_m / texture_u_m, height_m / texture_v_m
        uv_values.extend((Gf.Vec2f(0,0), Gf.Vec2f(u,0), Gf.Vec2f(u,v), Gf.Vec2f(0,v)))
    UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
        "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying,
    ).Set(uv_values)
    bind_pbr_material(cube_prim.GetStage(), cube_prim, spec)


@configclass
class UvCuboidCfg(sim_utils.CuboidCfg):
    """Cuboid configuration extended with face-varying ``st`` UVs."""

    func: Callable = spawn_uv_cuboid
    uv_scale: tuple[float, float] = (1.0, 1.0)
    # None keeps the MDL/untextured cuboid path used by the original scene.
    pbr: PbrMaterialConfig | None = None


__all__ = ["UvCuboidCfg", "spawn_uv_cuboid"]
