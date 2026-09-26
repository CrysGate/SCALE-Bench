"""Export robot dimensions and batch size for XPolicyLab's model adapters."""

import argparse
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.config.models.robot import RobotConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot-config", type=Path, required=True)
    parser.add_argument("--env-cfg-type", required=True)
    parser.add_argument("--num-envs", type=int, required=True)
    args = parser.parse_args()
    if args.num_envs <= 0:
        parser.error("--num-envs must be positive")
    if not args.env_cfg_type or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for char in args.env_cfg_type
    ):
        parser.error("--env-cfg-type must contain only letters, digits, '_' or '-'")
    # Metadata export also runs on the policy host, where USD assets and Isaac
    # need not be installed. Validate the profile without resolving asset paths.
    robot = RobotConfig.model_validate(yaml.safe_load(args.robot_config.read_text()))
    root = PROJECT_ROOT / "env_cfg"
    robot_dir = root / "robot"
    sim_dir = root / "sim"
    robot_dir.mkdir(parents=True, exist_ok=True)
    sim_dir.mkdir(parents=True, exist_ok=True)
    info_path = robot_dir / "_robot_info.json"
    robot_info = json.loads(info_path.read_text()) if info_path.exists() else {}
    robot_info[args.env_cfg_type] = {
        "arm_dim": [len(robot.kinematics.arm_joint_names)] * 2,
        "ee_dim": [len(robot.gripper.command_joint_names)] * 2,
    }
    info_path.write_text(json.dumps(robot_info, indent=2) + "\n")
    (sim_dir / f"{args.env_cfg_type}.yml").write_text(
        yaml.safe_dump({"scene": {"num_envs": args.num_envs}})
    )
    config_path = root / f"{args.env_cfg_type}.yml"
    config_path.write_text(yaml.safe_dump({
        "config": {"robot": args.env_cfg_type, "sim": args.env_cfg_type},
    }))
    print(f"Prepared {config_path}: {robot_info[args.env_cfg_type]}, num_envs={args.num_envs}")


if __name__ == "__main__":
    main()
