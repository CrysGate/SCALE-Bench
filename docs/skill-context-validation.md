# Skill Context 职责拆分验收

日期：2026-09-20。使用当前工作区的真实 Isaac Lab + CuRobo 链路，没有编写单元测试。

## 职责

- `IsaacLabSkillContext` 读取实时机器人和物体状态，并转发抓取候选请求。
- `IsaacLabGraspCandidates` 加载资产文件中的全部候选，或获取在线来源的有效候选，按分数排序。
- `AnyGraspSource` 封装 RGB-D 采集、相机恢复、推理、来源几何过滤和诊断。几何过滤检查分数、夹爪开度、目标包围盒、桌面净空和开合轴方向。

Context 的最小夹爪开度检查属于机器人测量有效性约定；抬升、滑移等物理验证由技能层执行，最终任务成功由任务 evaluator 判断。

## 真实数据与运行结果

任务为 `single_object_pick_and_place`，使用默认 Piper 机器人，seed 101。

| 来源 | 候选数据 | 完整任务结果 |
| --- | --- | --- |
| asset | bottle 的 `grasps.yaml` 包含 357 个候选；实际选中 331，其物体系 TCP Z 为 -0.035792 m | 254 步，`success=True`、`goal_reached`，退出码 0 |
| AnyGrasp | 29,174 个目标点，82 个检测中 53 个开合轴方向不合格，29 个有效；有效候选中 10 个 TCP Z 为负，最小 Z 为 -0.0886 m；实际选中 9 | 55 步失败：预抓取完成，grasp 与 recover_retreat 均为 `PATH_CONSTRAINT_FAILED`，退出码 1 |

AnyGrasp 协议 v3 健康检查正常，在线失败发生在运动规划阶段。以上结果验证了候选读取、在线推理与实际技能执行，不代表所有候选均可完成任务。修改文件的 Python 编译检查与 `git diff --check` 通过。

## 复现

```bash
HEADLESS=1 .venv/bin/python scripts/run_demo_generation.py \
  --task single_object_pick_and_place --base-seed 101 \
  --num-envs 1 --episodes 1 --max-steps 1200 \
  --camera-config configs/cameras/d435_smoke.yml --viz none \
  --record-output outputs/skill-context-refactor-final --dataset-name asset-seed101 \
  --log-file outputs/skill-context-refactor-final/asset-seed101.jsonl

HEADLESS=1 .venv/bin/python scripts/run_demo_generation.py \
  --task single_object_pick_and_place --grasp-source anygrasp --base-seed 101 \
  --num-envs 1 --episodes 1 --max-steps 1200 --viz kit \
  --record-output outputs/skill-context-refactor-final --dataset-name anygrasp-seed101 \
  --log-file outputs/skill-context-refactor-final/anygrasp-seed101.jsonl
```

产物：[离线轨迹](../outputs/skill-context-refactor-final/asset-seed101.hdf5)、[离线分段日志](../outputs/skill-context-refactor-final/asset-seed101.segments.jsonl)、[在线轨迹](../outputs/skill-context-refactor-final/anygrasp-seed101.hdf5)、[在线诊断与执行日志](../outputs/skill-context-refactor-final/anygrasp-seed101.jsonl)。
