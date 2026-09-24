---
description: SCALE-Bench 操作任务的目标定义、配置入口与专家数据采集方式。
---

# 任务指南

当前提供三个操作任务，均支持确定性 seed、layout 导入导出和最终状态评测。

## 任务定义

| 任务 | `--task` 参数 | 操作目标 |
| --- | --- | --- |
| [套娃排序](sort_dolls_by_size.md) | `sort_dolls_by_size` | 五个套娃按尺寸排序到固定槽位 |
| [单物体抓取与放置](single_object_pick_and_place.md) | `single_object_pick_and_place` | bottle 直立放入固定目标槽位 |
| [最大物体抓取与放置](largest_pick_and_place.md) | `largest_pick_and_place` | 选择最大的物体并直立放入目标槽位 |

首次运行建议使用单物体抓取与放置任务。套娃排序涉及多个物体的依次放置；最大物体抓取与放置默认使用不同尺寸的奶茶杯资产。

## 专家数据采集

所有任务使用 `scripts/run_demo_generation.py` 采集专家数据，通过 `--task` 选择任务。每个任务页提供一个环境、一个 episode 的完整命令。

!!! info "运行准备"

    先完成 [环境与资产准备](../getting-started.md#environment)。三个任务都需要任务配置引用的资产和对应的 Piper 抓取数据。

1. **准备场景**：确认资产路径和抓取数据，使用固定 seed 或已保存的 layout 复现场景。
2. **执行专家**：运行任务页的采集命令，保存关节状态、动作和评测结果；需要图像时加入 RGB-D 观测。
3. **检查结果**：根据结束日志打开实际 HDF5 文件，浏览数据或回放 episode。

[相机采集设置](../getting-started.md#collect){ .md-button }
[数据检查与回放](../getting-started.md#inspect){ .md-button }
