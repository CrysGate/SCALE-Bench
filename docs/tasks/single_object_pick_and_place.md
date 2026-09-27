---
description: 将随机位置的瓶子直立放入固定槽位，采集单物体抓取与放置轨迹。
---

# 单物体抓取与放置

抓起桌面上随机位置和朝向的瓶子，将其直立放入固定目标槽位。瓶子满足[放置标准](index.md#success)即为成功，适合作为第一次运行的任务。

[默认配置](https://github.com/CrysGate/SCALE-Bench/blob/main/configs/tasks/single_object_pick_and_place/default.yml)引用瓶子的物体集合并定义布局、目标槽位和成功条件。使用其他单物体集合时见[选择任务配置与物体](index.md#variants)。

## 采集一条轨迹 { #collect }

完成[环境与资产准备](../getting-started.md#environment)后运行：

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz none
```

后续按[数据浏览与回放](../getting-started.md#inspect)检查结果；需要图像时使用[相机采集方式](../getting-started.md#collect)。
