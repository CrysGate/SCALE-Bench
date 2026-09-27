"""Build open packing boxes, small convex-decomposed pots and Piper grasps."""

from __future__ import annotations

import argparse
import json
import math
import os
from importlib.metadata import version
from pathlib import Path

import coacd
import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade
import trimesh
from trimesh.ray.ray_triangle import RayMeshIntersector
import yaml

from download_scene_assets import checksum, verify
from prepare_scene_assets import visible_bounds
from scale_bench.config.loader import load_config
from scale_bench.config.models.robot import RobotConfig
from scale_bench.skills.geometry import quaternion_xyzw_from_rpy


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def visual_mesh(stage: Usd.Stage) -> trimesh.Trimesh:
    """Triangulate the authored polygons in the normalized object frame."""
    meshes = []
    transforms = UsdGeom.XformCache()
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh) or UsdGeom.Imageable(prim).ComputeVisibility() == "invisible":
            continue
        mesh = UsdGeom.Mesh(prim)
        transform_object = transforms.GetLocalToWorldTransform(prim)
        vertices = np.array([transform_object.Transform(Gf.Vec3d(*point)) for point in mesh.GetPointsAttr().Get()])
        indices = mesh.GetFaceVertexIndicesAttr().Get()
        triangles, offset = [], 0
        for count in mesh.GetFaceVertexCountsAttr().Get():
            face = indices[offset:offset + count]
            triangles.extend((face[0], face[index], face[index + 1]) for index in range(1, count - 1))
            offset += count
        meshes.append(trimesh.Trimesh(vertices, triangles, process=True))
    return trimesh.util.concatenate(meshes)


def measure_container(mesh: trimesh.Trimesh) -> dict:
    """Conservative upright bore samples; these do not define arbitrary insertions."""
    bottom_z_object_m, top_z_object_m = mesh.bounds[:, 2]
    height_m = top_z_object_m - bottom_z_object_m
    rays = RayMeshIntersector(mesh)
    axis_hits = rays.intersects_location([[0, 0, top_z_object_m + height_m]], [[0, 0, -1]])[0]
    if not len(axis_hits):
        raise ValueError("Container has no bottom on its central axis")
    floor_z_object_m = float(axis_hits[:, 2].max())
    profiles = []
    for fraction in np.linspace(0.1, 0.9, 17):
        z_object_m = bottom_z_object_m + height_m * fraction
        if z_object_m <= floor_z_object_m:
            continue
        inner, outer, thickness = [], [], []
        for angle in np.linspace(0, 2 * math.pi, 64, endpoint=False):
            hits = rays.intersects_location(
                [[0, 0, z_object_m]], [[math.cos(angle), math.sin(angle), 0]],
            )[0]
            distances = np.sort(np.linalg.norm(hits[:, :2], axis=1))
            if len(distances) < 2:
                raise ValueError(f"Open wall at z={z_object_m}: {distances}")
            inner.append(float(distances[0]))
            outer.append(float(distances[-1]))
            thickness.append(float(distances[-1] - distances[0]))
        profiles.append({
            "z_object_m": float(z_object_m),
            "inner_radius_min_m": min(inner), "outer_radius_max_m": max(outer),
            "wall_thickness_min_m": min(thickness), "wall_thickness_max_m": max(thickness),
        })
    return {
        "method": "mesh rays: 64 azimuths, 17 slices at 10–90% height; dimensions are geometric estimates",
        "floor_z_object_m": floor_z_object_m,
        "depth_m": float(top_z_object_m - floor_z_object_m),
        "bottom_thickness_m": float(floor_z_object_m - bottom_z_object_m),
        "opening_diameter_m": 2 * profiles[-1]["inner_radius_min_m"],
        "opening_measurement_z_object_m": profiles[-1]["z_object_m"],
        "bore_diameter_min_m": 2 * min(profile["inner_radius_min_m"] for profile in profiles),
        "wall_thickness_min_m": min(profile["wall_thickness_min_m"] for profile in profiles),
        "profiles": profiles,
    }


def new_stage(output: Path) -> Usd.Stage:
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(output))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, "Z")
    root = UsdGeom.Xform.Define(stage, "/Asset").GetPrim()
    stage.SetDefaultPrim(root)
    UsdPhysics.RigidBodyAPI.Apply(root)
    return stage


def finish_asset(stage: Usd.Stage, spec: dict, container: dict, source: dict, collision: dict, grasp: dict) -> dict:
    directory = Path(stage.GetRootLayer().realPath).parent
    size_object_m = list(visible_bounds(stage).GetSize())
    UsdPhysics.MassAPI.Apply(stage.GetDefaultPrim()).CreateMassAttr(spec["mass_kg"])
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            # Thin container walls need a contact envelope smaller than their cavity.
            # Author the PhysX schema without importing Kit in this CPU-only converter.
            prim.AddAppliedSchema("PhysxCollisionAPI")
            prim.CreateAttribute("physxCollision:contactOffset", Sdf.ValueTypeNames.Float).Set(spec["contact_offset_m"])
            prim.CreateAttribute("physxCollision:restOffset", Sdf.ValueTypeNames.Float).Set(0.0)
    material = UsdShade.Material.Define(stage, "/Asset/PhysicsMaterial")
    physics = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr(spec["friction"])
    physics.CreateDynamicFrictionAttr(spec["friction"])
    physics.CreateRestitutionAttr(0.0)
    UsdShade.MaterialBindingAPI.Apply(stage.GetDefaultPrim()).Bind(material, materialPurpose="physics")
    stage.GetRootLayer().Save()
    # Box grasps face its four flat walls; round pots support more azimuths.
    grasp = {
        **grasp, "yaw_samples": spec["grasp_yaw_samples"],
        "side_height_fraction": spec["grasp_height_fraction"],
    }
    write_grasps(directory, spec["id"], size_object_m, grasp)
    metadata = {
        "id": spec["id"], "role": "manipulation", "origin": "visual_aabb_center",
        "meters_per_unit": 1.0, "up_axis": "Z", "size_object_m": size_object_m,
        "physics": {"size": size_object_m, "mass": spec["mass_kg"], "friction": spec["friction"]},
        "physics_basis": "simulation specification; mass and friction are not measured real-product values",
        "container": container, "collision": collision, "source": source,
        "specification": spec,
        "usd_path": f"Assets/Imported/{spec['id']}/model.usdc",
        "grasp_robots": ["piper"], "validation": "run collection and cavity inspection before use",
        "grasp_specification": grasp,
        "generator_sha256": checksum(Path(__file__), "sha256"),
        "generated_files": [
            {"path": path.name, "sha256": checksum(path, "sha256")}
            for path in sorted(directory.iterdir())
            if path.name in {"model.usdc", "grasps-piper.yaml", "LICENSE.txt", "ATTRIBUTION.txt"}
        ],
    }
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared {spec['id']}: {size_object_m}", flush=True)
    return metadata


def write_grasps(directory: Path, name: str, size_object_m: list[float], spec: dict) -> None:
    robot = load_config(PROJECT_ROOT / spec["robot_config"], RobotConfig, asset_root=PROJECT_ROOT)
    if robot.name != "piper":
        raise ValueError("These analytic candidates require the Piper +X approach TCP")
    width_m = max(size_object_m[:2])
    if width_m >= robot.gripper.max_aperture_m:
        raise ValueError(f"{name} does not fit the Piper gripper")
    candidates = []
    for pitch_object_rad in spec["side_pitch_rad"]:
        for index in range(spec["yaw_samples"]):
            yaw_object_rad = index * 2 * math.pi / spec["yaw_samples"]
            candidates.append({
                "candidate_id": len(candidates), "robot": robot.name,
                "pose_object_tcp_xyz_xyzw": [
                    0, 0, size_object_m[2] * (spec["side_height_fraction"] - 0.5),
                    *quaternion_xyzw_from_rpy(0, pitch_object_rad, yaw_object_rad),
                ],
                "approach_axis_object": [
                    math.cos(yaw_object_rad) * math.cos(pitch_object_rad),
                    math.sin(yaw_object_rad) * math.cos(pitch_object_rad),
                    -math.sin(pitch_object_rad),
                ],
                "closed_joint_positions_m": {
                    joint: width_m / 2 - spec["closure_margin_m"] for joint in robot.gripper.joint_names
                },
            })
    for index in range(spec["yaw_samples"]):
        yaw_object_rad = index * 2 * math.pi / spec["yaw_samples"]
        # Piper approaches along TCP +X; rotating +90 degrees about Y points down.
        tcp_orientation_object_xyzw = quaternion_xyzw_from_rpy(0, math.pi / 2, yaw_object_rad)
        candidates.append({
            "candidate_id": len(candidates), "robot": robot.name,
            "pose_object_tcp_xyz_xyzw": [0, 0, size_object_m[2] / 2 - spec["top_inset_m"], *tcp_orientation_object_xyzw],
            "approach_axis_object": [0, 0, -1],
            "closed_joint_positions_m": {
                joint: width_m / 2 - spec["closure_margin_m"] for joint in robot.gripper.joint_names
            },
        })
    document = {
        "object": name, "position_unit": "m", "pose_layout": ["x", "y", "z", "qx", "qy", "qz", "qw"],
        "tcp": robot.kinematics.tcp.model_dump(),
        "approach_distance_m": spec["approach_distance_m"], "candidates": candidates,
    }
    (directory / f"grasps-{robot.name}.yaml").write_text(yaml.safe_dump(document, sort_keys=False))


def prepare_box(asset_dir: Path, spec: dict, grasp: dict) -> dict:
    stage = new_stage(asset_dir / spec["id"] / "model.usdc")
    x_m, y_m, z_m = spec["size_object_m"]
    wall_m, bottom_m = spec["wall_thickness_m"], spec["bottom_thickness_m"]
    if not 0 < 2 * wall_m < min(x_m, y_m) or not 0 < bottom_m < z_m:
        raise ValueError(f"Invalid box dimensions: {spec}")
    pieces = [
        ((x_m, y_m, bottom_m), (0, 0, (-z_m + bottom_m) / 2)),
        ((wall_m, y_m, z_m - bottom_m), ((x_m - wall_m) / 2, 0, bottom_m / 2)),
        ((wall_m, y_m, z_m - bottom_m), ((wall_m - x_m) / 2, 0, bottom_m / 2)),
        ((x_m - 2 * wall_m, wall_m, z_m - bottom_m), (0, (y_m - wall_m) / 2, bottom_m / 2)),
        ((x_m - 2 * wall_m, wall_m, z_m - bottom_m), (0, (wall_m - y_m) / 2, bottom_m / 2)),
    ]
    for index, (size_m, part_position_object_m) in enumerate(pieces):
        cube = UsdGeom.Cube.Define(stage, f"/Asset/Wall_{index}")
        cube.CreateSizeAttr(1.0)
        cube.AddTranslateOp().Set(Gf.Vec3d(*part_position_object_m))
        cube.AddScaleOp().Set(Gf.Vec3f(*size_m))
        cube.CreateDisplayColorAttr([Gf.Vec3f(0.55, 0.32, 0.13)])
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    container = {
        "method": "exact parametric cuboids",
        "inner_size_object_m": [x_m - 2 * wall_m, y_m - 2 * wall_m, z_m - bottom_m],
        "opening_size_object_xy_m": [x_m - 2 * wall_m, y_m - 2 * wall_m],
        "wall_thickness_m": wall_m, "bottom_thickness_m": bottom_m,
        "floor_z_object_m": -z_m / 2 + bottom_m,
    }
    directory = asset_dir / spec["id"]
    (directory / "ATTRIBUTION.txt").write_text("SCALE-Bench parametric packing box. Generated from configs/assets/manipulation.yml.\n")
    (directory / "LICENSE.txt").write_bytes((PROJECT_ROOT / "LICENSE").read_bytes())
    return finish_asset(stage, spec, container, {"provider": "project_parametric", "license": "MIT", "specification": "configs/assets/manipulation.yml"}, {"type": "compound_cuboids", "count": 5}, grasp)


def prepare_pots(asset_dir: Path, specs: list[dict], decomposition: dict, grasp: dict) -> list[dict]:
    entries = []
    for source_id in sorted({spec["source_id"] for spec in specs}):
        source_dir = asset_dir / source_id
        source_metadata = json.loads((source_dir / "metadata.json").read_text())
        for item in source_metadata["generated_files"]:
            verify(source_dir / item["path"], "sha256", item["sha256"])
        source_stage = Usd.Stage.Open(str(source_dir / "model.usdc"))
        mesh = visual_mesh(source_stage)
        parts = coacd.run_coacd(coacd.Mesh(mesh.vertices, mesh.faces), **decomposition)
        for spec in (item for item in specs if item["source_id"] == source_id):
            directory = asset_dir / spec["id"]
            stage = new_stage(directory / "model.usdc")
            visual = UsdGeom.Xform.Define(stage, "/Asset/Visual")
            visual.GetPrim().GetReferences().AddReference(os.path.relpath(source_dir / "model.usdc", directory))
            visual.AddScaleOp().Set(Gf.Vec3f(spec["scale"]))
            for prim in Usd.PrimRange(visual.GetPrim()):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    prim.RemoveAPI(UsdPhysics.CollisionAPI)
                    prim.RemoveAPI(UsdPhysics.MeshCollisionAPI)
            collision_meshes = []
            for index, (vertices, faces) in enumerate(parts):
                vertices = vertices * spec["scale"]
                collider = UsdGeom.Mesh.Define(stage, f"/Asset/Collision/Part_{index}")
                collider.CreatePointsAttr(vertices.tolist())
                collider.CreateFaceVertexCountsAttr([3] * len(faces))
                collider.CreateFaceVertexIndicesAttr(faces.flatten().tolist())
                collider.CreateVisibilityAttr("invisible")
                UsdPhysics.CollisionAPI.Apply(collider.GetPrim())
                UsdPhysics.MeshCollisionAPI.Apply(collider.GetPrim()).CreateApproximationAttr("convexHull")
                collision_meshes.append(trimesh.Trimesh(vertices, faces, process=False))
            measured = measure_container(mesh.copy().apply_scale(spec["scale"]))
            # The scanned underside is irregular. A disk inside its measured
            # footprint supplies a continuous, level support and cavity floor.
            bottom_z_object_m = float(mesh.bounds[0, 2] * spec["scale"])
            base_radius_m = measured["bore_diameter_min_m"] / 2
            base = UsdGeom.Cylinder.Define(stage, "/Asset/Collision/Base")
            base.CreateRadiusAttr(base_radius_m)
            base.CreateHeightAttr(measured["bottom_thickness_m"])
            base.CreateAxisAttr("Z")
            base.AddTranslateOp().Set(Gf.Vec3d(0, 0, bottom_z_object_m + measured["bottom_thickness_m"] / 2))
            base.CreateVisibilityAttr("invisible")
            UsdPhysics.CollisionAPI.Apply(base.GetPrim())
            # A ray into the centre must hit the floor, not an artificial convex lid.
            cooked = trimesh.util.concatenate(collision_meshes)
            top_z_object_m = mesh.bounds[1, 2] * spec["scale"]
            hits = RayMeshIntersector(cooked).intersects_location([[0, 0, top_z_object_m + 0.1]], [[0, 0, -1]])[0]
            if not len(hits) or abs(hits[:, 2].max() - measured["floor_z_object_m"]) > 0.003:
                raise ValueError(f"Convex decomposition closed or distorted {spec['id']}'s cavity")
            (directory / "ATTRIBUTION.txt").write_text(
                (source_dir / "ATTRIBUTION.txt").read_text()
                + f"Changes: scaled by {spec['scale']}; convex decomposition, measured flat base collider and Piper grasp candidates.\n"
            )
            (directory / "LICENSE.txt").write_bytes((source_dir / "LICENSE.txt").read_bytes())
            entries.append(finish_asset(stage, spec, measured, {
                **source_metadata["source"], "metadata_sha256": checksum(source_dir / "metadata.json", "sha256"),
            }, {"type": "coacd_convex_parts_with_measured_base", "count": len(parts) + 1,
                "base_radius_m": base_radius_m, "base_height_m": measured["bottom_thickness_m"],
                "settings": decomposition, "version": version("coacd")}, grasp))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=PROJECT_ROOT / "configs/assets/manipulation.yml")
    parser.add_argument("--asset-dir", type=Path, default=PROJECT_ROOT / "Assets/Imported")
    parser.add_argument("--index-path", type=Path, default=PROJECT_ROOT / "configs/assets/index.json")
    args = parser.parse_args()
    catalog = yaml.safe_load(args.catalog.read_text())
    for source_id in ("planter_pot_clay", "ceramic_vase_01"):
        directory = args.asset_dir / source_id
        metadata = json.loads((directory / "metadata.json").read_text())
        metadata["container"] = measure_container(visual_mesh(Usd.Stage.Open(str(directory / "model.usdc"))))
        metadata["container_measurements_status"] = "mesh_sampled"
        (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    entries = [prepare_box(args.asset_dir, spec, catalog["grasp"]) for spec in catalog["boxes"]]
    entries.extend(prepare_pots(args.asset_dir, catalog["pots"], catalog["decomposition"], catalog["grasp"]))
    # Include updated measurements and every prepared background in one index.
    metadata_paths = sorted(args.asset_dir.glob("*/metadata.json")) + sorted(args.asset_dir.glob("*/*/metadata.json"))
    all_entries = [json.loads(path.read_text()) for path in metadata_paths]
    (args.asset_dir / "index.json").write_text(json.dumps({"assets": all_entries}, indent=2) + "\n")
    index = []
    for path, metadata in zip(metadata_paths, all_entries, strict=True):
        index.append({
            "id": metadata["id"], "role": metadata["role"], "usd_path": metadata["usd_path"],
            "size_object_m": metadata["size_object_m"],
            "metadata_sha256": checksum(path, "sha256"),
            "usd_sha256": checksum(path.with_name("model.usdc"), "sha256"),
            "license": metadata["source"]["license"],
        })
    args.index_path.write_text(json.dumps({"assets": index}, indent=2) + "\n")


if __name__ == "__main__":
    main()
