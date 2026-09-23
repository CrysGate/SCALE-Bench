from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Sequence


DEFAULT_USD_NAME = "Aligned.usd"
DEFAULT_USDA_NAME = "Aligned.usda"
DEFAULT_OBJ_NAME = "Aligned.obj"
MANIFEST_NAME = "conversion.json"
POST_CONVERSION_UPDATES = 3

simulation_app: Any = None
asset_converter: Any = None
Usd: Any = None
UsdGeom: Any = None
UsdPhysics: Any = None


@dataclass(frozen=True)
class StageSummary:
    up_axis: str
    meters_per_unit: float
    mesh_prims: int
    visible_mesh_prims: int
    joint_prims: int
    points: int
    faces: int


@dataclass(frozen=True)
class ObjSummary:
    vertices: int
    texture_coordinates: int
    normals: int
    faces: int
    material_libraries: tuple[str, ...]
    materials_used: tuple[str, ...]
    aabb_min: Optional[tuple[float, float, float]]
    aabb_max: Optional[tuple[float, float, float]]


def initialize_isaac_runtime() -> None:
    global simulation_app, asset_converter, Usd, UsdGeom, UsdPhysics
    if simulation_app is not None:
        return

    saved_argv = sys.argv[:]
    sys.argv = [saved_argv[0]]
    try:
        from isaacsim import SimulationApp

        simulation_app = SimulationApp({"headless": True})
        import omni.kit.asset_converter as asset_converter_module
        from pxr import Usd as usd_module
        from pxr import UsdGeom as usd_geom_module
        from pxr import UsdPhysics as usd_physics_module
    except BaseException:
        if simulation_app is not None:
            simulation_app.close()
        simulation_app = None
        raise
    finally:
        sys.argv = saved_argv

    asset_converter = asset_converter_module
    Usd = usd_module
    UsdGeom = usd_geom_module
    UsdPhysics = usd_physics_module


def require_isaac_runtime() -> None:
    if any(
        module is None
        for module in (simulation_app, asset_converter, Usd, UsdGeom, UsdPhysics)
    ):
        raise RuntimeError("Isaac Sim runtime has not been initialized")


def discover_usd_assets(
    folders: Sequence[Path],
    source_root: Path,
    prefer_binary: bool,
) -> list[Path]:
    candidates: dict[Path, Path] = {}
    for folder in folders:
        folder = folder.resolve()
        if folder != source_root and source_root not in folder.parents:
            raise ValueError(f"Folder is outside --source-root: {folder}")
        if not folder.exists():
            print(f"Warning: folder does not exist: {folder}")
            continue
        if folder.is_file():
            if folder.suffix.lower() not in {".usd", ".usda", ".usdc"}:
                print(f"Warning: unsupported input file: {folder}")
                continue
            candidates[folder.parent.resolve()] = folder
            continue

        for root, _, files in os.walk(folder):
            lower_names = {name.lower(): name for name in files}
            preferred_names = (
                (DEFAULT_USD_NAME.lower(), DEFAULT_USDA_NAME.lower())
                if prefer_binary
                else (DEFAULT_USDA_NAME.lower(), DEFAULT_USD_NAME.lower())
            )
            for name in preferred_names:
                if name in lower_names:
                    asset_dir = Path(root).resolve()
                    candidates[asset_dir] = asset_dir / lower_names[name]
                    break
    return [candidates[key] for key in sorted(candidates, key=str)]


def analyze_stage(input_path: Path) -> StageSummary:
    require_isaac_runtime()
    stage = Usd.Stage.Open(str(input_path))
    if stage is None:
        raise RuntimeError(f"Cannot open USD stage: {input_path}")

    mesh_prims = visible_mesh_prims = joint_prims = points = faces = 0
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Joint):
            joint_prims += 1
        if not prim.IsA(UsdGeom.Mesh):
            continue

        mesh_prims += 1
        imageable = UsdGeom.Imageable(prim)
        is_visible = imageable.ComputeVisibility() != UsdGeom.Tokens.invisible
        if is_visible:
            visible_mesh_prims += 1

        mesh = UsdGeom.Mesh(prim)
        mesh_points = mesh.GetPointsAttr().Get(Usd.TimeCode.Default()) or []
        face_counts = mesh.GetFaceVertexCountsAttr().Get(Usd.TimeCode.Default()) or []
        points += len(mesh_points)
        faces += len(face_counts)

    return StageSummary(
        up_axis=str(UsdGeom.GetStageUpAxis(stage)),
        meters_per_unit=float(UsdGeom.GetStageMetersPerUnit(stage)),
        mesh_prims=mesh_prims,
        visible_mesh_prims=visible_mesh_prims,
        joint_prims=joint_prims,
        points=points,
        faces=faces,
    )


async def export_usd_to_obj(
    input_path: Path,
    output_path: Path,
    bake_mdl_materials: bool,
) -> tuple[bool, str]:
    require_isaac_runtime()
    context = asset_converter.AssetConverterContext()
    context.ignore_materials = False
    context.ignore_animations = True
    context.ignore_camera = True
    context.ignore_light = True
    context.export_hidden_props = False
    context.bake_mdl_material = bake_mdl_materials

    task = asset_converter.get_instance().create_converter_task(
        str(input_path),
        str(output_path),
        None,
        context,
    )
    success = await task.wait_until_finished()
    if success:
        return True, ""
    return False, f"{task.get_status()} - {task.get_error_message()}"


def analyze_obj(obj_path: Path) -> ObjSummary:
    vertices: list[tuple[float, float, float]] = []
    texture_coordinates = normals = faces = 0
    material_libraries: set[str] = set()
    materials_used: set[str] = set()

    with obj_path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("v "):
                values = line.split()
                if len(values) >= 4:
                    vertices.append(tuple(float(value) for value in values[1:4]))
            elif line.startswith("vt "):
                texture_coordinates += 1
            elif line.startswith("vn "):
                normals += 1
            elif line.startswith("f "):
                faces += 1
            elif line.startswith("mtllib "):
                material_libraries.add(line.removeprefix("mtllib ").strip())
            elif line.startswith("usemtl "):
                materials_used.add(line.removeprefix("usemtl ").strip())

    aabb_min: Optional[tuple[float, float, float]] = None
    aabb_max: Optional[tuple[float, float, float]] = None
    if vertices:
        aabb_min = tuple(min(vertex[axis] for vertex in vertices) for axis in range(3))
        aabb_max = tuple(max(vertex[axis] for vertex in vertices) for axis in range(3))

    return ObjSummary(
        vertices=len(vertices),
        texture_coordinates=texture_coordinates,
        normals=normals,
        faces=faces,
        material_libraries=tuple(sorted(material_libraries)),
        materials_used=tuple(sorted(materials_used)),
        aabb_min=aabb_min,
        aabb_max=aabb_max,
    )


def _copy_conversion_outputs(
    temporary_directory: Path,
    output_directory: Path,
    force: bool,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    for source in temporary_directory.iterdir():
        destination = output_directory / source.name
        if destination.exists() and not force:
            raise FileExistsError(f"Output already exists: {destination}")
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=force)
        else:
            shutil.copy2(source, destination)


def _write_manifest(
    manifest_path: Path,
    source_path: Path,
    output_path: Path,
    stage_summary: StageSummary,
    obj_summary: ObjSummary,
) -> None:
    payload = {
        "source": str(source_path),
        "output": str(output_path),
        "source_stage": asdict(stage_summary),
        "output_obj": asdict(obj_summary),
        "losses": [
            "USD physics schemas and collision settings are not represented in OBJ.",
            "USD joints and articulation are not represented in OBJ.",
            "USD scene hierarchy may be flattened by the exporter.",
        ],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _format_dimensions(summary: ObjSummary) -> str:
    if summary.aabb_min is None or summary.aabb_max is None:
        return "unknown"
    dimensions = tuple(
        summary.aabb_max[axis] - summary.aabb_min[axis] for axis in range(3)
    )
    return " x ".join(f"{value:.6g}" for value in dimensions)


def convert_one(
    input_path: Path,
    source_root: Path,
    output_root: Path,
    include_articulated: bool,
    bake_mdl_materials: bool,
    force: bool,
    loop: asyncio.AbstractEventLoop,
) -> str:
    relative_parent = input_path.parent.resolve().relative_to(source_root)
    output_directory = output_root / relative_parent
    output_obj = output_directory / DEFAULT_OBJ_NAME
    if output_obj.exists() and not force:
        print(f"[skip existing] {output_obj}")
        return "skipped"

    stage_summary = analyze_stage(input_path)
    if stage_summary.mesh_prims == 0:
        print(f"[skip no mesh] {input_path}")
        return "skipped"
    if stage_summary.joint_prims and not include_articulated:
        print(
            f"[skip articulated] {input_path} "
            f"({stage_summary.joint_prims} joint prims)"
        )
        return "skipped"

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{input_path.parent.name}-",
        dir=output_directory.parent,
    ) as temporary_name:
        temporary_directory = Path(temporary_name)
        temporary_obj = temporary_directory / DEFAULT_OBJ_NAME
        success, error = loop.run_until_complete(
            export_usd_to_obj(input_path, temporary_obj, bake_mdl_materials)
        )
        for _ in range(POST_CONVERSION_UPDATES):
            simulation_app.update()
        if not success:
            raise RuntimeError(f"Asset Converter failed: {error}")
        if not temporary_obj.is_file():
            raise RuntimeError(f"Exporter did not create OBJ: {temporary_obj}")

        temporary_summary = analyze_obj(temporary_obj)
        _copy_conversion_outputs(
            temporary_directory,
            output_directory,
            force,
        )

    final_summary = analyze_obj(output_obj)
    _write_manifest(
        output_directory / MANIFEST_NAME,
        input_path,
        output_obj,
        stage_summary,
        final_summary,
    )
    print(
        f"[converted] {input_path} -> {output_obj}; "
        f"meshes={stage_summary.mesh_prims}, vertices={temporary_summary.vertices}, "
        f"faces={temporary_summary.faces}, size={_format_dimensions(temporary_summary)}"
    )
    return "converted"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-export benchmark Aligned.usda/Aligned.usd assets to OBJ while "
            "preserving their relative directory layout."
        )
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--folders",
        type=Path,
        nargs="+",
        default=None,
        help="Folders or USD files to process; defaults to --source-root.",
    )
    parser.add_argument(
        "--prefer-usd",
        action="store_true",
        help="Prefer Aligned.usd instead of the composed Aligned.usda wrapper.",
    )
    parser.add_argument(
        "--include-articulated",
        action="store_true",
        help="Export articulated stages as static OBJ geometry instead of skipping them.",
    )
    parser.add_argument(
        "--bake-mdl-materials",
        action="store_true",
        help="Ask Asset Converter to bake supported MDL materials during export.",
    )
    parser.add_argument("--max-models", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = args.source_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    folders = [
        folder.expanduser().resolve()
        for folder in (args.folders or [source_root])
    ]

    if not source_root.is_dir():
        raise ValueError(f"--source-root is not a directory: {source_root}")
    if args.max_models < 0:
        raise ValueError("--max-models cannot be negative")
    if output_root == source_root or source_root in output_root.parents:
        raise ValueError("--output-root must be outside --source-root")

    input_paths = discover_usd_assets(folders, source_root, args.prefer_usd)
    if args.max_models:
        input_paths = input_paths[: args.max_models]
    print(f"Found {len(input_paths)} USD assets.")
    if not input_paths:
        return 0

    initialize_isaac_runtime()
    converted = skipped = failed = 0
    try:
        loop = asyncio.get_event_loop()
        for input_path in input_paths:
            try:
                result = convert_one(
                    input_path=input_path,
                    source_root=source_root,
                    output_root=output_root,
                    include_articulated=args.include_articulated,
                    bake_mdl_materials=args.bake_mdl_materials,
                    force=args.force,
                    loop=loop,
                )
                if result == "converted":
                    converted += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                print(f"[failed] {input_path}: {exc}")
            finally:
                simulation_app.update()
    finally:
        simulation_app.close()

    print(
        f"Summary: found={len(input_paths)}, converted={converted}, "
        f"skipped={skipped}, failed={failed}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
