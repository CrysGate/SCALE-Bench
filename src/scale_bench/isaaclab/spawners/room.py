"""Load room geometry while removing duplicate fixtures and imported lights."""

from __future__ import annotations

from collections.abc import Callable
from fnmatch import fnmatchcase

import isaaclab.sim as sim_utils
from isaaclab.utils.configclass import configclass
from pxr import Usd, UsdLux


def spawn_room(prim_path: str, cfg: RoomUsdCfg, **kwargs) -> Usd.Prim:
    root = sim_utils.spawn_from_usd(prim_path, cfg, **kwargs)
    for path in sim_utils.find_matching_prim_paths(prim_path):
        stage = sim_utils.get_current_stage()
        for pattern in cfg.excluded_prim_paths:
            matches = [
                prim for prim in Usd.PrimRange(stage.GetPrimAtPath(path))
                if fnmatchcase(str(prim.GetPath())[len(path) + 1:], pattern)
            ]
            if not matches:
                raise ValueError(f"Room exclusion does not match: {path}/{pattern}")
            for prim in sorted(matches, key=lambda item: item.GetPath().pathElementCount, reverse=True):
                prim.SetActive(False)
        for prim in Usd.PrimRange(stage.GetPrimAtPath(path)):
            if prim.HasAPI(UsdLux.LightAPI):
                prim.SetActive(False)
    return root


@configclass
class RoomUsdCfg(sim_utils.UsdFileCfg):
    func: Callable = spawn_room
    excluded_prim_paths: tuple[str, ...] = ()
