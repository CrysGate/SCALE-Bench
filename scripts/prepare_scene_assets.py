"""Normalize downloaded representatives as static, collidable USD scene props."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from xml.etree import ElementTree

from pxr import Gf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdUtils
import yaml

from download_scene_assets import checksum, verify


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def visible_bounds(stage: Usd.Stage) -> Gf.Range3d:
    bounds = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
    ).ComputeWorldBound(stage.GetDefaultPrim()).ComputeAlignedRange()
    if bounds.IsEmpty() or any(not math.isfinite(v) or v <= 0 for v in bounds.GetSize()):
        raise ValueError(f"Invalid visible bounds: {stage.GetRootLayer().identifier}")
    return bounds


def prepare(directory: Path, mjcf_models: dict[str, str]) -> list[dict]:
    manifest = json.loads((directory / "source_manifest.json").read_text())
    spec = manifest["asset"]
    for item in manifest["files"]:
        verify(directory / item["path"], "sha256", item["sha256"])
    entry = directory / manifest["entry"]
    collision_meshes: set[str] = set()
    if spec["provider"] == "huggingface_zip":
        from mujoco_usd_converter import Converter

        mjcf_path = directory / mjcf_models[spec["id"]]
        document = ElementTree.parse(mjcf_path)
        collision_meshes = {geom.attrib["mesh"] for geom in document.findall('.//geom[@class="collision"]')}
        entry = Path(Converter(layer_structure=True, scene=False).convert(
            str(mjcf_path), str(directory / "converted"),
        ).path)

    if spec["provider"] == "github_zip":
        return [
            normalize(directory, spec, directory / relative, directory / name / "model.usdc", set())
            for name, relative in spec["models"].items()
        ]
    return [normalize(directory, spec, entry, directory / "model.usdc", collision_meshes)]


def normalize(directory: Path, spec: dict, entry: Path, output: Path, collision_meshes: set[str]) -> dict:
    source = Usd.Stage.Open(str(entry))
    if not source or not source.GetDefaultPrim():
        raise ValueError(f"Source must have a default prim: {entry}")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(output))
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(stage, "/Asset")
    stage.SetDefaultPrim(root.GetPrim())
    # Isaac Lab sets the root pose when spawning; alignment belongs below it.
    center = UsdGeom.Xform.Define(stage, "/Asset/Centered").AddTranslateOp()
    units = UsdGeom.Xform.Define(stage, "/Asset/Centered/Units")
    units.AddScaleOp().Set(Gf.Vec3f(UsdGeom.GetStageMetersPerUnit(source)))
    axis = UsdGeom.GetStageUpAxis(source)
    if axis == UsdGeom.Tokens.y:
        units.AddRotateXOp().Set(90.0)
    elif axis != UsdGeom.Tokens.z:
        raise ValueError(f"Unsupported source up axis {axis}: {entry}")
    reference = stage.DefinePrim("/Asset/Centered/Units/Source")
    reference.GetReferences().AddReference(os.path.relpath(entry, output.parent))
    for prim in stage.Traverse():
        if prim.HasAPI(UsdLux.LightAPI):
            prim.SetActive(False)
            continue
        if prim.IsInstance():
            prim.SetInstanceable(False)
    collider_count = 0
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI(prim).CreateRigidBodyEnabledAttr(False)
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            prim.RemoveAPI(UsdPhysics.ArticulationRootAPI)
        if prim.IsA(UsdPhysics.Joint):
            prim.SetActive(False)
        if not prim.IsA(UsdGeom.Gprim):
            continue
        if collision_meshes:
            # The chosen rigid MJCF has named visual/convex collision meshes and
            # a transparent region marker. Keep its original convex pieces.
            if prim.GetName() in collision_meshes:
                UsdGeom.Imageable(prim).CreateVisibilityAttr(UsdGeom.Tokens.invisible)
                collider_count += 1
            elif prim.GetName() == "reg_bbox":
                prim.SetActive(False)
        elif prim.IsA(UsdGeom.Mesh):
            # Static triangle meshes preserve the vase/pot openings. Dynamic
            # manipulation will require separately validated collision assets.
            UsdPhysics.CollisionAPI.Apply(prim).CreateCollisionEnabledAttr(True)
            UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr("none")
            collider_count += 1
    if not collider_count:
        raise ValueError(f"No colliders prepared: {directory}")
    if collision_meshes and collider_count != len(collision_meshes):
        raise ValueError(f"MJCF collision pieces lost: {directory}")
    bounds = visible_bounds(stage)
    center.Set(-bounds.GetMidpoint())
    stage.GetRootLayer().Save()
    bounds = visible_bounds(stage)
    layers, dependencies, unresolved = UsdUtils.ComputeAllDependencies(str(output))
    # NVIDIA assets reference these shader modules shipped with Isaac Sim.
    missing_files = [path for path in unresolved if path not in {"OmniPBR.mdl", "OmniGlass.mdl"}]
    if missing_files:
        raise ValueError(f"Unresolved USD dependencies for {output}: {missing_files}")
    dependency_paths = {Path(layer.realPath) for layer in layers} | {Path(path) for path in dependencies}
    for path in dependency_paths:
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"Nonportable asset dependency: {path}")
    generated = [
        {"path": str(path.relative_to(directory)), "sha256": checksum(path, "sha256")}
        for path in sorted(directory.rglob("*"))
        if path.is_file() and (path == output or "converted" in path.relative_to(directory).parts)
    ]
    asset_id = str(output.parent.relative_to(directory.parent))
    metadata = {
        "id": asset_id, "scene": spec["scene"], "role": "background",
        "usd_path": f"Assets/Imported/{asset_id}/model.usdc",
        "size_object_m": list(bounds.GetSize()), "origin": "visual_aabb_center",
        "meters_per_unit": 1.0, "up_axis": "Z",
        "collision": {"type": "source_convex_parts" if collision_meshes else "static_triangle_mesh", "count": collider_count},
        "manipulation_ready": False,
        "source": spec,
        "source_manifest_sha256": checksum(directory / "source_manifest.json", "sha256"),
        "generated_files": generated,
        "runtime_dependencies": sorted(unresolved),
        "converter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "container_measurements_status": "unmeasured" if spec["id"] in {"ceramic_vase_01", "planter_pot_clay"} else "not_applicable",
    }
    (output.parent / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Prepared {asset_id}: {metadata['size_object_m']} m; {collider_count} colliders", flush=True)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=PROJECT_ROOT / "configs/assets/representatives.yml")
    parser.add_argument("--asset-dir", type=Path, default=PROJECT_ROOT / "Assets/Imported")
    args = parser.parse_args()
    catalog = yaml.safe_load(args.catalog.read_text())
    entries = [entry for spec in catalog["assets"] for entry in prepare(args.asset_dir / spec["id"], catalog["mjcf_models"])]
    (args.asset_dir / "index.json").write_text(json.dumps({"assets": entries}, indent=2) + "\n")


if __name__ == "__main__":
    main()
