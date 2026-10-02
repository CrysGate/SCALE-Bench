"""Independent client for XPolicyLab's binary WebSocket RPC protocol.

No server code is imported. Frames are MessagePack maps with msgpack-numpy
arrays; RGB images travel as arrays, so no server-specific JPEG codec is needed.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import msgpack
import msgpack_numpy
import numpy as np
from websockets.sync.client import ClientConnection, connect

from scale_bench.config.models.policy import XPolicyLabConfig

LOGGER = logging.getLogger(__name__)


def _encode_array(value: Any) -> Any:
    if isinstance(value, (np.ndarray, np.generic)) and value.dtype.hasobject:
        raise ValueError("object arrays are not supported by the policy protocol")
    return msgpack_numpy.encode(value)


def _decode_array(value: dict) -> Any:
    # msgpack-numpy otherwise unpickles object arrays. Only numeric/image arrays
    # are part of the observation/action contract.
    if value.get(b"kind") == b"O":
        raise ValueError("object arrays are not supported by the policy protocol")
    return msgpack_numpy.decode(value)


class PolicyClient:
    """Sequential RPC connection owned by one evaluation.

    Retry connection establishment while the model loads. Once connected, any
    transport error aborts the run: replaying a stateful model call or silently
    connecting to a restarted model could invalidate benchmark results.
    """

    def __init__(self, *, config: XPolicyLabConfig, evaluation_id: str) -> None:
        self._config = config
        self._evaluation_id = evaluation_id
        self._trial_id = evaluation_id
        self._step = 0
        self._connection = self._connect()
        try:
            self.server_info = self._request("hello", "hello_ack", {})
        except BaseException:
            self.close()
            raise

    def _connect(self) -> ClientConnection:
        deadline = time.monotonic() + self._config.max_connect_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"policy server unavailable: {self._config.server_url}")
            try:
                return connect(
                    self._config.server_url,
                    open_timeout=min(remaining, self._config.request_timeout_s),
                    close_timeout=5.0,
                    compression=None,
                    max_size=None,
                )
            except (OSError, TimeoutError) as error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"policy server unavailable: {self._config.server_url}"
                    ) from error
                LOGGER.info("Waiting for policy server %s: %s", self._config.server_url, error)
                time.sleep(min(1.0, remaining))

    def reset(self, trial_id: str) -> None:
        self._trial_id = trial_id
        self._step = 0
        self._request("reset", "reset_result", {})

    def call(self, method: str, arguments: dict[str, Any]) -> Any:
        """Pass {'obs': value} for observations/indices, or {} for get_action."""
        payload = self._request("call", "call_result", {"func_name": method, **arguments})
        if method in {"get_action", "get_action_batch"}:
            self._step += 1
        return payload.get("result")

    def _request(
        self, message_type: str, response_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        message_id = uuid4().hex
        frame = {
            "message_type": message_type,
            "message_id": message_id,
            "evaluation_id": self._evaluation_id,
            "trial_id": self._trial_id,
            "step": self._step,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        try:
            self._connection.send(msgpack.packb(frame, default=_encode_array, use_bin_type=True))
            raw = self._connection.recv(timeout=self._config.request_timeout_s)
            if not isinstance(raw, bytes):
                raise ValueError("policy response must be a binary MessagePack frame")
            response = msgpack.unpackb(raw, raw=False, object_hook=_decode_array)
            if not isinstance(response, dict):
                raise ValueError("policy response must be a mapping")
            for key in ("message_id", "evaluation_id", "trial_id", "step"):
                if response.get(key) != frame[key]:
                    raise ValueError(f"policy response {key} does not match the request")
            result = response.get("payload")
            if not isinstance(result, dict):
                raise ValueError("policy response payload must be a mapping")
            if response.get("message_type") == "error":
                raise RuntimeError(f"policy server {result.get('code')}: {result.get('message')}")
            if response.get("message_type") != response_type or result.get("ok") is not True:
                raise ValueError(f"expected successful {response_type} from policy server")
            return result
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> PolicyClient:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()
