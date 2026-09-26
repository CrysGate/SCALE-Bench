"""Adapt public policy observations and absolute joint actions to XPolicyLab."""

from collections import deque
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import torch
from torch import Tensor

from scale_bench.config.models.policy import XPolicyLabConfig
from scale_bench.config.models.robot import RobotConfig
from scale_bench.skills.executor import CommandActionLayout

from .policy import EpisodeContext, PolicyObservation
from .policy_client import PolicyClient


class XPolicyLabController:
    """One server model owns a fixed batch; reset only between full batches.

    Gripper state/actions contain command-joint positions in the robot's native
    units, excluding mimic joints. No normalization or delta conversion is
    applied. Models must be trained/configured for this action contract.
    """

    def __init__(
        self,
        *,
        client: PolicyClient,
        config: XPolicyLabConfig,
        robot: RobotConfig,
        layout: CommandActionLayout,
        num_envs: int,
        control_dt_s: float,
    ) -> None:
        if config.inference_mode == "single" and num_envs != 1:
            raise ValueError("single inference requires --num-envs 1")
        self._client = client
        self._config = config
        self._layout = layout
        self._num_envs = num_envs
        self._frequency = 1.0 / control_dt_s
        self._gripper_indices = tuple(
            robot.gripper.joint_names.index(name)
            for name in robot.gripper.command_joint_names
        )
        self._action_slices = {
            "left_arm_joint_state": slice(*layout.left_arm),
            "left_ee_joint_state": slice(*layout.left_gripper),
            "right_arm_joint_state": slice(*layout.right_arm),
            "right_ee_joint_state": slice(*layout.right_gripper),
        }
        self._contexts: dict[int, EpisodeContext] = {}
        self._pending: dict[int, deque[Tensor]] = {}
        self.inference_calls = 0

    def reset(self, env_ids: Tensor, contexts: Sequence[EpisodeContext]) -> None:
        ids = env_ids.detach().cpu().tolist()
        if ids != [context.env_id for context in contexts]:
            raise ValueError("episode contexts must match the reset environment IDs")
        self._contexts = {context.env_id: context for context in contexts}
        self._pending = {env_id: deque() for env_id in ids}
        self._client.reset(",".join(context.spec.episode_id for context in contexts))

    def act(self, observation: PolicyObservation, active_mask: Tensor) -> Tensor:
        env_ids = torch.nonzero(active_mask, as_tuple=False).flatten().cpu().tolist()
        action = observation["left_arm_joint_pos"].new_zeros(
            (self._num_envs, self._layout.action_dim)
        )
        if not env_ids:
            return action
        observations = [self._observation(observation, env_id) for env_id in env_ids]
        # XPolicyLab adapters with observation history need every control frame,
        # including frames between two get_action calls within an action chunk.
        if self._config.inference_mode == "batch":
            self._client.call("update_obs_batch", {"obs": observations})
        else:
            self._client.call("update_obs", {"obs": observations[0]})

        requesting_ids = [env_id for env_id in env_ids if not self._pending[env_id]]
        if requesting_ids:
            if self._config.inference_mode == "batch":
                chunks = self._client.call("get_action_batch", {"obs": requesting_ids})
            else:
                chunks = [self._client.call("get_action", {})]
            self.inference_calls += 1
            if not isinstance(chunks, list) or len(chunks) != len(requesting_ids):
                raise ValueError("policy must return one action chunk per requested env_idx")
            for env_id, chunk in zip(requesting_ids, chunks, strict=True):
                if not isinstance(chunk, list) or not chunk:
                    raise ValueError(f"env_idx={env_id}: policy returned an empty/invalid chunk")
                self._pending[env_id].extend(
                    self._action_row(item, action)
                    for item in chunk[: self._config.action_steps]
                )
        for env_id in env_ids:
            action[env_id] = self._pending[env_id].popleft()
        return action

    def _observation(self, observation: PolicyObservation, env_id: int) -> dict[str, Any]:
        state = {}
        for side in ("left", "right"):
            state[f"{side}_arm_joint_state"] = (
                observation[f"{side}_arm_joint_pos"][env_id].detach().cpu().numpy()
            )
            state[f"{side}_ee_joint_state"] = (
                observation[f"{side}_gripper_joint_pos"][env_id, self._gripper_indices]
                .detach().cpu().numpy()
            )
        vision = {}
        for camera_name, source in self._config.camera_map.items():
            rgb = observation[f"{source}_rgb"][env_id].detach().cpu().numpy()
            if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[-1] not in (3, 4):
                raise ValueError(f"{source}_rgb must be an HWC uint8 RGB/RGBA image")
            color = np.ascontiguousarray(rgb[..., :3])
            camera = {"color": color, "shape": color.shape}
            if self._config.send_depth:
                camera["depth"] = (
                    observation[f"{source}_depth"][env_id].detach().cpu().numpy()
                )
            vision[camera_name] = camera
        return {
            "env_idx": env_id,
            "instruction": self._contexts[env_id].instruction,
            "additional_info": {"frequency": self._frequency},
            "vision": vision,
            "state": state,
        }

    def _action_row(self, item: Mapping[str, Any], action: Tensor) -> Tensor:
        if not isinstance(item, Mapping) or set(item) != set(self._action_slices):
            raise ValueError(
                "joint action requires exactly these fields: "
                + ", ".join(self._action_slices)
            )
        row = action.new_empty(self._layout.action_dim)
        for key, indices in self._action_slices.items():
            values = np.asarray(item[key])
            expected = (indices.stop - indices.start,)
            if values.shape != expected or values.dtype.kind not in "fiu":
                raise ValueError(f"{key} must be a numeric vector of shape {expected}")
            # The upstream decoder exposes read-only NumPy views; copy them.
            row[indices] = torch.tensor(values, dtype=action.dtype, device=action.device)
        # PolicyRolloutRunner classifies NaN/Inf as INVALID_ACTION per episode.
        return row
