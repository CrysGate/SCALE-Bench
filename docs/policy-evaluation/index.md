# 模型评测

SCALE-Bench 负责仿真、观测、动作执行和任务评分；[XPolicyLab](https://github.com/XPolicyLab/XPolicyLab) 负责加载模型并提供推理服务。两端通过 WebSocket 交换 MessagePack 数据，各自使用独立 Python 环境，可以部署在不同机器上。客户端不导入 XPolicyLab 代码，也不需要本地存在该仓库。

## 首次联调

使用 XPolicyLab 自带的 `demo_policy` 检查服务通信、仿真动作执行和结果保存，无需模型权重。

先完成[仿真环境与资产准备](../getting-started.md#environment)，然后安装客户端的通信依赖。以下命令都从项目根目录执行：

```bash
uv sync --frozen --extra policy
```

初始化固定版本的服务端子模块，并为上游 `demo_policy` 创建独立环境：

```bash
git submodule update --init XPolicyLab
uv venv XPolicyLab/.venv --python 3.12
uv pip install --python XPolicyLab/.venv/bin/python -e ./XPolicyLab

XPolicyLab/.venv/bin/python scripts/prepare_xpolicylab.py \
  --robot-config configs/robots/piper.yml --env-cfg-type piper --num-envs 1

XPolicyLab/.venv/bin/python -m client_server.ws \
  --config-path configs/policies/demo_server.yml
```

`prepare_xpolicylab.py` 从机器人配置生成上游模型适配器需要的关节维数和批量大小，写入 `env_cfg/`。重复执行会更新所选名称的配置，保留其他机器人条目。此步骤用于服务端部署；不要求 Isaac 或 USD 资产。

保持服务端运行，在另一个终端执行：

```bash
uv run --frozen --extra policy python scripts/run_policy_evaluation.py \
  --task largest_pick_and_place \
  --episodes 1 --max-steps 8 \
  --camera-config configs/cameras/d435_smoke.yml \
  --output-dir outputs/xpolicylab-demo \
  --record-camera-observations --viz none
```

结果写入 `outputs/xpolicylab-demo/results.json`，轨迹和 RGB-D 写入同目录的 `episodes.hdf5`。输出目录必须尚不存在；再次运行时换一个目录。`demo_policy` 只返回零关节目标，预期会达到步数上限，不能用它的成功率代表模型能力。

## 评测实际模型

按照所选模型在 XPolicyLab 中的 README，在独立环境安装依赖并配置 checkpoint。服务端使用 `action_type: joint`，`env_cfg_type` 对应上一步生成的名称；`task_name`、机器人配置和评测批量大小应与客户端一致。模型自身的部署配置保留在服务端。

客户端使用自己的 `configs/policies/xpolicylab.yml` 配置服务地址、相机映射和动作序列执行长度。例如，连接另一台机器上的服务：

```bash
uv run --frozen --extra policy python scripts/run_policy_evaluation.py \
  --task largest_pick_and_place \
  --server-url ws://192.168.1.10:19000 \
  --episodes 20 --base-seed 100 --max-steps 1200 \
  --output-dir outputs/largest-policy-run \
  --viz none
```

将地址替换为服务端 IP；远程部署时，服务端需绑定可访问的接口，例如 `--host 0.0.0.0`。相机默认使用正式分辨率，按 checkpoint 的训练设置选择相机配置。

模型实现了 `update_obs_batch` 和 `get_action_batch`，并按 `env_idx` 隔离状态时，可以增加 `--inference-mode batch --num-envs 2`。服务端生成配置时也使用 `--num-envs 2`。默认单环境模式兼容只实现单条推理接口的模型。

每批 episode 开始前重置模型状态，所有活动环境结束后再分配下一批。完成的环境不再向模型请求动作。一个有状态的服务实例应只供一个评测进程使用。

## 观测与动作约定

客户端只发送相机、机器人关节状态、任务指令和控制频率。评分使用的物体真值与目标位置不进入模型观测。

| XPolicyLab 字段 | SCALE-Bench 内容 |
| --- | --- |
| `vision.cam_head` | 俯视相机 |
| `vision.cam_left_wrist`、`vision.cam_right_wrist` | 左、右腕部相机 |
| `state.left_arm_joint_state`、`state.right_arm_joint_state` | 机器人配置中 `arm_joint_names` 顺序的绝对关节角，单位 rad |
| `state.left_ee_joint_state`、`state.right_ee_joint_state` | `command_joint_names` 顺序的夹爪关节位置，不含被动模仿关节 |
| `instruction` | 当前任务的自然语言指令 |
| `env_idx` | 当前批次内的环境编号 |
| `additional_info.frequency` | 仿真控制频率，单位 Hz |

颜色是 `uint8`、HWC、RGB 数组；默认同时发送深度，单位 m。只使用 RGB 的模型可在客户端配置中设置 `send_depth: false`，减少传输量。相机名称可通过 `camera_map` 匹配模型输入。

一个动作是包含上表四个关节状态字段的字典，一次推理返回非空动作列表；批量推理返回与请求环境编号顺序一致的动作列表集合。动作是绝对位置目标：机械臂以 rad 表示；当前 Piper 和 X5 夹爪以 m 表示。夹爪全开值从机器人配置读取，分别为 0.05 m 和 0.044 m，全闭为 0 m；这些值是主动关节位移，不是双指总开口宽度。客户端不进行归一化、增量累加或末端位姿转换，checkpoint 的观测和输出必须匹配这一约定。

客户端在每个控制步发送观测，按返回顺序执行动作序列，最多执行配置中的 `action_steps` 个动作后重新推理。每个动作执行一个控制步，控制周期由 `physics_dt_s × control_decimation` 决定，默认约为 30 Hz；正式评测前应与模型训练频率对齐。

## 结果与录制

`results.json` 保存种子、初始布局、解析后的运行配置、每个 episode 的成功标记、进度、任务指标、终止原因和步数，并汇总成功率。任务成功沿用项目现有的几何与稳定性判定，不由模型决定；各任务的判定条件见[任务指南](../tasks/index.md)。

默认仅写评测结果；`--record` 增加关节和动作 HDF5，`--record-camera-observations` 同时启用 RGB-D 录制。录制文件为输出目录下的 `episodes.hdf5`，可用[数据浏览与回放工具](https://github.com/CrysGate/SCALE-Bench/blob/main/scripts/README.md#浏览与回放数据)检查动作。

运行完成时 `status` 为 `completed`，进程退出码为 0，即使模型没有完成任务。服务错误、连接中断或超时会中止评测并标为 `error`，退出码非 0，不生成完整成功率。仅在初次连接、等待模型加载时重试；推理开始后不自动重发调用或连接到重启后的模型。

`env_cfg/` 只提供当前推理适配器所需的元数据。训练数据转换、模型微调和末端位姿控制不在这条关节推理链路中。
