"""Inspect AnyGrasp candidates from a real task camera frame."""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.cli.simulation import (
    add_simulation_arguments,
    nonnegative_int,
    run_simulation,
)
from scale_bench.runtime.task_run import TaskRun


def view_after_collection() -> int:
    """Keep Isaac and Open3D native libraries in separate processes."""
    arguments = [argument for argument in sys.argv[1:] if argument != "--open3d"]
    with tempfile.TemporaryDirectory(prefix="scale-bench-anygrasp-") as directory:
        bundle = Path(directory) / "frame.npz"
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                *arguments,
                "--open3d-bundle",
                str(bundle),
            ],
            check=True,
        )
        environment = os.environ.copy()
        environment.pop("WAYLAND_DISPLAY", None)
        environment.update(XDG_SESSION_TYPE="x11", GDK_BACKEND="x11")
        return subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts/view_anygrasp_open3d.py"),
                str(bundle),
            ],
            env=environment,
            check=False,
        ).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_simulation_arguments(parser, PROJECT_ROOT)
    parser.set_defaults(grasp_source="anygrasp")
    parser.add_argument("--seed", type=nonnegative_int, default=100)
    parser.add_argument(
        "--object-name", help="Omit to inspect the task's first target object."
    )
    parser.add_argument(
        "--grasp-arm", choices=("auto", "left", "right"), default="auto"
    )
    parser.add_argument(
        "--diagnostics-output",
        type=Path,
        help="Save JSON evidence; omit for console inspection.",
    )
    parser.add_argument(
        "--open3d",
        action="store_true",
        help="View RGB-D and grasps after Isaac closes.",
    )
    parser.add_argument("--open3d-bundle", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.grasp_source != "anygrasp":
        parser.error("grasp diagnostics requires --grasp-source anygrasp")
    if args.open3d:
        return view_after_collection()

    def execute(run: TaskRun) -> int:
        from scale_bench.isaaclab.runtime.anygrasp_diagnostics import (
            AnyGraspOpen3DFrame,
        )
        from scale_bench.isaaclab.runtime.grasp_diagnostics import (
            collect_grasp_diagnostics,
        )

        object_name = args.object_name or run.task.target_object_order[0]
        if object_name not in run.task.metadata:
            raise ValueError(f"unknown --object-name: {object_name!r}")
        spec = run.episode_specs(base_seed=args.seed, episodes=1, max_steps=1)[0]
        diagnostics = collect_grasp_diagnostics(run, spec, object_name, args.grasp_arm)
        if args.diagnostics_output is not None:
            diagnostics.write_json(args.diagnostics_output.resolve())
        if args.open3d_bundle is not None:
            AnyGraspOpen3DFrame.from_diagnostics(diagnostics).write(args.open3d_bundle)
        return 0

    return run_simulation(args, PROJECT_ROOT, execute)


if __name__ == "__main__":
    raise SystemExit(main())
