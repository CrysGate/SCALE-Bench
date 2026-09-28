"""Collect complete task experts into an HDF5 demonstration dataset."""

import argparse
import csv
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.cli.simulation import (
    add_simulation_arguments,
    nonnegative_int,
    positive_int,
    run_simulation,
)
from scale_bench.config.models.recording import RecordingConfig
from scale_bench.runtime.task_run import TaskRun

LOGGER = logging.getLogger("scale_bench.cli.demo_generation")


def _merge_recordings(workers: list[dict[str, Any]], dataset_path: Path) -> dict[str, Any]:
    """Publish one self-contained dataset after every recorder has closed its shard."""
    import h5py

    if any("result" not in worker for worker in workers):
        raise RuntimeError("a worker did not finish recording; keeping GPU shards for inspection")
    segments_path = dataset_path.with_suffix(".segments.jsonl")
    pending_dataset = dataset_path.with_suffix(".hdf5.partial")
    pending_segments = segments_path.with_suffix(".jsonl.partial")
    if len(workers) == 1:
        result = workers[0]["result"]
        with h5py.File(result["dataset_path"], "r") as source:
            episode_count = len(source["data"])
            total_samples = int(source["data"].attrs["total"])
        # Shards share the output filesystem; links retain them until publication succeeds.
        pending_dataset.hardlink_to(result["dataset_path"])
        pending_segments.hardlink_to(result["segments_path"])
    else:
        total_samples = 0
        with h5py.File(pending_dataset, "x") as merged, pending_segments.open("x") as segments:
            merged_data = merged.create_group("data")
            for rank, worker in enumerate(workers):
                result = worker["result"]
                with h5py.File(result["dataset_path"], "r") as source:
                    source_data = source["data"]
                    env_args = json.loads(source_data.attrs["env_args"])
                    # Workers can have different slot counts when episodes divide unevenly.
                    env_args["sim_args"].pop("num_envs")
                    if rank == 0:
                        merged.attrs.update(source.attrs)
                        merged_data.attrs.update(source_data.attrs)
                        common_env_args = env_args
                    elif (
                        source.attrs["format_version"] != merged.attrs["format_version"]
                        or env_args != common_env_args
                    ):
                        raise ValueError("GPU recordings have incompatible format or simulation settings")
                    for name, episode in source_data.items():
                        # HDF5 copies compressed datasets directly, including camera observations.
                        # Duplicate episode names raise instead of overwriting another worker's data.
                        source.copy(episode, merged_data, name=name)
                        total_samples += int(episode.attrs["num_samples"])
                with Path(result["segments_path"]).open() as source_segments:
                    shutil.copyfileobj(source_segments, segments)
            common_env_args["sim_args"]["num_envs"] = sum(worker["num_envs"] for worker in workers)
            merged_data.attrs["env_args"] = json.dumps(common_env_args)
            merged_data.attrs["total"] = total_samples
            episode_count = len(merged_data)

    pending_segments.replace(segments_path)
    pending_dataset.replace(dataset_path)
    # Sources remain recoverable until both final files have been written and closed.
    for worker in workers:
        result = worker["result"]
        Path(result["dataset_path"]).unlink()
        Path(result["segments_path"]).unlink()
        result.update(dataset_path=str(dataset_path), segments_path=str(segments_path))
    return {
        "dataset_path": str(dataset_path), "segments_path": str(segments_path),
        "recorded_episode_count": episode_count, "sample_count": total_samples,
    }


def _stop_workers(processes: list[subprocess.Popen[bytes]]) -> None:
    """Interrupt all worker process groups, then reap them within one grace period."""
    for process in processes:
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGINT)
    deadline = time.monotonic() + 15
    for process in processes:
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def _run_on_gpus(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Split a fixed seed range among isolated, persistent collection processes."""
    if args.device is not None or args.log_file is not None:
        parser.error("use --gpus to select devices; each worker saves its own logs automatically")
    try:
        inventory = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,uuid,name", "--format=csv,noheader"],
            text=True,
        )
        available = {
            row[0].strip(): {"index": row[0].strip(), "uuid": row[1].strip(), "name": row[2].strip()}
            for row in csv.reader(inventory.splitlines())
        }
    except (OSError, subprocess.CalledProcessError) as error:
        parser.error(f"cannot discover GPUs with nvidia-smi: {error}")
    selected = list(available) if args.gpus == "all" else args.gpus.split(",")
    if not selected or len(set(selected)) != len(selected) or any(
        index not in available for index in selected
    ):
        parser.error(f"--gpus must be 'all' or distinct nvidia-smi indices from {list(available)}")

    # Avoid starting a simulator on GPUs with no episodes assigned.
    selected = selected[:args.episodes]
    output_dir = args.record_output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = output_dir / f"{args.dataset_name}.hdf5"
    summary_path = output_dir / f"{args.dataset_name}.summary.json"
    for path in (
        dataset_path, dataset_path.with_suffix(".segments.jsonl"), summary_path,
        dataset_path.with_suffix(".hdf5.partial"),
        dataset_path.with_suffix(".segments.jsonl.partial"),
    ):
        if path.exists():
            parser.error(f"collection output already exists: {path}; choose another dataset name or output directory")
    worker_root = output_dir / f"{args.dataset_name}.logs"
    try:
        worker_root.mkdir(exist_ok=False)
    except FileExistsError:
        parser.error(f"collection logs already exist: {worker_root}; choose another dataset name or output directory")

    workers: list[dict[str, Any]] = []
    processes: list[subprocess.Popen[bytes]] = []
    recording: dict[str, Any] = {}
    per_gpu, remainder = divmod(args.episodes, len(selected))
    base_seed = args.base_seed
    for rank, index in enumerate(selected):
        episodes = per_gpu + (rank < remainder)
        worker_dir = worker_root / f"gpu-{index}"
        worker_dir.mkdir()
        workers.append({
            "gpu": available[index], "base_seed": base_seed,
            "episodes": episodes, "num_envs": min(args.num_envs, episodes),
            "output_dir": str(worker_dir), "status": "pending",
            "log_path": str(worker_dir / "worker.log"),
            "events_path": str(worker_dir / "events.jsonl"),
        })
        base_seed += episodes

    def save_summary(status: str) -> tuple[int, int]:
        completed = sum(worker.get("result", {}).get("episode_count", 0) for worker in workers)
        succeeded = sum(worker.get("result", {}).get("success_count", 0) for worker in workers)
        temporary_path = summary_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps({
            "status": status, "task": args.task, "base_seed": args.base_seed,
            "episode_count": args.episodes, "completed_count": completed,
            "success_count": succeeded, "success_rate": succeeded / args.episodes,
            "workers": workers, **recording,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(summary_path)
        return completed, succeeded

    def interrupt_workers(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    previous_handler = signal.signal(signal.SIGTERM, interrupt_workers)
    status = "failed"
    exit_code = 1
    try:
        save_summary("starting")
        for worker in workers:
            # Each fresh interpreter receives its GPU mask before importing Isaac or Torch.
            environment = os.environ.copy()
            environment["CUDA_VISIBLE_DEVICES"] = worker["gpu"]["uuid"]
            command = [
                sys.executable, "-u", str(Path(__file__).resolve()), *sys.argv[1:],
                "--_gpu-worker", "--device", "cuda:0",
                "--episodes", str(worker["episodes"]),
                "--base-seed", str(worker["base_seed"]),
                "--num-envs", str(worker["num_envs"]),
                "--record-output", worker["output_dir"],
                "--log-file", worker["events_path"],
            ]
            with Path(worker["log_path"]).open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command, env=environment, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            processes.append(process)
            worker.update(pid=process.pid, status="running")
            print(
                f"GPU {worker['gpu']['index']} ({worker['gpu']['name']}): "
                f"seeds={worker['base_seed']}..{worker['base_seed'] + worker['episodes'] - 1} "
                f"num_envs={worker['num_envs']} log={worker['log_path']}",
                flush=True,
            )
        save_summary("running")
        pending = set(range(len(processes)))
        while pending:
            for rank in tuple(pending):
                return_code = processes[rank].poll()
                if return_code is None:  # This worker is still collecting its assigned episodes.
                    continue
                pending.remove(rank)
                worker = workers[rank]
                events_path = Path(worker["events_path"])
                if events_path.exists():
                    with events_path.open(encoding="utf-8") as events:
                        for line in events:
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue  # A terminated worker can leave its last log line incomplete.
                            if event.get("event") == "SUMMARY":
                                worker["result"] = event
                result = worker.get("result", {})
                completed = (
                    return_code == 0
                    and result.get("episode_count") == worker["episodes"]
                )
                worker.update(exit_code=return_code, status="completed" if completed else "failed")
                print(
                    f"GPU {worker['gpu']['index']}: {worker['status']} "
                    f"success={result.get('success_count', 0)}/{worker['episodes']} "
                    f"exit_code={return_code} log={worker['log_path']}",
                    flush=True,
                )
                save_summary("running")
            if pending:
                time.sleep(0.2)
        save_summary("merging")
        print("Combining GPU recordings...", flush=True)
        recording.update(_merge_recordings(workers, dataset_path))
        print(f"Dataset: {recording['dataset_path']}", flush=True)
        exit_code = int(any(worker["status"] != "completed" for worker in workers))
        status = "completed" if exit_code == 0 else "failed"
    except KeyboardInterrupt:
        status, exit_code = "interrupted", 130
        print("Stopping GPU workers...", flush=True)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Collection failed: {error}", file=sys.stderr)
    finally:
        # Keep repeated interrupts from abandoning the remaining workers during cleanup.
        previous_int_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            _stop_workers(processes)
            for worker, process in zip(workers, processes):
                if worker["status"] == "running":
                    worker.update(status="interrupted", exit_code=process.returncode)
            completed, succeeded = save_summary(status)
        finally:
            signal.signal(signal.SIGINT, previous_int_handler)
            signal.signal(signal.SIGTERM, previous_handler)
    print(
        f"Collection {status}: episodes={completed}/{args.episodes} "
        f"success={succeeded}/{args.episodes} summary={summary_path}",
        flush=True,
    )
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    add_simulation_arguments(parser, PROJECT_ROOT)
    # Device and event-log paths are internal worker settings for this entry point.
    for action in parser._actions:
        if action.dest in {"device", "log_file"}:
            action.help = argparse.SUPPRESS
    parser.set_defaults(enable_cameras=False)
    parser.add_argument("--num-envs", type=positive_int, default=1, help="Parallel environments per GPU.")
    parser.add_argument("--episodes", type=positive_int, default=1, help="Total episodes across all selected GPUs.")
    parser.add_argument("--base-seed", type=nonnegative_int, default=100)
    parser.add_argument("--max-steps", type=positive_int, default=1200)
    parser.add_argument(
        "--gpus", default="0",
        help="Use 'all' or comma-separated nvidia-smi GPU indices (e.g. 0,1). "
        "Defaults to GPU 0. One collection process is started per GPU. "
        "Episodes are divided across GPUs; num-envs is per GPU.",
    )
    parser.add_argument("--_gpu-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--record-output", type=Path, default=Path("outputs/demonstrations")
    )
    parser.add_argument("--dataset-name", default="demo_generation")
    parser.add_argument(
        "--record-camera-observations",
        action="store_true",
        help="Include wrist and overhead RGB-D; omit for joint/action data only.",
    )
    args = parser.parse_args()
    args.enable_cameras = args.enable_cameras or args.record_camera_observations
    recording = RecordingConfig(
        output_dir=args.record_output.resolve(),
        dataset_name=args.dataset_name,
        record_camera_observations=args.record_camera_observations,
    )
    if not args._gpu_worker:
        return _run_on_gpus(args, parser)

    def execute(run: TaskRun) -> int:
        # Isaac runtime modules require an initialized application.
        from scale_bench.isaaclab.runtime.expert_collection import collect_expert_data

        specs = run.episode_specs(
            base_seed=args.base_seed,
            episodes=args.episodes,
            max_steps=args.max_steps,
        )
        result = collect_expert_data(
            run, specs, recording=recording, num_envs=args.num_envs,
        )
        episode_count = len(result.benchmark.episodes)
        success_count = result.success_count
        LOGGER.info(
            "success=%d/%d dataset=%s segments=%s",
            success_count,
            episode_count,
            result.dataset_path,
            result.segments_path,
            extra={
                "event": "SUMMARY",
                "event_fields": {
                    "task": run.task.task_id,
                    "episode_count": episode_count,
                    "success_count": success_count,
                    "success_rate": success_count / episode_count,
                    "batch_count": result.benchmark.batch_count,
                    "dataset_path": str(result.dataset_path),
                    "segments_path": str(result.segments_path),
                },
            },
        )
        return 0

    return run_simulation(args, PROJECT_ROOT, execute)


if __name__ == "__main__":
    raise SystemExit(main())
