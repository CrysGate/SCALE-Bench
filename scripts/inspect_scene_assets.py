"""Inspect two live environments, RGB-D, open cavities and material/light isolation."""

import argparse
import json
from pathlib import Path
import sys
import time
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--scene-config", type=Path, required=True)
parser.add_argument("--object-set", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
AppLauncher.add_app_launcher_args(parser)
parser.set_defaults(enable_cameras=True)
args = parser.parse_args()
app = AppLauncher(args).app


def main() -> None:
    import numpy as np
    from PIL import Image
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade
    import torch
    import isaaclab.sim as sim_utils
    from isaaclab.assets import RigidObjectCfg
    from scale_bench.config.loader import load_config
    from scale_bench.config.models.environment import EnvironmentConfig
    from scale_bench.config.models.robot import RobotConfig
    from scale_bench.config.models.scene import SceneConfig
    from scale_bench.config.models.simulation import SimulationConfig
    from scale_bench.isaaclab.builders.environment import build_environment_cfg
    from scale_bench.isaaclab.runtime.environment import ScaleBenchEnv
    from scale_bench.tasks.registry import load_task

    scene_config = load_config(args.scene_config, SceneConfig, asset_root=PROJECT_ROOT)
    robot = load_config(PROJECT_ROOT / "configs/robots/piper.yml", RobotConfig, asset_root=PROJECT_ROOT)
    task = load_task("single_object_pick_and_place", project_root=PROJECT_ROOT, asset_root=PROJECT_ROOT, object_set_path=args.object_set)
    cfg = build_environment_cfg(
        left_robot_config=robot, right_robot_config=robot, scene_config=scene_config,
        simulation_config=load_config(PROJECT_ROOT / "configs/sim/default.yml", SimulationConfig),
        environment_config=load_config(PROJECT_ROOT / "configs/envs/default.yml", EnvironmentConfig),
        task=task, task_layout_seed=100, num_envs=2,
    )
    probe_radius_m = 0.003
    containers = {}
    for name, asset in task.assets.items():
        metadata = json.loads(Path(asset.metadata_path).read_text())
        if "container" not in metadata:
            continue
        containers[name] = metadata["container"]
        object_cfg = getattr(cfg.scene, name)
        object_position_env_m = object_cfg.init_state.pos
        setattr(cfg.scene, f"probe_{name}", RigidObjectCfg(
            prim_path=f"{{ENV_REGEX_NS}}/Probes/{name}",
            init_state=RigidObjectCfg.InitialStateCfg(pos=(
                *object_position_env_m[:2], object_position_env_m[2] + task.metadata[name].size[2] / 2 + 0.03,
            )),
            spawn=sim_utils.SphereCfg(
                radius=probe_radius_m,
                # Keep travel per physics step below the thinnest container base.
                rigid_props=sim_utils.PhysxRigidBodyPropertiesCfg(max_linear_velocity=0.1),
                collision_props=sim_utils.PhysxCollisionPropertiesCfg(contact_offset=0.001, rest_offset=0.0),
                mass_props=sim_utils.MassPropertiesCfg(mass=0.001),
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(1.0, 0.1, 0.1)),
            ),
        ))
    env = ScaleBenchEnv(cfg)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    try:
        env.reset()
        # Layout reset uses a distinct seed per environment; align each probe with its object.
        for name in containers:
            probe = env.scene[f"probe_{name}"]
            probe_pose_world = probe.data.root_pose_w.torch.clone()
            probe_pose_world[:, :3] = env.scene[name].data.root_pos_w.torch
            probe_pose_world[:, 2] += task.metadata[name].size[2] / 2 + 0.03
            probe.write_root_pose_to_sim_index(root_pose=probe_pose_world)
            probe.write_root_velocity_to_sim_index(root_velocity=torch.zeros((2, 6), device=env.device))
            print({"probe_reset_world": probe_pose_world[:, :3].cpu().tolist()}, flush=True)
        started = time.perf_counter()
        for _ in range(90):
            env.step(env.hold_action())
        elapsed = time.perf_counter() - started
        gpu_memory_used_mib = int(subprocess.check_output([
            "nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits",
            f"--id={torch.cuda.current_device()}",
        ], text=True).strip())
        stage = sim_utils.get_current_stage()
        bounds = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
        report = {"scene": str(args.scene_config), "object_set": str(args.object_set), "num_envs": 2,
                  "probe_max_linear_velocity_m_s": 0.1,
                  "environment_steps_per_second": 180 / elapsed, "torch_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                  "gpu_memory_used_mib_including_other_processes": gpu_memory_used_mib,
                  "props": [], "cavities": [], "cameras": [], "light_links": []}
        for env_id in range(2):
            env_path = f"/World/envs/env_{env_id}"
            env_origin_world_m = env.scene.env_origins[env_id].cpu().numpy()
            for prop in scene_config.props:
                measured = bounds.ComputeWorldBound(stage.GetPrimAtPath(f"{env_path}/Props/{prop.name}")).ComputeAlignedRange()
                prop_position_env_m = np.array(measured.GetMidpoint()) - env_origin_world_m
                assert np.allclose(prop_position_env_m, prop.object_position_env_m, atol=1e-5), prop.name
                assert np.isclose(measured.GetMin()[2] - env_origin_world_m[2], prop.support_position_env_m[2], atol=1e-5), prop.name
                report["props"].append({"env": env_id, "name": prop.name, "center_env_m": prop_position_env_m.tolist()})
            for prim in Usd.PrimRange(stage.GetPrimAtPath(f"{env_path}/Room")):
                assert not prim.HasAPI(UsdLux.LightAPI), str(prim.GetPath())
            for prim in Usd.PrimRange(stage.GetPrimAtPath(f"{env_path}/Lights")):
                if prim.HasAPI(UsdLux.LightAPI):
                    links = UsdLux.LightAPI(prim).GetLightLinkCollectionAPI().GetIncludesRel().GetTargets()
                    assert list(map(str, links)) == [env_path], (prim.GetPath(), links)
                    report["light_links"].append({"light": str(prim.GetPath()), "includes": list(map(str, links))})
            for name, container in containers.items():
                object_position_world_m = env.scene[name].data.root_pos_w.torch[env_id].cpu().numpy()
                probe_position_world_m = env.scene[f"probe_{name}"].data.root_pos_w.torch[env_id].cpu().numpy()
                expected_probe_z_world_m = object_position_world_m[2] + container["floor_z_object_m"] + probe_radius_m
                error_m = float(probe_position_world_m[2] - expected_probe_z_world_m)
                print({"env": env_id, "object_position_world_m": object_position_world_m.tolist(), "object_orientation_world_xyzw": env.scene[name].data.root_quat_w.torch[env_id].cpu().tolist(), "probe_position_world_m": probe_position_world_m.tolist(), "probe_floor_error_m": error_m}, flush=True)
                # Smaller than the thinnest base, so a probe on the table fails.
                assert abs(error_m) < 0.001, (name, error_m)
                support_error_m = float(object_position_world_m[2] - env_origin_world_m[2] - task.metadata[name].size[2] / 2 - scene_config.table_top_z_m)
                assert abs(support_error_m) < 0.003, (name, support_error_m)
                report["cavities"].append({"env": env_id, "name": name, "probe_floor_error_m": error_m, "support_error_m": support_error_m})
        frames, before = [], {}
        for env_id in range(2):
            for name in ("left_robot_camera", "right_robot_camera", "overhead_camera"):
                camera = env.scene.sensors[name]
                rgb = camera.data.output["rgb"][env_id].cpu().numpy()[..., :3].copy()
                depth = camera.data.output["distance_to_image_plane"][env_id].cpu().numpy()
                assert rgb.std() > 1 and np.isfinite(depth).any(), (env_id, name)
                before[env_id, name] = rgb
                frame = Image.fromarray(rgb)
                frame.save(output / f"env{env_id}_{name}.png")
                np.save(output / f"env{env_id}_{name}_depth_m.npy", depth)
                frames.append(frame)
                report["cameras"].append({"env": env_id, "name": name, "shape": list(rgb.shape), "finite_depth_fraction": float(np.isfinite(depth).mean())})
        sheet = Image.new("RGB", (frames[0].width * 3, frames[0].height * 2))
        for index, frame in enumerate(frames):
            sheet.paste(frame, (index % 3 * frame.width, index // 3 * frame.height))
        sheet.save(output / "cameras.png")
        # Mutate only env_1, then verify env_0 retains its material graph and key intensity.
        lights = [prim for prim in Usd.PrimRange(stage.GetPrimAtPath("/World/envs/env_1/Lights")) if prim.HasAPI(UsdLux.LightAPI)]
        for prim in lights:
            other_path = str(prim.GetPath()).replace("env_1", "env_0")
            other_intensity = UsdLux.LightAPI(stage.GetPrimAtPath(other_path)).GetIntensityAttr()
            original = other_intensity.Get()
            UsdLux.LightAPI(prim).GetIntensityAttr().Set(0.0)
            assert other_intensity.Get() == original
        if scene_config.table.pbr is not None:
            shaders = [UsdShade.Shader(stage.GetPrimAtPath(f"/World/envs/env_{i}/Table/geometry/PBR/Shader")) for i in range(2)]
            original_connection = shaders[0].GetInput("diffuseColor").GetAttr().GetConnections()
            shaders[1].GetInput("diffuseColor").DisconnectSource()
            shaders[1].GetInput("diffuseColor").Set(Gf.Vec3f(0.8, 0.02, 0.02))
            assert shaders[0].GetInput("diffuseColor").GetAttr().GetConnections() == original_connection
        else:
            # MDL scenes exercise a local material replacement instead of a PBR input.
            bindings = [UsdShade.MaterialBindingAPI(stage.GetPrimAtPath(
                f"/World/envs/env_{i}/Table/geometry/mesh"
            )) for i in range(2)]
            original_material = bindings[0].ComputeBoundMaterial()[0].GetPath()
            material = UsdShade.Material.Define(stage, "/World/envs/env_1/Table/InspectionMaterial")
            shader = UsdShade.Shader.Define(stage, material.GetPath().AppendChild("Shader"))
            shader.CreateIdAttr("UsdPreviewSurface")
            shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.8, 0.02, 0.02))
            material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
            bindings[1].Bind(material, bindingStrength=UsdShade.Tokens.strongerThanDescendants)
            assert bindings[0].ComputeBoundMaterial()[0].GetPath() == original_material
        for _ in range(30):
            env.step(env.hold_action())
        report["isolation_rgb_mean_absolute_change"] = {}
        for env_id in range(2):
            rgb = env.scene.sensors["overhead_camera"].data.output["rgb"][env_id].cpu().numpy()[..., :3]
            Image.fromarray(rgb).save(output / f"env{env_id}_after_override.png")
            report["isolation_rgb_mean_absolute_change"][str(env_id)] = float(np.abs(rgb.astype(float) - before[env_id, "overhead_camera"]).mean())
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)
    finally:
        env.close()


exit_code = 0
try:
    main()
except BaseException:
    import traceback
    traceback.print_exc()
    exit_code = 1
finally:
    app.close(exit_code=exit_code)
