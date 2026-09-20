# Skill Context 职责拆分验收

日期：2026-09-20。使用当前工作区的真实 Isaac Lab + CuRobo 链路，没有编写单元测试。

## 职责与任务规则

- `IsaacLabSkillContext` 从 1,113 行缩减为 247 行，读取实时机器人和物体状态，并转发抓取候选请求。
- `IsaacLabGraspCandidates` 加载资产候选、选择来源并调用任务的 `allows_grasp`。
- `AnyGraspSource` 封装 RGB-D 采集、相机恢复、推理、来源几何过滤和诊断；只接收准入回调，不依赖具体任务。
- `SingleObjectPickAndPlace.allows_grasp` 要求 `tcp_pose_object.position_m[2] >= 0`；asset、AnyGrasp 和在线诊断共用这个定义。任务规则拒绝使用 `rejected_task_rule`，旧 `rejected_tcp_height` 枚举仅保留用于读取已保存的 Open3D 数据。

Context 的最小夹爪开度检查属于机器人测量有效性约定；抬升、滑移等物理验证由技能层执行，最终任务成功由任务 evaluator 判断。

## 真实数据与运行结果

使用默认 Piper 机器人和 bottle 的实际 `grasps.yaml`：357 个候选中 21 个满足上半部规则，336 个被拒绝。允许候选的最小物体系 TCP Z 为 0.004546 m，被拒绝候选的最大 Z 为 -0.000804 m。候选 ID、分数和位姿保留来源值。

AnyGrasp 协议 v3 健康检查正常。seed 101 实际相机采集得到 29,174 个目标点，返回 82 个候选：53 个开合轴方向不合格，10 个被任务规则拒绝，19 个有效。有效候选最小物体系 TCP Z 为 0.002550 m，任务拒绝候选最大 Z 为 -0.026775 m。诊断和完整任务日志的过滤计数一致。

| 来源 | Seed | 完整任务结果 |
| --- | --- | --- |
| asset | 101 | 75 步失败：候选 245 的预抓取完成，grasp 为 `PATH_CONSTRAINT_FAILED`，recover_retreat 三次规划均为 `PLANNER_NO_RESULT` |
| asset | 102 | 候选 356；294 步，`success=True`、`goal_reached`，进程退出码 0 |
| AnyGrasp | 101 | 候选 71；294 步，`success=True`、`goal_reached`，进程退出码 0 |

统一规则会收紧离线候选集并改变实际选择；上述结果不能视为所有布局均可成功。asset seed 101 的失败仍需要在运动规划/恢复链路中进一步分析。

## 复现

```bash
HEADLESS=1 .venv/bin/python scripts/run_demo_generation.py \
  --task single_object_pick_and_place --base-seed 102 \
  --num-envs 1 --episodes 1 --max-steps 1200 \
  --camera-config configs/cameras/d435_smoke.yml --viz none \
  --record-output outputs/skill-context-refactor --dataset-name asset-seed102 \
  --log-file outputs/skill-context-refactor/asset-seed102.jsonl

HEADLESS=1 .venv/bin/python scripts/run_demo_generation.py \
  --task single_object_pick_and_place --grasp-source anygrasp --base-seed 101 \
  --num-envs 1 --episodes 1 --max-steps 1200 --viz kit \
  --record-output outputs/skill-context-refactor --dataset-name anygrasp-seed101 \
  --log-file outputs/skill-context-refactor/anygrasp-seed101.jsonl

HEADLESS=1 .venv/bin/python scripts/run_grasp_diagnostics.py \
  --task single_object_pick_and_place --seed 101 --viz kit \
  --diagnostics-output outputs/skill-context-refactor/anygrasp-seed101.json
```

asset seed 101 使用第一个命令，将 seed、dataset 和 log 文件名中的 102 改为 101。

产物：[离线成功轨迹](../outputs/skill-context-refactor/asset-seed102.hdf5)、[离线失败日志](../outputs/skill-context-refactor/asset-seed101.segments.jsonl)、[在线成功轨迹](../outputs/skill-context-refactor/anygrasp-seed101.hdf5)、[在线诊断](../outputs/skill-context-refactor/anygrasp-seed101.json)。修改文件的 Python 编译检查与 `git diff --check` 通过。
