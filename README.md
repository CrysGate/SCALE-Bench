# SCALE-Bench

[English](README.md) | [简体中文](README.zh-CN.md) | [Documentation](https://crysgate.github.io/SCALE-Bench/)

SCALE-Bench is an Isaac Lab benchmark for dual-arm tabletop manipulation and expert demonstration collection. It provides scene preview, CuRobo motion planning, task evaluation, and HDF5 data inspection and replay.

## Tasks

| Task | Goal |
| --- | --- |
| [Single-object pick and place](docs/tasks/single_object_pick_and_place.md) | Place a randomly positioned bottle upright in a fixed slot |
| [Sort nesting dolls](docs/tasks/sort_dolls_by_size.md) | Place five dolls in their slots, ordered by increasing height |
| [Largest-object pick and place](docs/tasks/largest_pick_and_place.md) | Place the tallest object in the target slot; the default assets are bubble tea cups |

Seeds and layout files reproduce task scenes. YAML files configure robots, cameras, and tasks.

## Getting Started

Complete the [environment and asset setup](https://crysgate.github.io/SCALE-Bench/getting-started/#environment) first (guide in Chinese). Assets are hosted in [ScaleBench-Data](https://modelscope.cn/datasets/CrysGate/ScaleBench-Data) and linked into the project root as `Assets`.

Preview the single-object task:

```bash
uv run python scripts/preview_scene.py --task single_object_pick_and_place
```

Collect one expert episode:

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz none
```

The HDF5 output contains joint states, actions, and evaluation results. Continue with [camera recording, data inspection, and replay](https://crysgate.github.io/SCALE-Bench/getting-started/#collect).

## Further Reading

- [Task guide](docs/tasks/index.md): task definitions and success conditions.
- [Asset catalog](docs/assets/index.md): asset specifications and grasp data.
- [Script guide](scripts/README.md): layout reproduction, batch collection, debugging, and video export.
- [OBJ-to-USD conversion](src/assets_gen/README.md): convert your own object assets.
- [Documentation standards](DOCUMENTATION.md): content selection, page responsibilities, and validation.

## License

[MIT License](LICENSE)
