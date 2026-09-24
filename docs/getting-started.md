---
description: 准备 SCALE-Bench 运行环境与资产，预览场景，采集第一条专家轨迹并检查 HDF5 结果。
---

# 开始使用

从准备环境到采集第一条专家轨迹，沿着这条路径运行 SCALE-Bench。

## 01 · 准备环境与资产 { #environment }

在本地克隆仓库，并进入仓库根目录。本文中的所有运行命令均从这里执行。

```bash
git clone https://github.com/CrysGate/SCALE-Bench.git
cd SCALE-Bench
```

### 运行环境

| 组件 | 项目使用版本 |
| --- | --- |
| Python | 3.12 |
| Isaac Sim | 6.0.1 |
| Isaac Lab | `release/3.0.0-beta2`，验证提交 `6a7acb0` |
| CuRobo | 验证提交 `8e734f3` |
| PyTorch / CUDA | 2.10 / 12.8 |
| 包管理 | [uv](https://docs.astral.sh/uv/) |

准备支持上述仿真环境的 NVIDIA GPU 与驱动。安装 `uv` 后，拉取项目引用的本地依赖，再同步 Python 环境：

```bash title="安装项目依赖"
mkdir -p third_parties
git clone --branch release/3.0.0-beta2 \
  https://github.com/isaac-sim/IsaacLab.git third_parties/IsaacLab
git clone https://github.com/NVlabs/curobo.git third_parties/curobo
git -C third_parties/IsaacLab checkout 6a7acb0
git -C third_parties/curobo checkout 8e734f3

uv sync --frozen
```

### 任务资产

将资产包准备到仓库的 `Assets/` 目录。具体路径以 `configs/` 下的 YAML 为准，包括机器人、房间、材质和任务物体。

!!! info "资产与抓取数据需要单独准备"

    `Assets/` 未纳入 Git。每个任务还需要对应的 Piper 抓取数据，离线候选读取自物体 USD 同目录的 `grasps-<机器人name>.yaml`。机器人配置中的 TCP 和关节定义应与抓取数据匹配。

完整安装说明与项目约定见 [仓库 README](https://github.com/CrysGate/SCALE-Bench/blob/main/README.zh-CN.md#环境)。

## 02 · 预览任务场景 { #preview }

先检查物体与场景是否正常加载，再启动完整采集。

=== "打开仿真窗口"

    ```bash title="预览套娃排序场景"
    uv run python scripts/preview_scene.py --task sort_dolls_by_size
    ```

=== "无界面运行检查"

    ```bash title="固定 seed，运行两个仿真步"
    uv run python scripts/preview_scene.py \
      --task single_object_pick_and_place \
      --seed 42 \
      --viz none \
      --max-steps 2
    ```

任务支持确定性 seed 与布局导入导出。需要恢复同一个实验场景时，参考 [布局复现命令](https://github.com/CrysGate/SCALE-Bench/blob/main/scripts/README.md#场景预览)。

## 03 · 采集专家数据 { #collect }

第一次运行建议选择单物体抓取与放置，先采集一个 episode。下面两种模式分别适用于状态数据采集和包含相机观测的数据采集。

=== "关节与动作"

    ```bash title="采集一条 bottle 操作轨迹"
    uv run python scripts/run_demo_generation.py \
      --task single_object_pick_and_place \
      --num-envs 1 \
      --episodes 1 \
      --max-steps 1200 \
      --record-output outputs/bottle-pick-place \
      --dataset-name bottle_pick_place \
      --viz none
    ```

=== "加入 RGB-D 相机"

    ```bash title="无显示器采集 RGB-D 与状态数据"
    HEADLESS=1 uv run python scripts/run_demo_generation.py \
      --task single_object_pick_and_place \
      --num-envs 1 \
      --episodes 1 \
      --max-steps 1200 \
      --record-output outputs/bottle-pick-place \
      --dataset-name bottle_pick_place \
      --viz kit \
      --record-camera-observations
    ```

!!! tip "相机采集需要渲染"

    默认记录关节状态、动作和评测结果。加入相机时，使用 `HEADLESS=1`、`--viz kit` 和 `--record-camera-observations`，以生成左腕、右腕及俯视相机的有效 RGB-D 帧。

更多任务的配置与命令见 [任务指南](tasks/index.md)。

## 04 · 检查数据与回放 { #inspect }

结束日志会输出实际 HDF5 路径、每条 episode 的结果和成功率。同名数据集已存在时，程序会自动增加文件名后缀。

- 成功与失败的 episode 都会保留，包含 success、终止原因和技能语义。
- 退出码为 `0` 表示全部 episode 成功；任务失败或运行异常时为非零。
- 回放时使用与采集一致的任务，并以日志中的实际数据路径为准。

=== "浏览数据"

    ```bash title="将路径替换为结束日志中的实际文件"
    uv run python scripts/view_hdf5.py \
      outputs/bottle-pick-place/bottle_pick_place.hdf5
    ```

    打开命令输出的本地地址，即可浏览关节轨迹、逐帧状态及可用的相机数据。有相机观测时，系统需要安装 `ffmpeg` 来生成播放视频。

=== "回放 episode"

    ```bash title="回放只有一个 episode 的数据集"
    uv run python scripts/replay_episode.py \
      outputs/bottle-pick-place/bottle_pick_place.hdf5 \
      --task single_object_pick_and_place \
      --viz kit
    ```

    数据集包含多个 episode 时，通过 `--episode-name` 指定要回放的一条。回放会恢复初态、重放 action 并重新评测。

## 继续探索

- [任务指南](tasks/index.md)：套娃排序、单物体放置和最大物体选择的任务配置与采集命令。
- [脚本说明](https://github.com/CrysGate/SCALE-Bench/blob/main/scripts/README.md)：布局导出、技能调试、策略运行和相机视频导出。

??? note "本地预览与构建文档"

    文档工具可通过 `uvx` 独立运行，无需启动仿真。

    ```bash
    uvx --from mkdocs==1.6.1 --with mkdocs-material==9.6.20 mkdocs serve
    ```

    提交前执行与 GitHub Pages 相同的严格构建：

    ```bash
    uvx --from mkdocs==1.6.1 --with mkdocs-material==9.6.20 mkdocs build --strict
    ```
