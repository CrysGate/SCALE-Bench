"""Task selection options shared by all simulation entry points."""

import argparse
from pathlib import Path


def add_task_overrides(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--task-config", type=Path,
        help="Task variant YAML; omit to use configs/tasks/<task>/default.yml.",
    )
    parser.add_argument(
        "--object-set", type=Path,
        help="Object-set YAML; omit to use the task variant's collection.",
    )
