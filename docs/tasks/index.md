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

## 成功判定 { #success }

物体需要放到指定位置并保持直立。当前默认配置采用以下放置标准，任务页说明哪些物体必须满足这些条件：

| 判定项 | 允许范围 |
| --- | --- |
| 水平位置误差 | 不超过 2.5 cm |
| 高度误差 | 不超过 1.5 cm |
| 偏离直立方向的角度 | 不超过 0.10 rad（约 5.7°） |
| 成功验证 | 连续 10 个验证步满足条件，结束时仍满足 |

调整标准时，在任务 YAML 的 `target_slot`（套娃为 `target_slots`）中设置 `position_tolerance_m`、`height_tolerance_m` 和 `upright_tolerance_rad`；连续验证步数由 `success_stability_steps` 设置。
