"""Bounded camera transfers and serialized, incremental HDF5 writes."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

import h5py
import torch
from isaaclab.utils.datasets import EpisodeData, HDF5DatasetFileHandler

LOGGER = logging.getLogger(__name__)


def _completed() -> Future:
    future = Future()
    future.set_result(None)
    return future


class EpisodeHDF5DatasetFileHandler(HDF5DatasetFileHandler):
    """Publish complete episodes with frame counts independent of action recording."""

    def write_episode(
        self, episode: EpisodeData, demo_id: str | int | None = None,
        dataset_compression: bool = True,
    ) -> None:
        """Preserve native explicit string/integer IDs and default sequential IDs."""
        self._raise_if_not_initialized()
        if episode.is_empty():
            return
        group_name = f"demo_{self._demo_count if demo_id is None else demo_id}"
        if group_name in self._hdf5_data_group:
            raise ValueError(f"Episode group '{group_name}' already exists in the dataset")
        pending_path = f"_pending/{group_name}"
        group = self._hdf5_file_stream.create_group(pending_path)
        try:
            _write_episode_data(group, episode.data, dataset_compression)
            self._write_cameras(group, episode)
            num_samples = _episode_frame_count(group)
            group.attrs["num_samples"] = num_samples
            if episode.seed is not None:
                group.attrs["seed"] = episode.seed
            if episode.success is not None:
                group.attrs["success"] = episode.success
            self._hdf5_file_stream.move(pending_path, f"/data/{group_name}")
            self._hdf5_data_group.attrs["total"] += num_samples
            if demo_id is None:
                self._demo_count += 1
        finally:
            if pending_path in self._hdf5_file_stream:
                del self._hdf5_file_stream[pending_path]

    def _write_cameras(self, group: h5py.Group, episode: EpisodeData) -> None:
        """The streaming subclass attaches cameras held outside EpisodeData."""

    def close(self) -> None:
        if self._hdf5_file_stream is not None:
            if self._hdf5_file_stream.mode != "r" and "_pending" in self._hdf5_file_stream:
                del self._hdf5_file_stream["_pending"]
            super().close()


def _write_episode_data(group: h5py.Group, data: dict, compression: bool) -> None:
    options = {"compression": "gzip", "compression_opts": 2} if compression else {}
    for name, value in data.items():
        if isinstance(value, dict):
            _write_episode_data(group.create_group(name), value, compression)
        else:
            group.create_dataset(name, data=value.cpu().numpy(), **options)


def _episode_frame_count(group: h5py.Group) -> int:
    lengths: set[int] = set()

    def collect_length(name: str, dataset: h5py.Dataset | h5py.Group) -> None:
        # HDF5 visititems calls this for both groups and leaf datasets.
        # Initial state and termination fields are episode-level, not frame series.
        if name.split("/", 1)[0] not in {"initial_state", "termination"}:
            if isinstance(dataset, h5py.Dataset):
                lengths.add(len(dataset))

    group.visititems(collect_length)
    if "termination/step_count" in group:
        lengths.add(int(group["termination/step_count"][0]))
    if len(lengths) > 1:
        raise ValueError(f"episode frame counts do not match: {sorted(lengths)}")
    return next(iter(lengths), 0)


class StreamingHDF5DatasetFileHandler(EpisodeHDF5DatasetFileHandler):
    """Stage cameras outside /data until the native recorder commits an episode.

    One executor owns writes for each file. The failed-episode handler reads
    cameras from the primary handler after its pending writes have completed.
    """

    def __init__(self) -> None:
        super().__init__()
        self.camera_source = self
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="camera-hdf5")
        self._last_write = _completed()
        self._closed = False

    def _submit(self, operation: Callable, *args) -> Future:
        if self._closed:
            raise RuntimeError("recording file is closed")
        previous = self._last_write

        def write() -> None:
            # Propagate earlier background errors instead of committing partial data.
            previous.result()
            operation(*args)

        self._last_write = self._writer.submit(write)
        return self._last_write

    def append_cameras(
        self, images: dict[str, torch.Tensor], steps: int,
        env_ids: tuple[int, ...], ready: torch.cuda.Event, compression: bool,
    ) -> Future:
        return self._submit(self._append_cameras, images, steps, env_ids, ready, compression)

    def _append_cameras(
        self, images: dict[str, torch.Tensor], steps: int,
        env_ids: tuple[int, ...], ready: torch.cuda.Event, compression: bool,
    ) -> None:
        ready.synchronize()
        pending = self._hdf5_file_stream.require_group("_pending")
        for name, image in images.items():
            for index, env_id in enumerate(env_ids):
                observations = pending.require_group(f"{env_id}/obs")
                values = image[:steps, index].numpy()
                if name not in observations:
                    options = {"compression": "gzip", "compression_opts": 2} if compression else {}
                    observations.create_dataset(
                        name, shape=(0, *values.shape[1:]),
                        maxshape=(None, *values.shape[1:]),
                        chunks=(1, *values.shape[1:]), dtype=values.dtype, **options,
                    )
                dataset = observations[name]
                start = len(dataset)
                dataset.resize(start + steps, axis=0)
                dataset[start:] = values
        self._hdf5_file_stream.flush()

    def discard_cameras(self, env_ids: Sequence[int]) -> None:
        self._submit(self._discard_cameras, tuple(env_ids))

    def _discard_cameras(self, env_ids: tuple[int, ...]) -> None:
        for env_id in env_ids:
            path = f"_pending/{env_id}"
            if path in self._hdf5_file_stream:
                del self._hdf5_file_stream[path]

    def add_env_args(self, env_args: dict) -> None:
        self._submit(super().add_env_args, env_args).result()

    def write_episode(
        self, episode: EpisodeData, demo_id: str | int | None = None,
        dataset_compression: bool = True,
    ) -> None:
        """Keep native string/integer/default demo naming and compression options."""
        self.camera_source.flush()
        self._submit(super().write_episode, episode, demo_id, dataset_compression).result()

    def _write_cameras(self, group: h5py.Group, episode: EpisodeData) -> None:
        source_file = self.camera_source._hdf5_file_stream
        path = f"_pending/{episode.env_id}/obs"
        if path in source_file:
            observations = group.require_group("obs")
            for name in list(source_file[path]):
                source = source_file[f"{path}/{name}"]
                if self.camera_source is self:
                    source_file.move(source.name, f"{observations.name}/{name}")
                else:
                    source_file.copy(source, observations, name=name)

    def flush(self) -> None:
        self._submit(super().flush).result()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._last_write.result()
        finally:
            self._writer.shutdown(wait=True)
            super().close()


@dataclass
class _CameraBuffer:
    images: dict[str, torch.Tensor]
    ready: torch.cuda.Event
    written: Future


class CameraTransfer:
    """Double-buffer pinned CPU images within a total byte budget."""

    def __init__(
        self, images: dict[str, torch.Tensor], handler: StreamingHDF5DatasetFileHandler,
        *, buffer_bytes: int, compression: bool,
    ) -> None:
        frame_bytes = sum(image.numel() * image.element_size() for image in images.values())
        self._capacity = buffer_bytes // (2 * frame_bytes)
        if self._capacity < 1:
            raise ValueError(
                f"camera buffer needs at least {2 * frame_bytes} bytes for two frames; "
                f"configured {buffer_bytes}"
            )
        self._handler = handler
        self._compression = compression
        self._stream = torch.cuda.Stream(device=next(iter(images.values())).device)
        self._buffers = [
            _CameraBuffer(
                images={
                    name: torch.empty(
                        (self._capacity, *image.shape), dtype=image.dtype,
                        device="cpu", pin_memory=True,
                    )
                    for name, image in images.items()
                },
                ready=torch.cuda.Event(), written=_completed(),
            )
            for _ in range(2)
        ]
        self._index = 0
        self._steps = 0
        self._env_ids: tuple[int, ...] = ()
        self._env_indices = torch.empty(0, dtype=torch.long, device=self._stream.device)
        LOGGER.info(
            "camera recording: chunk_steps=%d cpu_buffers_mib=%.1f",
            self._capacity, 2 * self._capacity * frame_bytes / 1024**2,
        )

    def append(self, images: dict[str, torch.Tensor], env_ids: tuple[int, ...]) -> None:
        if env_ids != self._env_ids:
            self.flush()
            self._env_ids = env_ids
            self._env_indices = torch.tensor(env_ids, dtype=torch.long, device=self._stream.device)
        buffer = self._buffers[self._index]
        if self._steps == 0:
            # Backpressure: the writer must release this buffer before reuse.
            buffer.written.result()
        self._stream.wait_stream(torch.cuda.current_stream(self._stream.device))
        with torch.cuda.stream(self._stream):
            for name, image in images.items():
                # Keep the source snapshot alive through DMA or the subset gather.
                image.record_stream(self._stream)
                if len(env_ids) != image.shape[0]:
                    self._env_indices.record_stream(self._stream)
                    image = image.index_select(0, self._env_indices)
                buffer.images[name][self._steps, :len(env_ids)].copy_(image, non_blocking=True)
        self._steps += 1
        if self._steps == self._capacity:
            self.flush()

    def flush(self) -> None:
        if not self._steps:
            return
        buffer = self._buffers[self._index]
        buffer.ready.record(self._stream)
        buffer.written = self._handler.append_cameras(
            buffer.images, self._steps, self._env_ids, buffer.ready, self._compression,
        )
        self._steps = 0
        self._index = (self._index + 1) % len(self._buffers)

    def close(self) -> None:
        # Closing aborts any uncommitted tail, but DMA must finish before freeing it.
        self._stream.synchronize()
        self._buffers.clear()
