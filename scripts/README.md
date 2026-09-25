# Scripts

以下命令都从仓库根目录运行。参数列表以各脚本的 `--help` 为准。

## 场景预览

`preview_scene.py` 创建真实 `ScaleBenchEnv`，用于交互预览、layout 检查和有界运行：

```bash
uv run python scripts/preview_scene.py \
  --task sort_dolls_by_size \
  --seed 42
```

支持的 task 为 `sort_dolls_by_size`、`single_object_pick_and_place` 和 `largest_pick_and_place`。`--seed` 与 `--layout` 互斥；`--export-layout` 保存本次布局。

`--workspace-samples` 调整每臂采样数量，`--workspace-opacity` 调整单点不透明度。

使用 Physics Inspector 手动检查机械臂关节：

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place \
  --physics-inspector
```

此模式固定使用 CPU 物理（覆盖 `--device` 和仿真配置中的设备，渲染仍使用 GPU），以兼容 Inspector 的关节驱动接口。加载场景后停止主仿真并打开 Inspector，不再下发环境动作。在 Inspector 中使用 `Select Articulation` 选择机械臂，通过关节滑块检查运动。Inspector 使用局部关节调试仿真，不代表完整任务执行或与整个场景的碰撞验证；无需点击主时间轴的 Play。该模式要求 Kit 图形界面，`--max-steps` 限制界面更新次数。

Inspector 模式同时关闭 Fabric，启用物理状态到 USD 的同步，并在场景初始化完成后启用 authoring。选择机械臂或修改场景后若出现 `Re-Enable authoring`，点击它重新解析场景。调整关节位置请使用 `Joint States Position`（直接改变关节位置）或 `Joint Drives Target Position`（通过驱动运动到目标）；修改 Limits/Gains 只改变约束或驱动参数，不会直接指定新位置。

无界面检查：

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place \
  --viz none \
  --max-steps 2
```

## Policy 运行

`run_policy_rollout.py` 使用套娃任务验证 policy、fixed-batch scheduler、episode evaluator 和可选 HDF5 记录：

```bash
uv run python scripts/run_policy_rollout.py \
  --num-envs 2 \
  --episodes 3 \
  --max-steps 8 \
  --record-output outputs/policy-smoke \
  --viz none
```

默认 policy 保持 reset 关节位置，并按 seed 在不同 step 结束。传入 `--left-joint4-offset-rad` 时会执行一次真实 `MoveToJoints` command，用于检查 action adapter。

## 专家数据采集

`run_demo_generation.py` 是专家数据采集客户端：始终执行 Task 提供的完整专家程序并保存 HDF5。默认任务为 `single_object_pick_and_place`，默认步数上限为 1200，默认输出为 `outputs/demonstrations/demo_generation.hdf5`。同名数据集存在时自动增加后缀，结束日志给出实际文件路径。

```bash
HEADLESS=1 uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --base-seed 101 \
  --num-envs 2 \
  --episodes 3 \
  --max-steps 1200 \
  --viz kit \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --record-camera-observations
```

seed 范围为 `[base-seed, base-seed + episodes)`，`--num-envs` 只改变并行 slot 数；最后一批可以不满。采集成功和失败的 episode 都保留，并记录 success、终止原因和技能语义。退出码为 0 表示全部 episode 成功；存在失败或运行异常时为非零。日志输出每条结果、成功率和实际数据集路径。

每个环境拥有独立的 CuRobo 单场景规划器、碰撞场景和 CUDA stream，不同环境的规划请求由工作线程并发求解。规划器保留单场景求解的重试与图搜索能力，同一环境内的运动阶段和候选尝试依次执行。`--num-envs` 决定环境和规划器数量。

启动时在主线程逐个预热规划器并捕获 CUDA Graph，随后才开始并发求解。相机采集和 Isaac 状态读取仍在主线程完成。规划期间暂停仿真，本轮所需命令准备完成后统一步进，避免计算等待时间变成录制中的额外物理步。

`PLAN-INIT` 记录环境数量和初始化预热耗时；`PLAN-PARALLEL` 记录同轮并发请求的环境 ID、数量与耗时；`PLAN-STATS` 汇总请求数、规划成功/失败数、参与并发的请求数以及规划队列与预热耗时。规划请求失败后由技能层决定是否继续尝试候选，规划成功数不等于最终 episode 成功数。增加环境数会增加 GPU 资源需求，显存不足时应降低 `--num-envs`。

省略 `--record-camera-observations` 时记录关节、动作等默认数据；传入时额外保存左腕、右腕和俯视相机的 RGB-D。无显示器采集相机时使用 `HEADLESS=1 --viz kit`，使 reset 阶段生成有效 RTX 帧；`--viz none` 适用于不录制相机的运行。

抓取候选读取自物体 USD 同目录的 `grasps-<机器人name>.yaml`。机器人通过 `--robot-config` 选择，其 TCP 和关节定义必须与抓取数据匹配。

`--log-file PATH` 追加完整 DEBUG JSONL；省略时只输出终端日志。自定义配置路径相对于当前目录解析，内置配置默认使用仓库中的绝对路径。

运行奶茶杯任务时将示例中的 `--task` 改为 `largest_pick_and_place`，并准备好 [任务配置](../configs/tasks/largest_pick_and_place.yml) 引用的资产及对应的抓取文件。

### 单步技能与 CuRobo 调试

`run_skill_debug.py` 执行一次 `pick` 或 `pick-and-place`，不写入演示数据集。`--object-name` 省略时使用任务的第一个目标物体。

```bash
uv run python scripts/run_skill_debug.py \
  --task single_object_pick_and_place \
  --program pick-and-place \
  --seed 101 \
  --visualize-curobo
```

`--visualize-curobo` 启用 Kit，在执行后浏览实际规划阶段；关闭浏览器后退出。该入口固定使用一个环境、一个 episode，不能将该开关与 `--headless` 或不包含 Kit 的显式 visualizer 配置组合。

`grasp`、`retreat` 和恢复撤离 `recover_retreat` 临时关闭当前机械臂两个 finger 的 CuRobo 碰撞检查；抓取候选的 `select_grasp` IK 使用相同规则。其他阶段保留 finger 检查，另一机械臂的 finger 仍作为障碍物。每次求解结束或异常退出后恢复检查，仿真中的物理接触不变。`PLAN-STATE` 和 `MOTION-PLAN` 日志中的 `check_finger_collision` 记录该次求解的策略。

- 蓝色球：求解机械臂的 collision spheres。
- 橙色球：夹持物的 collision spheres。
- 黄色盒体：桌面。
- 红色盒体：场景物体。
- 灰色盒体：相机支架。
- 绿色盒体：另一机械臂。

使用 `<` 和 `>` 浏览实际进入过的 `pre_grasp`、`grasp`、`lift`、`pre_place`、`place`、`retreat`、`clear` 阶段。这些是规划起点的碰撞快照，不是轨迹动画。

## Episode 回放

`replay_episode.py` 恢复录制初态、重放全部 action，并核对 seed、layout、步数和重新评测的 success：

```bash
uv run python scripts/replay_episode.py \
  outputs/bottle-pick-place/bottle_pick_place.hdf5 \
  --task single_object_pick_and_place \
  --episode-name demo-seed-101 \
  --viz kit
```

数据集只有一个 episode 时可省略 `--episode-name`。回放不会再次记录。

## 浏览 HDF5 录制

`view_hdf5.py` 使用 NiceGUI 在本机浏览器中展示多个 episode、可选的 RGB-D 相机、录制属性和逐帧状态。每个关节都有独立的连续轨迹图，并与视频或纯数据播放同步：

```bash
uv run python scripts/view_hdf5.py \
  outputs/bottle-pick-place/bottle_pick_place.hdf5
```

打开命令输出的 `http://127.0.0.1:8765`；端口占用时传入 `--port`。浏览器只监听本机回环地址。无相机观测的录制可直接播放关节和逐帧数据；存在相机观测时必须成对包含 RGB 和 depth，且系统需要安装 `ffmpeg` 才能生成播放视频。

## 导出相机视频

`export_hdf5_camera_videos.py` 从一个 HDF5 group 导出 RGB 和伪彩色深度 MP4：

```bash
uv run python scripts/export_hdf5_camera_videos.py \
  outputs/bottle-pick-place/bottle_pick_place.hdf5 \
  --demo demo_demo-seed-101 \
  --camera overhead
```

`--camera` 可选 `left_robot`、`right_robot` 或 `overhead`。默认帧率从记录元数据推导；`--depth-min-m` 和 `--depth-max-m` 只控制深度视频显示范围，不修改原始数据。

## 生成 CuRobo 配置

`generate_curobo_robot_config.py` 从机器人配置和 URDF 生成 collision YAML、XRDF 和 metrics：

```bash
uv run python scripts/generate_curobo_robot_config.py \
  --robot-config configs/robots/piper.yml \
  --output configs/robots/curobo/piper.yml
```

生成需要 CUDA。`--reuse-generated PATH --device cpu` 只能复核已有生成物的结构和 CPU 几何指标，不能替代真实 CuRobo load 与规划验收。
