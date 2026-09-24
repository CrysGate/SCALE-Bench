---
title: 项目概览
description: SCALE-Bench 是配置驱动的 Isaac Lab 双臂操作项目，提供可复现任务、专家数据采集和 episode 回放。
hide:
  - navigation
  - toc
  - footer
---

<div class="research-home" markdown>
<div class="project-header" markdown>
<div markdown>
<p class="project-label">机器人操作 · 仿真实验 · 专家数据</p>

# SCALE-Bench

<p class="project-lead">Isaac Lab 双臂操作任务与专家数据采集</p>

<p class="project-description">通过配置定义机器人、场景与任务，支持确定性布局、CuRobo 运动规划、专家轨迹采集和回放评测，用于开展可复现的机器人操作实验。</p>

<p class="project-links" markdown>
[开始使用](getting-started.md){ .md-button .md-button--primary }
[GitHub 仓库](https://github.com/CrysGate/SCALE-Bench){ .md-button }
</p>
</div>
<div class="project-meta">
  <dl>
    <dt>仿真环境</dt><dd>Isaac Lab</dd>
    <dt>运动规划</dt><dd>CuRobo</dd>
    <dt>机器人</dt><dd>双臂 Piper</dd>
    <dt>数据格式</dt><dd>HDF5</dd>
  </dl>
</div>
</div>

## 操作任务 { #tasks }

当前提供三个任务，共享专家执行、评测与记录链路。任务页包含目标定义、配置文件和完整采集命令。

<div class="task-list" markdown>
<div class="task-row" markdown>
<div markdown>
### [套娃排序](tasks/sort_dolls_by_size.md)

`sort_dolls_by_size`
</div>

将五个套娃按尺寸从小到大排列到桌面上的固定槽位。

[采集命令 →](tasks/sort_dolls_by_size.md#collect)
</div>
<div class="task-row" markdown>
<div markdown>
### [单物体抓取与放置](tasks/single_object_pick_and_place.md)

`single_object_pick_and_place`
</div>

抓起随机位置的 bottle，将其直立放入固定目标槽位。

[采集命令 →](tasks/single_object_pick_and_place.md#collect)
</div>
<div class="task-row" markdown>
<div markdown>
### [最大物体抓取与放置](tasks/largest_pick_and_place.md)

`largest_pick_and_place`
</div>

从多个物体中选出最大的一个并直立放入目标槽位，默认使用奶茶杯资产。

[采集命令 →](tasks/largest_pick_and_place.md#collect)
</div>
</div>

<div class="research-columns" markdown>
<div markdown>
## 实验流程

1. **准备环境与资产**。安装项目依赖，准备任务物体和对应的 Piper 抓取数据。[环境说明](getting-started.md#environment)
2. **预览并采集**。检查场景，选择任务并运行专家链路，按需加入 RGB-D 相机观测。[采集设置](getting-started.md#collect)
3. **检查并回放**。查看实际 HDF5 文件，恢复初态、重放 action 并重新评测。[结果检查](getting-started.md#inspect)
</div>
<div markdown>
## 配置与复现

- **配置驱动**：机器人、相机、场景、任务、仿真和环境参数保存在 YAML 中。
- **确定性布局**：支持 seed 和 layout 导入导出，用于恢复同一个实验场景。
- **数据记录**：保存初始状态、关节动作、评测结果和终止原因，支持 episode 回放检查。

[完整脚本说明 →](https://github.com/CrysGate/SCALE-Bench/blob/main/scripts/README.md)
</div>
</div>
</div>
