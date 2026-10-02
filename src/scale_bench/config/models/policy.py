"""Environment-side settings for XPolicyLab joint policy evaluation."""

from typing import Annotated, Literal

from pydantic import Field, StrictBool

from scale_bench.config.base import FrozenModel, Name, PositiveFloat, PositiveInt


class XPolicyLabConfig(FrozenModel):
    server_url: Annotated[str, Field(pattern=r"^wss?://[^\s]+$")]
    # Single-model adapters (for example ACT) require single mode. Batch mode
    # is selected only for adapters implementing both batch RPCs with env_idx.
    inference_mode: Literal["single", "batch"]
    action_steps: PositiveInt
    camera_map: Annotated[dict[Name, Name], Field(min_length=1)]
    send_depth: StrictBool
    request_timeout_s: PositiveFloat
    max_connect_seconds: PositiveFloat
