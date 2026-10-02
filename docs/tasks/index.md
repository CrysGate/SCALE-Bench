---
description: 选择 SCALE-Bench 操作任务，了解任务目标和成功条件。
---

# 任务指南

首次运行可从单物体抓取与放置开始；套娃排序增加了多物体操作，最大物体任务增加了目标选择。

| 任务 | 目标 |
| --- | --- |
| [单物体抓取与放置](single_object_pick_and_place.md) | 将瓶子直立放入固定槽位 |
| [套娃排序](sort_dolls_by_size.md) | 将五个套娃按高度排序到对应槽位 |
| [最大物体抓取与放置](largest_pick_and_place.md) | 将最高的物体直立放入目标槽位 |

各任务页提供采集命令。环境、资产和相机采集的准备步骤见[开始使用](../getting-started.md)。

## 选择任务配置与物体 { #variants }

任务配置位于 `configs/tasks/<任务名>/`，省略 `--task-config` 时使用该目录的 `default.yml`。例如，预览最大物体抓放的套娃版本：

```bash
uv run python scripts/preview_scene.py \
  --task largest_pick_and_place \
  --task-config configs/tasks/largest_pick_and_place/matryoshka.yml
```

替换物体时，使用 `--object-set configs/tasks/object_sets/matryoshka_5.yml` 覆盖配置中的物体集合。模型指令在任务 YAML 的 `instruction` 中设置；若指令指定了物体类别或数量，需与替换后的集合一致。

两个参数同样适用于专家采集、技能调试、策略链路验证和回放。专家采集与技能调试要求目标物体具备对应机器人的[抓取文件](../assets/index.md)。

物体集合维护实例名称、资产路径和物理参数，可供不同任务引用。新增任务配置版本时，在对应任务目录中添加 YAML 并通过 `--task-config <配置文件路径>` 使用；其中的 `task` 必须与 `--task` 一致。配置中的 `object_set` 路径相对于该配置文件解析，命令行路径相对于当前目录解析。

物体实例名称必须唯一，同一资产可以出现多次。单物体任务需要一个实例；最大物体任务需要至少两个候选且最高者唯一；排序需要至少两个高度不同的物体，槽位数量与物体数量一致，并沿 Y 轴正方向排列。

回放和导入布局时，使用与生成时一致的任务配置、物体集合及资产文件。布局 JSON 保存位姿，不包含资产和任务配置快照。

## 成功判定 { #success }

默认放置标准如下，任务页说明哪些物体必须满足这些条件：

| 判定项 | 允许范围 |
| --- | --- |
| 水平位置误差 | 不超过 2.5 cm |
| 高度误差 | 不超过 1.5 cm |
| 偏离直立方向的角度 | 不超过 0.10 rad（约 5.7°） |
| 成功验证 | 连续 10 个验证步满足条件，结束时仍满足 |

调整标准时，在任务 YAML 顶层设置 `position_tolerance_m`、`height_tolerance_m` 和 `upright_tolerance_rad`；连续验证步数由 `success_stability_steps` 设置。槽位坐标在同一文件的 `target_positions_env_xy_m` 中设置，单位为米，使用单环境局部世界坐标系。
