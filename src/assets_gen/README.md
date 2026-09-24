# OBJ to USD Asset Conversion

[简体中文](README.zh-CN.md)

`convert_obj_to_usd.py` uses Isaac Sim's Asset Converter to process OBJ assets
in batches and generate standardized USD files for rigid-body simulation. It
can also read mass and dimensions from XLSX metadata, scale each `x/y/z` axis
independently, and export the aligned geometry as OBJ files.

## Requirements

The script requires Isaac Sim 6.0.1 and the project dependencies. It starts
`SimulationApp` in headless mode. The `pxr` and `omni` modules must therefore
be imported only after the Isaac Sim runtime is initialized.

```bash
uv run python src/assets_gen/convert_obj_to_usd.py \
  --assets-root ./assets \
  --folders ./assets/vase ./assets/mug \
  --metadata-xlsx ./assets/sample.xlsx \
  --output-root ./converted-obj \
  --usd-output-root ./converted-usd
```

When `--folders` is omitted, the script scans `<assets-root>/vase`. When
`--metadata-xlsx` is omitted, it reads `<assets-root>/sample.xlsx`. The default
OBJ output directory is `<assets-root>/../rigid assets`. All defaults are
portable relative paths rather than machine-specific user paths.

## Processing Pipeline

1. Optionally extract ZIP archives under the input folders. Git LFS pointers
   are skipped, and archive members are checked for path traversal.
2. Recursively discover OBJ files and deduplicate them by resolved path.
3. Generate USD directly from the original OBJ with Asset Converter, measure
   the source AABB, and match the corresponding metadata record.
4. Create `/root/{_materials,visual,collision}`. Source hierarchy transforms,
   physical dimension scaling, and up-axis alignment are baked into the visual
   and collision meshes. The baked mesh AABB is then centered on `/root`, so
   the rigid-body root represents the geometry center.
5. Author rigid-body properties, mass, and `scale_x/scale_y/scale_z` on
   `/root`; apply PhysX convex-decomposition colliders to the collision mesh;
   then author `real_x/real_y/real_z` on `/root`.
6. Limit collision geometry to 500000 triangles and use `maxConvexHulls=128`
   and `errorPercentage=0.010001`. Visual geometry is not simplified. The small margin above 0.01
   avoids float32 rounding below the convex decomposer’s minimum.
7. Save `Aligned.usd`, generate `metadata.json`, and copy material resources into
   `textures/` with relative USD references, including transitive relative MDL imports. Converter temporary files are cleaned
   up. Export `Aligned.obj` into the separate OBJ output directory.

Each source directory receives an `Aligned.usd`. Exported OBJ files preserve
the directory layout relative to `--assets-root`, for example:

```text
assets/vase/001/model.obj
converted-usd/vase/001/Aligned.usd
converted-usd/vase/001/metadata.json
converted-usd/vase/001/textures/
converted-obj/vase/001/Aligned.obj
```

With `--usd-output-root`, each asset package follows the Geniesim layout:
`Aligned.usd`, `metadata.json`, and `textures/`. Without this option, output stays
beside the source OBJ and source files are preserved. Existing USD files are
skipped; use `--force` to regenerate their packages.
With `--force`, existing files are replaced only after the new package is
complete; a failed conversion leaves the previous package in place.

Generated JSON contains `physics.size` (final x/y/z dimensions in meters),
`physics.mass` (the applied mass in kg), and `physics.friction` (matching the USD,
currently 1.0). Values describe the converted asset, not the reference asset.

## Metadata Format

Only the first worksheet is read. The first row must contain headers using the
following supported names:

- Name: `name`, `object`, `名称`, or `物体`
- Mass: `mass(kg)`, `mass(g)`, `mass`, `weight`, `重量`, or `质量`
- Dimensions: `x`, `y`, and `z`

The name cell may be left empty on consecutive rows; the previous non-empty
name is reused. Dimensions are interpreted as centimeters by default. Change
this with `--dimension-unit m|cm|mm`. The mass unit is inferred from the column
header first, with `--metadata-mass-unit auto|g|kg` as the fallback.

When metadata is unavailable, the script uses `--mass` (default `0.1 kg`) and
`--scale` (default `1.0`). Each axis is resolved independently, so a missing
dimension falls back only for that axis.

## Options

| Option | Description |
| --- | --- |
| `--assets-root PATH` | Asset root; defaults to `assets` |
| `--folders PATH ...` | Directories to scan |
| `--metadata-xlsx PATH` | Metadata workbook |
| `--output-root PATH` | Root directory for exported OBJ files |
| `--usd-output-root PATH` | Root for USD packages, preserving relative source directories |
| `--mass KG` | Fallback mass when metadata is unavailable |
| `--scale VALUE` | Fallback scale when dimension metadata is unavailable |
| `--force` | Replace an existing `Aligned.usd` |
| `--max-models N` | Maximum successful conversions; `0` means unlimited |
| `--extract-zips` | Recursively extract ZIP files before conversion |

`--scale-axis` remains available for backward compatibility. Scaling is always
computed independently for all three axes, and passing a value other than
`auto` produces a deprecation warning.

## Limitations

- Asset Converter is configured to merge meshes. If conversion does not
  produce exactly one mesh, processing stops for that asset to avoid creating
  an invalid collider.
- `Aligned.usd` and `Aligned.obj` form one conversion result. A failed reverse
  OBJ export marks the asset as failed rather than reporting partial success.
- A failed asset does not stop the batch. The final summary reports discovered,
  converted, skipped, and failed counts. The process exits nonzero if any asset
  fails to convert.
