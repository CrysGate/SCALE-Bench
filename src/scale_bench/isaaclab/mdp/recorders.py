"""Recorder terms for the SCALE-Bench dataset contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import torch
from isaaclab.managers import RecorderTerm

from scale_bench.isaaclab.runtime.streaming_recording import CameraTransfer
from scale_bench.runtime.recording import SEMANTIC_TEXT_BYTES

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv
    from isaaclab.managers import RecorderTermCfg


class PolicyObservationsRecorder(RecorderTerm):
    """Record the configured named policy observations before each action."""

    def record_pre_step(self):
        policy_observations = self._env.obs_buf["policy"]
        missing = [
            name
            for name in self.cfg.observation_names
            if name not in policy_observations
        ]
        if missing:
            raise RuntimeError(
                "configured recorder observations are missing at runtime: "
                + ", ".join(missing)
            )
        return "obs", {
            name: policy_observations[name]
            for name in self.cfg.observation_names
        }


class CameraObservationsRecorder(RecorderTerm):
    """Stream camera snapshots without adding image history to GPU episodes."""

    def __init__(self, cfg: RecorderTermCfg, env: ManagerBasedEnv) -> None:
        super().__init__(cfg, env)
        # Image shapes become available on the first recorded step.
        self._transfer: CameraTransfer | None = None
        self._active_env_ids: set[int] = set()

    def record_post_reset(self, env_ids: Sequence[int] | None):
        """Only a simulation reset starts recording again; None resets every slot."""
        self._active_env_ids.update(
            range(self._env.num_envs) if env_ids is None else map(int, env_ids)
        )
        return None, None

    def record_pre_step(self):
        if not self._active_env_ids:
            return None, None
        manager = self._env.recorder_manager
        images = {
            name: self._env.obs_buf["policy"][name]
            for name in self.cfg.observation_names
        }
        if self._transfer is None:
            handler = manager._dataset_file_handler
            failed_handler = manager._failed_episode_dataset_file_handler
            if failed_handler is not None:
                failed_handler.camera_source = handler
            self._transfer = CameraTransfer(
                images, handler,
                buffer_bytes=self.cfg.buffer_mib * 1024**2,
                compression=manager.cfg.dataset_compression,
            )
        env_ids = tuple(sorted(self._active_env_ids))
        for env_id in env_ids:
            # A camera-only episode still needs to participate in native export.
            manager.get_episode(env_id).data.setdefault("obs", {})
        self._transfer.append(images, env_ids)
        return None, None

    def flush(self) -> None:
        if self._transfer is not None:
            self._transfer.flush()

    def reset(self, env_ids: Sequence[int]) -> None:
        stopped_env_ids = self._active_env_ids.intersection(env_ids)
        if not stopped_env_ids:
            return
        if self._transfer is not None:
            self.flush()
            self._env.recorder_manager._dataset_file_handler.discard_cameras(tuple(stopped_env_ids))
        self._active_env_ids.difference_update(stopped_env_ids)

    def finish_transfers(self) -> None:
        """Finish DMA before file shutdown, including when a writer has failed."""
        if self._transfer is not None:
            self._transfer.close()

    def close(self, file_path: str) -> None:
        self.finish_transfers()


class ProcessedActionsRecorder(RecorderTerm):
    """Assemble processed action terms once in their action-manager order."""

    def record_post_step(self):
        manager = self._env.action_manager
        return "processed_actions", torch.cat(
            tuple(manager.get_term(name).processed_actions for name in manager.active_terms),
            dim=-1,
        )


class SemanticEventsRecorder(RecorderTerm):
    """Record UTF-8 skill, command, and subgoal text for every action frame."""

    def record_pre_step(self):
        events = self._env.step_semantics
        return "semantic", {
            field_name: _encode_semantic_text(
                tuple(
                    None if event is None else getattr(event, field_name)
                    for event in events
                ),
                device=self._env.device,
            )
            for field_name in ("skill", "command_label", "subgoal")
        }


def _encode_semantic_text(
    values: tuple[str | None, ...],
    *,
    device: str,
) -> torch.Tensor:
    """
    Encode semantic text, using a zero row when that field has no value.
    """

    encoded = torch.zeros(
        (len(values), SEMANTIC_TEXT_BYTES),
        dtype=torch.uint8,
        device=device,
    )
    for index, value in enumerate(values):
        if value is None:
            continue
        raw = value.encode("utf-8")
        encoded[index, : len(raw)] = torch.tensor(
            tuple(raw),
            dtype=torch.uint8,
            device=device,
        )
    return encoded


__all__ = [
    "CameraObservationsRecorder", "PolicyObservationsRecorder",
    "ProcessedActionsRecorder", "SemanticEventsRecorder",
]
