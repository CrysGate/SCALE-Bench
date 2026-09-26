# 脚本用法

第一次运行先完成[安装与资产准备](https://crysgate.github.io/SCALE-Bench/getting-started/#environment)。

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
  --num-envs 2 \
  --episodes 10 \
  --base-seed 101 \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz none
```

根据显存容量调整并行环境数，采集总数由 `--episodes` 决定。[相机录制与结果说明](https://crysgate.github.io/SCALE-Bench/getting-started/#collect)涵盖 RGB-D 采集、成功标记和输出路径。

更换机械臂时使用 `--robot-config` 指定[机器人配置](../configs/robots/)。对应物体需包含与该机械臂匹配的[抓取文件](../docs/assets/index.md)。

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

根据机器人配置和 URDF 生成碰撞配置，需要 CUDA：

```bash
uv run python scripts/generate_curobo_robot_config.py \
  --robot-config configs/robots/piper.yml \
  --output configs/robots/curobo/piper.yml
```
