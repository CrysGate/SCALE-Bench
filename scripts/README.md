# 脚本用法

第一次运行先完成[安装与资产准备](https://crysgate.github.io/SCALE-Bench/getting-started/#environment)。

预览、采集、调试、策略链路验证和回放共用 `--task`、`--task-config` 与 `--object-set`；具体用法见[选择任务配置与物体](../docs/tasks/index.md#variants)。

## 场景预览

预览任务中的机械臂、物体和目标槽位：

```bash
uv run python scripts/preview_scene.py --task single_object_pick_and_place
```

无显示器时，运行两步检查场景加载：

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place --viz none --max-steps 2
```

## 布局复现

保存由固定种子生成的布局：

```bash
uv run python scripts/preview_scene.py \
  --task sort_dolls_by_size \
  --seed 42 \
  --export-layout layouts/sort_dolls_by_size/42.json
```

恢复该布局：

```bash
uv run python scripts/preview_scene.py \
  --task sort_dolls_by_size \
  --layout layouts/sort_dolls_by_size/42.json
```

## 批量采集

使用两个并行环境采集十个 episode，种子从 101 依次递增：

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --gpus 0 \
  --num-envs 2 \
  --episodes 10 \
  --base-seed 101 \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz none
```

根据显存容量调整并行环境数。需要图像时见 [RGB-D 采集](https://crysgate.github.io/SCALE-Bench/getting-started/#collect)。

相机录制占用过多内存时，通过 `--record-camera-buffer-mib` 调整每张 GPU 的图像缓冲预算，单位为 MiB。

单卡和多卡共用 `--gpus`，默认使用 GPU 0。使用全部 GPU 采集：

```bash
uv run python scripts/run_demo_generation.py \
  --gpus all \
  --task single_object_pick_and_place \
  --num-envs 2 \
  --episodes 4 \
  --base-seed 100 \
  --record-output outputs/bottle-pick-place \
  --dataset-name multi_gpu \
  --viz none
```

`all` 使用 `nvidia-smi` 列出的全部 GPU；也可用 `--gpus 0,1` 指定其中的编号。

所有轨迹合并为 `<record-output>/<dataset-name>.hdf5`，同目录保存 `.segments.jsonl` 和 `.summary.json`，各 GPU 的日志保存在 `<dataset-name>.logs/`。

更换机械臂时使用 `--robot-config` 指定[机器人配置](../configs/robots/)。对应物体需包含与该机械臂匹配的[抓取文件](../docs/assets/index.md)。

## 使用 Franka Panda

Franka Panda 搭载原装双指夹爪和腕部 D435。预览时指定机器人配置：

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place \
  --robot-config configs/robots/franka_panda.yml
```

无界面验证关节动作和 RGB-D 录制：

```bash
uv run python scripts/run_policy_rollout.py \
  --task single_object_pick_and_place \
  --robot-config configs/robots/franka_panda.yml \
  --left-joint4-offset-rad 0.1 \
  --record-output outputs/franka-panda-smoke \
  --dataset-name joint_motion \
  --viz none
```

## 使用 UR5e

UR5e 搭载 Robotiq 2F-85 夹爪和腕部 D435。预览时指定机器人配置：

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place \
  --robot-config configs/robots/ur5e.yml
```

无界面验证关节动作：

```bash
uv run python scripts/run_policy_rollout.py \
  --task single_object_pick_and_place \
  --robot-config configs/robots/ur5e.yml \
  --left-joint4-offset-rad 0.1 \
  --viz none
```

## 浏览与回放数据

在浏览器中检查关节轨迹、逐帧数据和相机观测：

```bash
uv run python scripts/view_hdf5.py \
  outputs/bottle-pick-place/bottle_pick_place.hdf5
```

打开终端输出的本地地址。播放相机视频需要安装 `ffmpeg`。

回放上面批量采集中的第一条轨迹，并重新评测：

```bash
uv run python scripts/replay_episode.py \
  outputs/bottle-pick-place/bottle_pick_place.hdf5 \
  --task single_object_pick_and_place \
  --episode-name demo_demo-seed-101 \
  --viz kit
```

使用采集日志中的实际文件路径，以及采集时的任务和机器人配置。只有一个 episode 时可省略 `--episode-name`；多条时可在数据浏览器中查看名称。

## 导出相机视频

从包含相机观测的录制中导出俯视 RGB 和伪彩色深度 MP4：

```bash
uv run python scripts/export_hdf5_camera_videos.py \
  outputs/bottle-pick-place/bottle_pick_place.hdf5 \
  --demo demo_demo-seed-101 \
  --camera overhead
```

左右腕相机分别使用 `left_robot`、`right_robot`。视频默认写入录制文件旁的 `<录制文件名>_videos/` 目录。

## 调试抓取与放置

执行一次抓取与放置，并查看各阶段的 CuRobo 碰撞场景：

```bash
uv run python scripts/run_skill_debug.py \
  --task single_object_pick_and_place \
  --program pick-and-place \
  --seed 101 \
  --visualize-curobo
```

调试需要图形界面，不写入数据集。使用 `<` 和 `>` 切换规划阶段的碰撞快照。蓝色球表示机械臂，橙色球表示夹持物；盒体中黄色为桌面、红色为物体、灰色为相机支架、绿色为另一机械臂。

多物体任务中，可用 `--object-name` 指定目标；只检查抓取时使用 `--program pick`。

## 手动检查机械臂关节

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place \
  --physics-inspector
```

在 Physics Inspector 中用 `Select Articulation` 选择机械臂，再用 `Joint States Position` 调整关节。该工具需要图形界面，用于局部关节检查；无需启动主时间轴。若显示 `Re-Enable authoring`，点击后继续操作。

## 验证策略运行链路

`run_policy_rollout.py` 使用内置策略检查多环境运行与录制，默认保持初始关节位置：

```bash
uv run python scripts/run_policy_rollout.py \
  --num-envs 2 \
  --episodes 3 \
  --record-output outputs/policy-smoke \
  --viz none
```

指定 `--record-output` 时保存全部 episode 的轨迹和三路 RGB-D，包括未完成操作任务的 episode。默认使用 160×120 的相机配置以降低验证开销。

需要检查关节动作时，可加入 `--left-joint4-offset-rad 0.1`，使左臂第四关节移动指定角度。

## 生成资产三视图

生成带尺寸标注的正面、侧面和俯视图片：

```bash
uv run python scripts/render_asset_views.py \
  Assets/Object/Rigid/bubble_tea_cup/300g/Aligned.usd \
  Assets/Object/Rigid/bubble_tea_cup/500g/Aligned.usd \
  Assets/Object/Rigid/bubble_tea_cup/800g/Aligned.usd \
  --output-dir docs/assets/objects/bubble_tea_cup
```

转换自己的 OBJ 资产见 [OBJ 转 USD](../src/assets_gen/README.zh-CN.md)。

## 生成 CuRobo 机器人配置

根据机器人配置和 URDF 生成 YAML 碰撞配置，需要 CUDA：

```bash
uv run python scripts/generate_curobo_robot_config.py \
  --robot-config configs/robots/piper.yml \
  --output configs/robots/curobo/piper.yml \
  --refit-link link8:2.0
```

检查碰撞球拟合质量时加 `--export-metrics`，对接使用 XRDF 的工具时加 `--export-xrdf`。

Panda 使用 URDF 碰撞网格拟合，D435 按 USD 中的凸包碰撞形状处理：

```bash
uv run python scripts/generate_curobo_robot_config.py \
  --robot-config configs/robots/franka_panda.yml \
  --output configs/robots/curobo/franka_panda.yml \
  --use-collision-mesh --sphere-density 2 \
  --convex-fit-link camera
```

UR5e 为相机支架提高拟合密度，并排除夹爪联动产生的接触对：

```bash
uv run python scripts/generate_curobo_robot_config.py \
  --robot-config configs/robots/ur5e.yml \
  --output configs/robots/curobo/ur5e.yml \
  --base-collision-link base_link_inertia \
  --use-collision-mesh --sphere-density 2 \
  --refit-link camera_base:20 \
  --ignore-collision-pair robotiq_85_base_link:robotiq_85_left_finger_link \
  --ignore-collision-pair robotiq_85_right_inner_knuckle_link:robotiq_85_right_knuckle_link \
  --ignore-collision-pair robotiq_85_left_finger_tip_link:robotiq_85_right_finger_tip_link \
  --ignore-collision-pair robotiq_85_left_finger_tip_link:robotiq_85_right_inner_knuckle_link \
  --ignore-collision-pair robotiq_85_left_inner_knuckle_link:robotiq_85_right_finger_tip_link \
  --ignore-collision-pair robotiq_85_left_inner_knuckle_link:robotiq_85_right_inner_knuckle_link
```
