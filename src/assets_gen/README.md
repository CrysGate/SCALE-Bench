# OBJ-to-USD Conversion

[简体中文](README.zh-CN.md)

Convert your OBJ assets into USD files with collision geometry, apply dimensions and mass from metadata, and export aligned OBJ files. Complete the [project environment setup](https://crysgate.github.io/SCALE-Bench/getting-started/#environment) before running the converter.

## Prepare the Input

This example uses `assets/vase/300g/model.obj` and its material files. Put dimensions and mass in the first worksheet of `assets/sample.xlsx`, with headers in the first row:

| name | mass(kg) | x | y | z |
| --- | --- | --- | --- | --- |
| vase | 0.3 | 9 | 9 | 13.5 |

The `name` matches the object directory. For multiple mass variants of the same object, use directory names such as `300g` to distinguish them. Dimensions default to centimeters; use `--dimension-unit m` or `--dimension-unit mm` for other units. Use `mass(kg)` or `mass(g)` as the mass column header.

## Convert

```bash
uv run python src/assets_gen/convert_obj_to_usd.py \
  --assets-root assets \
  --folders assets/vase \
  --metadata-xlsx assets/sample.xlsx \
  --output-root converted-obj \
  --usd-output-root converted-usd
```

The corresponding output is:

```text
converted-usd/vase/300g/Aligned.usd
converted-usd/vase/300g/metadata.json
converted-usd/vase/300g/textures/
converted-obj/vase/300g/Aligned.obj
```

`metadata.json` records the final dimensions in meters, mass in kilograms, and friction coefficient. Keep the metadata and textures with the USD when moving an asset.

## Other Uses

- **No matching metadata:** use `--mass` for mass in kilograms and `--scale` for the scale factor; defaults are `0.1` and `1.0`. If a single dimension is missing, only that axis uses the fallback scale.
- **Try a small batch:** add `--max-models 1` to stop after one successful conversion.
- **Regenerate an asset:** existing USD files are skipped unless `--force` is set. Omitting `--usd-output-root` writes USD files beside the source OBJ.

Check the converted, skipped, and failed counts at the end. A failed model does not stop subsequent conversions; any model conversion failure produces a nonzero exit code.
