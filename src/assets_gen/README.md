# OBJ to USD Asset Conversion

[简体中文](README.zh-CN.md)

`convert_obj_to_usd.py` uses Isaac Sim's Asset Converter to process OBJ assets
in batches and generate standardized USD files for rigid-body simulation. It
can also read mass and dimensions from XLSX metadata, scale each `x/y/z` axis
independently, and export the aligned geometry as OBJ files.

## Requirements

Requires Isaac Sim 6.0.1 and the project dependencies.

```bash
uv run python src/assets_gen/convert_obj_to_usd.py \
  --assets-root ./assets \
  --folders ./assets/vase ./assets/mug \
  --metadata-xlsx ./assets/sample.xlsx \
  --output-root ./converted-obj \
  --usd-output-root ./converted-usd
```

By default, the script scans `<assets-root>/vase`, reads
`<assets-root>/sample.xlsx`, and exports OBJ files to
`<assets-root>/../rigid assets`.

## Output

The script converts each OBJ to an aligned rigid-body USD with collision
geometry, exports an aligned OBJ, and writes `metadata.json` with the final
size, mass, and friction. Output paths preserve the layout under `--assets-root`:

```text
assets/vase/001/model.obj
converted-usd/vase/001/Aligned.usd
converted-usd/vase/001/metadata.json
converted-usd/vase/001/textures/
converted-obj/vase/001/Aligned.obj
```

Without `--usd-output-root`, USD output stays beside the source OBJ. Existing
assets are skipped unless `--force` is set; failed conversions leave previous
outputs intact.

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
- A failed asset does not stop the batch; the process exits nonzero if any
  asset fails to convert.
