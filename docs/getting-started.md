---
description: 安装 SCALE-Bench、获取资产，采集第一条专家轨迹并查看结果。
---

# 开始使用

本指南使用单物体抓取与放置任务，完成从安装到采集、浏览和回放的第一次运行。

## 准备环境与资产 { #environment }

需要 NVIDIA GPU、兼容的驱动、[uv](https://docs.astral.sh/uv/) 和 [Git LFS](https://git-lfs.com/)。当前验证环境为：

| 组件 | 版本 |
| --- | --- |
| Python | 3.12 |
| Isaac Sim | 6.0.1 |
| Isaac Lab | `release/3.0.0-beta2`，提交 `6a7acb0` |
| CuRobo | 提交 `8e734f3` |
| PyTorch / CUDA | 2.10 / 12.8 |

```bash
git clone https://github.com/CrysGate/SCALE-Bench.git
cd SCALE-Bench

mkdir -p third_parties
git clone --branch release/3.0.0-beta2 \
  https://github.com/isaac-sim/IsaacLab.git third_parties/IsaacLab
git clone https://github.com/NVlabs/curobo.git third_parties/curobo
git -C third_parties/IsaacLab checkout 6a7acb0
git -C third_parties/curobo checkout 8e734f3

uv sync --frozen
```

资产来自 [ScaleBench-Data](https://modelscope.cn/datasets/CrysGate/ScaleBench-Data)。将数据仓库克隆到项目同级目录，再把其中的 [Assets](https://modelscope.cn/datasets/CrysGate/ScaleBench-Data/tree/master/Assets) 链接到当前项目：

```bash
git lfs install
git clone https://www.modelscope.cn/datasets/CrysGate/ScaleBench-Data.git ../ScaleBench-Data
ln -s ../ScaleBench-Data/Assets Assets
```

## 预览场景 { #preview }

```bash
uv run python scripts/preview_scene.py --task single_object_pick_and_place
```

窗口中应显示机械臂、桌面、瓶子和目标槽位。无显示器时可运行两步检查场景加载：

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place \
  --viz none \
  --max-steps 2
```

## 采集专家数据 { #collect }

先采集一次抓取与放置，即一个 episode。默认保存关节状态、动作和评测结果：

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz none
```

需要左腕、右腕和俯视相机的 RGB-D 时，使用以下无显示器采集命令；相机观测需要启用渲染：

```bash
HEADLESS=1 uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz kit \
  --record-camera-observations
```

## 检查数据与回放 { #inspect }

结束日志给出成功率和实际 HDF5 路径。成功与失败的 episode 都会保留，使用数据时按 `success` 区分。退出码为 `0` 表示全部成功，非零表示有任务失败或运行异常。

首次运行的数据路径如下；重复运行会自动增加文件名后缀，后续命令使用日志中的实际路径。

```bash
uv run python scripts/view_hdf5.py \
  outputs/bottle-pick-place/bottle_pick_place.hdf5
```

打开命令输出的本地地址，检查关节轨迹和逐帧数据。播放相机视频需要系统安装 `ffmpeg`。

回放会恢复初始场景、重放动作并重新评测：

```bash
uv run python scripts/replay_episode.py \
  outputs/bottle-pick-place/bottle_pick_place.hdf5 \
  --task single_object_pick_and_place \
  --viz kit
```

## 下一步

- [选择其他任务](tasks/index.md)。
- [复现同一布局](https://github.com/CrysGate/SCALE-Bench/blob/main/scripts/README.md#布局复现)。
- [批量采集与辅助工具](https://github.com/CrysGate/SCALE-Bench/blob/main/scripts/README.md)。
