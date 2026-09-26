"""Area lights linked to the geometry of their own cloned environment."""

from __future__ import annotations

from collections.abc import Callable

import isaaclab.sim as sim_utils
from isaaclab.utils.configclass import configclass
from pxr import Usd, UsdLux


def spawn_environment_light(prim_path: str, cfg: EnvironmentDiskLightCfg, **kwargs) -> Usd.Prim:
    root = sim_utils.spawn_light(prim_path, cfg, **kwargs)
    stage = sim_utils.get_current_stage()
    for path in sim_utils.find_matching_prim_paths(prim_path):
        light = UsdLux.LightAPI(stage.GetPrimAtPath(path))
        env_path = light.GetPrim().GetPath().GetParentPath().GetParentPath()
        for collection in (light.GetLightLinkCollectionAPI(), light.GetShadowLinkCollectionAPI()):
            collection.CreateIncludeRootAttr(False)
            collection.CreateIncludesRel().SetTargets([env_path])
    return root


@configclass
class EnvironmentDiskLightCfg(sim_utils.DiskLightCfg):
    func: Callable = spawn_environment_light
