---
description: 从多个奶茶杯中选出最大的一个并直立放入目标槽位，采集尺寸选择与放置的专家数据。
---

# 最大物体抓取与放置

从多个物体中选出最大的一个，并将它直立放入目标槽位。

## 任务配置

| 项目 | 配置 |
| --- | --- |
| 任务标识 | `largest_pick_and_place` |
| 默认物体 | 一个 800g、两个 500g 和两个 300g 奶茶杯资产 |
| 任务配置 | [largest_pick_and_place.yml](https://github.com/CrysGate/SCALE-Bench/blob/main/configs/tasks/largest_pick_and_place.yml) |

!!! info "运行准备"

    完成 [环境与资产准备](../getting-started.md#environment)，并准备任务配置引用的各尺寸奶茶杯资产及对应的 Piper 抓取数据。

## 专家数据采集 { #collect }

从仓库根目录采集一个 episode：

```bash title="专家数据采集"
uv run python scripts/run_demo_generation.py \
  --task largest_pick_and_place \
  --num-envs 1 \
  --episodes 1 \
  --max-steps 1200 \
  --record-output outputs/largest-pick-place \
  --dataset-name largest_pick_place \
  --viz none
```

## 检查结果

结束日志会给出实际 HDF5 文件路径和成功率。数据写入 `outputs/largest-pick-place/`，同名数据集已存在时会自动使用新文件名。

成功与失败的 episode 都会保留。通过 [数据浏览与回放](../getting-started.md#inspect) 检查录制结果；回放时将 `--task` 设置为 `largest_pick_and_place`。

[加入 RGB-D 相机观测](../getting-started.md#collect){ .md-button }
[浏览其他任务](index.md){ .md-button }
