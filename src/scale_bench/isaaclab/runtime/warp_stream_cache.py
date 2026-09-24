"""Reuse imported CUDA streams without concurrent Warp registration or teardown.

The cache owns wrappers for the process lifetime: releasing them while planning
workers run would call Warp's unsynchronized native stream unregister function.
"""

from __future__ import annotations

from threading import Lock

import torch
import warp as wp

_original_stream_from_torch = wp.stream_from_torch
_stream_lock = Lock()
_stream_cache: dict[tuple[int, int], wp.Stream] = {}


def _cached_stream_from_torch(
    stream_or_device: torch.cuda.Stream | torch.device | str | int | None = None,
) -> wp.Stream:
    """Preserve Warp's conversion API while sharing one wrapper per CUDA stream.

    CuRobo passes explicit streams, including CUDA graph capture streams. Since
    this replaces Warp's public function, device objects, strings and ordinals
    still select that device's current stream; an omitted argument or None
    selects the current device's current stream, as in the original API.
    """
    torch_stream = (
        stream_or_device
        if isinstance(stream_or_device, torch.cuda.Stream)
        else torch.cuda.current_stream(stream_or_device)
    )
    with _stream_lock:
        warp_device = wp.device_from_torch(torch_stream.device)
        key = (warp_device.context, torch_stream.cuda_stream)
        if key not in _stream_cache:
            _stream_cache[key] = _original_stream_from_torch(torch_stream)
        return _stream_cache[key]


def install_warp_stream_cache() -> None:
    """Install the converter before constructing or warming up CuRobo backends.

    Repeated planning pools reuse the same function and process-wide cache.
    Solves and kernel launches run outside the cache lock.
    """
    wp.stream_from_torch = _cached_stream_from_torch
