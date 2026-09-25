"""Render dimensioned orthographic views of rigid USD assets in Isaac Sim."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from isaacsim import SimulationApp
    from pxr import Gf, Usd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = PROJECT_ROOT / "docs/assets/fonts/inter-latin-wght-normal.woff2"
Vector3 = tuple[float, float, float]
Point2 = tuple[float, float]
BACKGROUND = "#f5f6f8"
INK = "#243348"
DIMENSION_COLOR = "#8a969e"
DIMENSION_TEXT = "#4e5c66"
ELEVATION_RAD = math.radians(16)


@dataclass(frozen=True)
class Asset:
    path: Path
    label: str
    meters_per_unit: float
    minimum_object_m: Vector3
    maximum_object_m: Vector3

    @property
    def size_object_m(self) -> Vector3:
        return tuple(b - a for a, b in zip(self.minimum_object_m, self.maximum_object_m))


@dataclass(frozen=True)
class View:
    name: str
    horizontal_axis: int
    vertical_axis: int
    camera_direction_world: Vector3
    camera_up_world: Vector3


# Front and side look down 16 degrees; top looks along -Z with +Y up.
VIEWS = (
    View("front", 0, 2,
         (0.0, -math.cos(ELEVATION_RAD), math.sin(ELEVATION_RAD)),
         (0.0, math.sin(ELEVATION_RAD), math.cos(ELEVATION_RAD))),
    View("side", 1, 2,
         (math.cos(ELEVATION_RAD), 0.0, math.sin(ELEVATION_RAD)),
         (-math.sin(ELEVATION_RAD), 0.0, math.cos(ELEVATION_RAD))),
    View("top", 0, 1, (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "usd_paths", nargs="+", type=Path,
        help="USD files, in display order; shell globs are supported",
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path,
        help="Directory for front.png, side.png and top.png",
    )
    parser.add_argument(
        "--panel-size", type=int, default=640,
        help="Pixels per square asset panel (default: 640); increase for publication",
    )
    args = parser.parse_args()
    if args.panel_size < 400:
        parser.error("--panel-size must be at least 400 for readable dimensions")
    args.usd_paths = [path.expanduser().resolve() for path in args.usd_paths]
    for path in args.usd_paths:
        if not path.is_file() or path.suffix.lower() not in {".usd", ".usda", ".usdc", ".usdz"}:
            parser.error(f"expected an existing USD file: {path}")
    if len(set(args.usd_paths)) != len(args.usd_paths):
        parser.error("USD input paths must be unique")
    args.output_dir = args.output_dir.expanduser().resolve()
    return args


def inspect_assets(paths: list[Path]) -> list[Asset]:
    """Measure visible render geometry at the default time, in source Z-up axes."""
    from pxr import Usd, UsdGeom

    common_parent = Path(os.path.commonpath([path.parent for path in paths]))
    assets: list[Asset] = []
    for path in paths:
        stage = Usd.Stage.Open(str(path))
        root = stage.GetDefaultPrim()
        if not root:
            raise ValueError(f"USD must define a default prim: {path}")
        if UsdGeom.GetStageUpAxis(stage) != UsdGeom.Tokens.z:
            raise ValueError(f"Expected a Z-up rigid asset; align the asset before rendering: {path}")
        meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
        bounds = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
            useExtentsHint=False,
        ).ComputeWorldBound(root).ComputeAlignedRange()
        minimum_object_m = tuple(float(value * meters_per_unit) for value in bounds.GetMin())
        maximum_object_m = tuple(float(value * meters_per_unit) for value in bounds.GetMax())
        if (
            bounds.IsEmpty() or not math.isfinite(meters_per_unit) or meters_per_unit <= 0
            or any(
                not math.isfinite(a) or not math.isfinite(b) or b <= a
                for a, b in zip(minimum_object_m, maximum_object_m)
            )
        ):
            raise ValueError(f"Asset must have finite, nonzero visible dimensions: {path}")
        relative = path.relative_to(common_parent)
        label = str(relative.parent) if relative.parent != Path(".") else path.stem
        if len(paths) == 1:
            label = f"{path.parent.name}/{path.stem}"
        assets.append(Asset(path, label, meters_per_unit, minimum_object_m, maximum_object_m))
    return assets


def create_scene(stage: Usd.Stage, span_m: float) -> None:
    from pxr import Gf, UsdGeom, UsdLux

    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    dome = UsdLux.DomeLight.Define(stage, "/World/Light")
    dome.CreateIntensityAttr(650.0)
    key = UsdLux.DistantLight.Define(stage, "/World/Key")
    key.CreateIntensityAttr(1800.0)
    key.CreateAngleAttr(12.0)
    UsdGeom.XformCommonAPI(key).SetRotate(Gf.Vec3f(25.0, -30.0, -25.0))
    ground = UsdGeom.Cube.Define(stage, "/World/Ground")
    ground.CreateSizeAttr(1.0)
    ground.CreateDisplayColorAttr([Gf.Vec3f(0.8, 0.82, 0.85)])
    UsdGeom.XformCommonAPI(ground).SetScale(Gf.Vec3f(span_m * 100, span_m * 100, span_m * 0.01))
    UsdGeom.XformCommonAPI(ground).SetTranslate(Gf.Vec3d(0.0, 0.0, -span_m * 0.005))


def load_asset(stage: Usd.Stage, asset: Asset) -> None:
    """Use a wrapper transform so authored asset transforms remain intact."""
    from pxr import Gf, Usd, UsdGeom, UsdPhysics

    stage.RemovePrim("/World/Asset")
    wrapper = UsdGeom.Xform.Define(stage, "/World/Asset")
    object_center_object_m = tuple((a + b) / 2 for a, b in zip(asset.minimum_object_m, asset.maximum_object_m))
    object_translation_world_m = Gf.Vec3d(
        -object_center_object_m[0], -object_center_object_m[1], -asset.minimum_object_m[2],
    )
    wrapper.AddTranslateOp().Set(object_translation_world_m)
    wrapper.AddScaleOp().Set(Gf.Vec3f(asset.meters_per_unit))
    source = stage.DefinePrim("/World/Asset/Source")
    if not source.GetReferences().AddReference(str(asset.path)):
        raise RuntimeError(f"Could not reference asset: {asset.path}")
    for prim in Usd.PrimRange(source):
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI(prim).CreateRigidBodyEnabledAttr(False)


def configure_camera(stage: Usd.Stage, view: View, span_m: float) -> Gf.Matrix4d:
    from pxr import Gf, UsdGeom

    # Offset in the camera plane so every variant shares the same baseline.
    camera_up_world = Gf.Vec3d(*view.camera_up_world)
    camera_target_world_m = camera_up_world * (0.28 if view.vertical_axis == 2 else -0.02) * span_m
    camera_target_world_m[view.horizontal_axis] = 0.07 * span_m
    camera_position_world_m = camera_target_world_m + Gf.Vec3d(*view.camera_direction_world) * span_m * 4
    camera_transform_world = Gf.Matrix4d().SetLookAt(
        camera_position_world_m, camera_target_world_m, Gf.Vec3d(*view.camera_up_world),
    ).GetInverse()
    camera = UsdGeom.Camera.Define(stage, "/World/Camera")
    camera.CreateProjectionAttr(UsdGeom.Tokens.orthographic)
    # USD aperture is expressed in tenths of a stage unit (stage uses metres).
    camera.CreateHorizontalApertureAttr(span_m * 10)
    camera.CreateVerticalApertureAttr(span_m * 10)
    camera.CreateClippingRangeAttr(Gf.Vec2f(span_m * 0.01, span_m * 10))
    xform = UsdGeom.Xformable(camera)
    xform.ClearXformOpOrder()
    xform.AddTransformOp().Set(camera_transform_world)
    return camera_transform_world


def project_to_image(
    point_world_m: Vector3, camera_transform_world: Gf.Matrix4d,
    span_m: float, panel_size: int,
) -> Point2:
    from pxr import Gf

    point_camera_m = camera_transform_world.GetInverse().Transform(Gf.Vec3d(*point_world_m))
    return (
        (0.5 + point_camera_m[0] / span_m) * panel_size,
        (0.5 - point_camera_m[1] / span_m) * panel_size,
    )


def draw_dimension(
    draw: ImageDraw.ImageDraw, start: Point2, end: Point2, label: str,
    font: ImageFont.FreeTypeFont, panel_size: int,
) -> None:
    """Keep a gap around the label without painting over the rendered background."""
    line_width = max(1, round(panel_size / 640))
    arrow = panel_size * 0.007
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    box = draw.textbbox(midpoint, label, font=font, anchor="mm")
    gap = ((box[2] - box[0]) if abs(dx) > abs(dy) else (box[3] - box[1])) / 2 + panel_size * 0.012
    for tip, sign in ((start, -1), (end, 1)):
        if length > gap * 2:
            draw.line((tip, (midpoint[0] + sign * ux * gap, midpoint[1] + sign * uy * gap)),
                      fill=DIMENSION_COLOR, width=line_width)
    for tip, sign in ((start, 1), (end, -1)):
        base = (tip[0] + sign * ux * arrow, tip[1] + sign * uy * arrow)
        draw.polygon((tip, (base[0] - uy * arrow / 2, base[1] + ux * arrow / 2),
                      (base[0] + uy * arrow / 2, base[1] - ux * arrow / 2)), fill=DIMENSION_COLOR)
    draw.text(midpoint, label, font=font, fill=DIMENSION_TEXT, anchor="mm")


def annotate(
    image: Image.Image, asset: Asset, view: View, span_m: float,
    camera_transform_world: Gf.Matrix4d,
) -> Image.Image:
    panel_size = image.width
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT_PATH), round(panel_size * 0.03))
    title_font = ImageFont.truetype(str(FONT_PATH), round(panel_size * 0.038))
    while title_font.getlength(asset.label) > panel_size * 0.9:
        title_font = ImageFont.truetype(str(FONT_PATH), title_font.size - 1)
    title_font.set_variation_by_axes([550])
    draw.text((panel_size / 2, panel_size * 0.94), asset.label, font=title_font, fill=INK, anchor="mm")
    size_object_m = asset.size_object_m
    corners_image = [
        project_to_image((x, y, z), camera_transform_world, span_m, panel_size)
        for x in (-size_object_m[0] / 2, size_object_m[0] / 2)
        for y in (-size_object_m[1] / 2, size_object_m[1] / 2)
        for z in (0.0, size_object_m[2])
    ]
    left = min(point[0] for point in corners_image)
    right = max(point[0] for point in corners_image)
    bottom = max(point[1] for point in corners_image)
    # Height dimensions follow a Z segment through the object's centre plane;
    # their projected length is H*cos(elevation), not the silhouette's height.
    dimension_start_world_m = [0.0, 0.0, 0.0]
    dimension_end_world_m = [0.0, 0.0, 0.0]
    dimension_start_world_m[view.vertical_axis] = -size_object_m[1] / 2 if view.name == "top" else 0.0
    dimension_end_world_m[view.vertical_axis] = size_object_m[view.vertical_axis] + dimension_start_world_m[view.vertical_axis]
    height_bottom = project_to_image(tuple(dimension_start_world_m), camera_transform_world, span_m, panel_size)[1]
    height_top = project_to_image(tuple(dimension_end_world_m), camera_transform_world, span_m, panel_size)[1]
    horizontal_offset = panel_size * 0.045
    vertical_offset = panel_size * 0.08
    extension = panel_size * 0.01
    for x in (left, right):
        draw.line(((x, bottom + extension), (x, bottom + horizontal_offset + extension)), fill=DIMENSION_COLOR)
    for y in (height_top, height_bottom):
        draw.line(((right + extension, y), (right + vertical_offset + extension, y)), fill=DIMENSION_COLOR)
    for start, end, axis in (
        ((left, bottom + horizontal_offset), (right, bottom + horizontal_offset), view.horizontal_axis),
        ((right + vertical_offset, height_top), (right + vertical_offset, height_bottom), view.vertical_axis),
    ):
        label = f"{asset.size_object_m[axis] * 100:.3g} cm"
        draw_dimension(draw, start, end, label, font, panel_size)
    return image


def render(app: SimulationApp, assets: list[Asset], output_dir: Path, panel_size: int) -> None:
    import numpy as np
    import omni.replicator.core as rep
    import omni.usd

    omni.usd.get_context().new_stage()
    stage = omni.usd.get_context().get_stage()
    span_m = max(
        max(asset.size_object_m[view.horizontal_axis],
            sum(abs(up) * size for up, size in zip(view.camera_up_world, asset.size_object_m)))
        for asset in assets for view in VIEWS
    ) / 0.66
    create_scene(stage, span_m)
    columns = min(3, len(assets))
    rows = math.ceil(len(assets) / columns)
    sheets = {view.name: Image.new("RGB", (columns * panel_size, rows * panel_size), BACKGROUND) for view in VIEWS}
    configure_camera(stage, VIEWS[0], span_m)
    product = rep.create.render_product("/World/Camera", (panel_size, panel_size))
    rgb = rep.AnnotatorRegistry.get_annotator("rgb")
    mask = rep.AnnotatorRegistry.get_annotator("instance_id_segmentation", init_params={"colorize": False})
    rgb.attach([product])
    mask.attach([product])
    try:
        for index, asset in enumerate(assets):
            load_asset(stage, asset)
            for view in VIEWS:
                camera_transform_world = configure_camera(stage, view, span_m)
                # Wait for USD, materials and RTX before accumulating a static frame.
                for _ in range(8):
                    app.update()
                rep.orchestrator.step(rt_subframes=16, pause_timeline=True)
                pixels = rgb.get_data()
                segmentation = mask.get_data()
                if pixels.shape != (panel_size, panel_size, 4):
                    raise RuntimeError(f"Invalid RGB frame for {asset.path}: {pixels.shape}")
                object_ids = [int(key) for key, value in segmentation["info"]["idToLabels"].items()
                              if str(value).startswith("/World/Asset/")]
                foreground = np.isin(segmentation["data"], object_ids)
                if not foreground.any():
                    raise RuntimeError(f"No asset pixels rendered: {asset.path} ({view.name})")
                image = Image.fromarray(pixels).convert("RGB")
                annotate(image, asset, view, span_m, camera_transform_world)
                sheets[view.name].paste(image, ((index % columns) * panel_size, (index // columns) * panel_size))
                print(f"Rendered {asset.label}: {view.name}, dimensions (m)={asset.size_object_m}", flush=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, sheet in sheets.items():
            path = output_dir / f"{name}.png"
            sheet.save(path)
            print(f"Saved {path}", flush=True)
    finally:
        rgb.detach([product])
        mask.detach([product])
        product.destroy()


def main() -> None:
    args = parse_args()
    from isaacsim import SimulationApp

    app = SimulationApp({"headless": True, "renderer": "RaytracedLighting"})
    try:
        assets = inspect_assets(args.usd_paths)
        render(app, assets, args.output_dir, args.panel_size)
    finally:
        app.close()


if __name__ == "__main__":
    main()
