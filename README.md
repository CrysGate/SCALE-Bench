# SCALE-Bench

[English](README.md) | [简体中文](README.zh-CN.md) | [Documentation](https://crysgate.github.io/SCALE-Bench/)

SCALE-Bench is a configuration-driven Isaac Lab project for dual-arm manipulation. Robot, camera, scene, task, simulation, and environment settings live in validated YAML files. The repository provides scene preview, task evaluation, expert-data generation, policy rollout, and episode replay entry points.

Three tasks are currently implemented:

- `sort_dolls_by_size`: arrange five nesting dolls in size order at fixed slots.
- `single_object_pick_and_place`: place a randomly positioned bottle upright at a fixed slot.
- `largest_pick_and_place`: place the largest object in the target slot; the default configuration uses bubble tea cups.

The tasks support deterministic seeds, layout import/export, and final-state evaluation. The expert path supports CuRobo planning with either live AnyGrasp detections or an offline grasp catalog from the robot configuration.

## Environment

- Python 3.12
- Isaac Sim 6.0.1
- Isaac Lab `release/3.0.0-beta2` (verified commit `6a7acb0`)
- CuRobo (verified commit `8e734f3`)
- PyTorch 2.10 for CUDA 12.8
- [`uv`](https://docs.astral.sh/uv/)

`pyproject.toml` expects local checkouts at `third_parties/IsaacLab` and `third_parties/curobo`:

```bash
mkdir -p third_parties
git clone --branch release/3.0.0-beta2 \
  https://github.com/isaac-sim/IsaacLab.git third_parties/IsaacLab
git clone https://github.com/NVlabs/curobo.git third_parties/curobo
git -C third_parties/IsaacLab checkout 6a7acb0
git -C third_parties/curobo checkout 8e734f3

uv sync --frozen
```

The default configuration also requires an `Assets/` bundle that is not stored in Git. It contains the Piper USD/URDF, room, materials, camera stand, HDR, nesting dolls, and bottle. Treat the paths in `configs/` as the source of truth; configuration errors identify the missing field and path.

## Quick Start

Preview a task scene:

```bash
uv run python scripts/preview_scene.py --task sort_dolls_by_size
```

Run a bounded headless check with a fixed seed:

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place \
  --seed 42 \
  --viz none \
  --max-steps 2
```

Export and restore the same layout:

```bash
uv run python scripts/preview_scene.py \
  --task sort_dolls_by_size \
  --seed 42 \
  --export-layout layouts/sort_dolls_by_size/42.json

uv run python scripts/preview_scene.py \
  --task sort_dolls_by_size \
  --layout layouts/sort_dolls_by_size/42.json
```

Run the complete expert path:

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --robot-config configs/robots/piper.yml \
  --num-envs 1 \
  --episodes 1 \
  --max-steps 1200 \
  --record-output outputs/demonstrations \
  --viz none
```

Grasp candidates are read from `grasps-<robot name>.yaml` beside each object USD, including its TCP definition and approach distance.

## Entry Points

| Entry point | Purpose |
|---|---|
| `scripts/preview_scene.py` | Preview scenes, inspect layouts, and run bounded checks. |
| `scripts/run_policy_rollout.py` | Exercise policy rollout, fixed-batch scheduling, and recording. |
| `scripts/run_demo_generation.py` | Collect complete task experts into HDF5 datasets. |
| `scripts/run_skill_debug.py` | Run one skill and inspect CuRobo planning. |
| `scripts/replay_episode.py` | Restore HDF5 state, replay actions, and re-evaluate. |
| `scripts/view_hdf5.py` | Inspect recorded episodes, cameras, and state in a browser. |
| `scripts/export_hdf5_camera_videos.py` | Export RGB and depth videos. |
| `scripts/generate_curobo_robot_config.py` | Generate a CuRobo collision configuration from a robot configuration. |

See [scripts/README.md](scripts/README.md) for command examples. Run scripts through `uv run` from the repository root, and use each script's `--help` as the authoritative option reference.

## Configuration Boundaries

- `configs/robots/`: joints, TCP, actuators, gripper, camera mount, and URDF.
- `configs/cameras/`: image dimensions, outputs, intrinsics, and clipping range.
- `configs/scene/`: static assets, robot mounts, cameras, and lighting.
- `configs/tasks/`: task assets, layout constraints, target slots, and success thresholds.
- `configs/sim/`: physics timing, gravity, rendering, and justified PhysX overrides.
- `configs/envs/`: environment count, spacing, control rate, cloning, and reset behavior.

Configuration models reject unknown fields. Configuration references resolve relative to the containing file; asset references resolve relative to `asset_root` when it is supplied. Distances use metres and quaternions use `xyzw` order.

## Runtime

`scale_bench.api.create_env()` is the public environment entry point. Start Isaac Sim first, then pass loaded configurations, a concrete Task, and either `base_seed` or `layouts`. `ScaleBenchEnv` owns the simulation, scene, and manager lifecycle.

Episode execution has two paths:

- `PolicyRolloutRunner` consumes policy observations and produces joint actions.
- `DemoGenerationRunner` expands a task expert into skill requests executed by a planner and command executor.

They share scheduling, evaluation, termination, and recording. HDF5 output contains the initial state, actions, evaluation result, and termination reason; `replay_episode.py` checks it against a fresh run.

## Validation

Validate changes through the corresponding real execution path. At minimum, load the configuration and run a bounded environment:

```bash
uv run python -c \
  'from scale_bench.config.loader import load_config; from scale_bench.config.models.environment import EnvironmentConfig; print(load_config("configs/envs/default.yml", EnvironmentConfig))'

uv run python scripts/preview_scene.py \
  --task sort_dolls_by_size \
  --viz none \
  --max-steps 2
```

Planner, grasping, or recorder changes should also run the matching demo-generation and replay commands.

## Documentation

- [OBJ-to-USD conversion](src/assets_gen/README.md)

## License

[MIT License](LICENSE)
