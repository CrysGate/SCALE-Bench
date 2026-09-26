---
description: 选择最高的奶茶杯并直立放入目标槽位，采集目标选择与放置轨迹。
---

# 最大物体抓取与放置

从多个物体中选择最高的一个，并将其直立放入固定目标槽位。“最大”按资产元数据中的高度判定。

默认场景包含一个 800g、两个 500g 和两个 300g [奶茶杯](../assets/bubble_tea_cup.md)，目标为 800g 杯。其余杯子作为干扰物，成功按目标杯是否满足[放置标准](index.md#success)判定。

[默认配置](https://github.com/CrysGate/SCALE-Bench/blob/main/configs/tasks/largest_pick_and_place/default.yml)定义物体集合、布局、目标槽位和成功条件。使用套娃版本或替换物体时见[选择任务配置与物体](index.md#variants)。

## 采集一条轨迹 { #collect }

完成[环境与资产准备](../getting-started.md#environment)后运行：

```bash
uv run python scripts/run_demo_generation.py \
  --task largest_pick_and_place \
  --record-output outputs/largest-pick-place \
  --dataset-name largest_pick_place \
  --viz none
```

按[数据浏览与回放](../getting-started.md#inspect)检查本次输出，回放时使用 `--task largest_pick_and_place`。扩大采集规模时参考[批量采集](https://github.com/CrysGate/SCALE-Bench/blob/main/scripts/README.md#批量采集)，相机观测按[相机采集方式](../getting-started.md#collect)启用。
