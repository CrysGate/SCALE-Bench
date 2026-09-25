---
description: 抓起随机位置的 bottle 并直立放入固定槽位，采集单物体抓取与放置的专家轨迹。
---

<p class="page-kicker">MANIPULATION / 单物体操作</p>

# 单物体抓取与放置

抓起随机位置的 bottle，将其直立放入固定目标槽位。

<div class="task-tags"><span>推荐入门</span><span>抓取与放置</span><span>bottle</span></div>

## 任务配置

| 项目 | 配置 |
| --- | --- |
| 任务标识 | `single_object_pick_and_place` |
| 操作物体 | bottle |
| 任务配置 | [single_object_pick_and_place.yml](https://github.com/CrysGate/SCALE-Bench/blob/main/configs/tasks/single_object_pick_and_place.yml) |

!!! info "运行准备"

    完成 [环境与资产准备](../getting-started.md#environment)，并准备 bottle 资产及对应的 Piper 抓取数据。

## 专家数据采集 { #collect }

从仓库根目录采集一个 episode：

```bash title="专家数据采集"
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --num-envs 1 \
  --episodes 1 \
  --max-steps 1200 \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz none
```

## 检查结果

结束日志会给出实际 HDF5 文件路径和成功率。数据写入 `outputs/bottle-pick-place/`，同名数据集已存在时会自动使用新文件名。

成功与失败的 episode 都会保留。按 [数据浏览与回放指南](../getting-started.md#inspect) 打开本任务的数据，检查关节轨迹、动作和重新评测的结果。

[加入 RGB-D 相机观测](../getting-started.md#collect){ .md-button }
[浏览其他任务](index.md){ .md-button }
