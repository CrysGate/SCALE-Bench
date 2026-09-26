"""Evaluate an XPolicyLab joint policy in SCALE-Bench and save episode results."""

import argparse
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.cli.simulation import (
    add_simulation_arguments,
    nonnegative_int,
    positive_int,
    run_simulation,
)
from scale_bench.config.loader import load_config
from scale_bench.config.models.policy import XPolicyLabConfig
from scale_bench.config.models.recording import RecordingConfig
from scale_bench.runtime.task_run import TaskRun

LOGGER = logging.getLogger("scale_bench.cli.policy_evaluation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_simulation_arguments(parser, PROJECT_ROOT)
    parser.add_argument(
        "--policy-config", type=Path,
        default=PROJECT_ROOT / "configs/policies/xpolicylab.yml",
    )
    parser.add_argument("--server-url", help="Override the endpoint for a remote policy host.")
    parser.add_argument(
        "--inference-mode", choices=("single", "batch"),
        help="Override RPC mode for a model supporting batch inference.",
    )
    parser.add_argument("--num-envs", type=positive_int, default=1)
    parser.add_argument("--episodes", type=positive_int, default=1)
    parser.add_argument("--base-seed", type=nonnegative_int, default=100)
    parser.add_argument("--max-steps", type=positive_int, default=1200)
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="New run directory; existing directories are never overwritten.",
    )
    parser.add_argument(
        "--record", action="store_true",
        help="Also save joint states/actions to episodes.hdf5.",
    )
    parser.add_argument(
        "--record-camera-observations", action="store_true",
        help="Also record RGB-D in HDF5; implies --record.",
    )
    args = parser.parse_args()
    policy_data = load_config(args.policy_config, XPolicyLabConfig).model_dump()
    # Omitted endpoint/mode overrides use the selected policy profile.
    if args.server_url is not None:
        policy_data["server_url"] = args.server_url
    if args.inference_mode is not None:
        policy_data["inference_mode"] = args.inference_mode
    config = XPolicyLabConfig.model_validate(policy_data)
    if config.inference_mode == "single" and args.num_envs != 1:
        parser.error("--num-envs > 1 requires --inference-mode batch and a batch-capable model")
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    evaluation_id = uuid4().hex
    report = {
        "evaluation_id": evaluation_id,
        "status": "running",
        "policy": config.model_dump(),
        "task": args.task,
        "num_envs": args.num_envs,
        "requested_episodes": args.episodes,
        "base_seed": args.base_seed,
        "max_steps": args.max_steps,
    }
    report_path = args.output_dir / "results.json"

    def save_report() -> None:
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    def execute(run: TaskRun) -> int:
        try:
            return evaluate(run)
        except BaseException as error:
            report.update(
                status="cancelled" if isinstance(error, KeyboardInterrupt) else "error",
                error=str(error),
            )
            raise
        finally:
            # Isaac can terminate the process during app.close(), so persist
            # both successful results and callback errors before returning.
            save_report()

    def evaluate(run: TaskRun) -> int:
        from scale_bench.isaaclab.runtime.command_adapter import build_command_action_layout
        from scale_bench.runtime.policy import PolicyRolloutRunner
        from scale_bench.runtime.policy_client import PolicyClient
        from scale_bench.runtime.scheduler import BenchmarkScheduler
        from scale_bench.runtime.xpolicylab import XPolicyLabController

        specs = run.episode_specs(
            base_seed=args.base_seed, episodes=args.episodes, max_steps=args.max_steps,
        )
        report["environment"] = {
            "robot": run.robot.model_dump(mode="json"),
            "scene": run.scene.model_dump(mode="json"),
            "simulation": run.simulation.model_dump(mode="json"),
            "environment": run.environment.model_dump(mode="json"),
            "task": run.task.config.model_dump(mode="json"),
            "instruction": run.task.instruction,
        }
        # None selects metrics-only evaluation; recording is explicitly opt-in.
        recording = (
            RecordingConfig(
                output_dir=args.output_dir, dataset_name="episodes",
                record_camera_observations=args.record_camera_observations,
            )
            if args.record or args.record_camera_observations else None
        )
        with PolicyClient(config=config, evaluation_id=evaluation_id) as client:
            report["server"] = client.server_info
            with run.open_environment(specs, num_envs=args.num_envs, recording=recording) as env:
                layout = build_command_action_layout(
                    env, left_robot_config=run.robot, right_robot_config=run.robot,
                )
                controller = XPolicyLabController(
                    client=client, config=config, robot=run.robot, layout=layout,
                    num_envs=env.num_envs, control_dt_s=env.step_dt,
                )
                result = BenchmarkScheduler(specs).run(PolicyRolloutRunner(env, controller))
                report["inference_calls"] = controller.inference_calls
        episodes = [
            {
                "episode_id": item.spec.episode_id,
                "seed": item.spec.seed,
                "layout": item.spec.layout.model_dump(mode="json"),
                "success": item.success,
                "progress": item.evaluation.progress,
                "metrics": dict(item.evaluation.metrics),
                "failure_reason": item.evaluation.failure_reason,
                "termination": item.termination.reason.value,
                "termination_message": item.termination.message,
                "steps": item.steps,
            }
            for item in result.episodes.values()
        ]
        success_count = sum(item["success"] for item in episodes)
        report.update(
            status="completed", episodes=episodes, batch_count=result.batch_count,
            success_count=success_count, success_rate=success_count / len(episodes),
        )
        LOGGER.info("success=%d/%d results=%s", success_count, len(episodes), report_path)
        # Task failures are benchmark outcomes, not process/runtime failures.
        return 0

    save_report()
    try:
        exit_code = run_simulation(args, PROJECT_ROOT, execute)
        if exit_code != 0 and report["status"] == "running":
            report.update(status="error", error="Evaluation failed; see the client/server logs.")
        return exit_code
    except Exception as error:
        report.update(status="error", error=str(error))
        raise
    except KeyboardInterrupt:
        report.update(status="cancelled")
        raise
    finally:
        save_report()


if __name__ == "__main__":
    raise SystemExit(main())
