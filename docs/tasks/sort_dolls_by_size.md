---
description: 将五个套娃按尺寸从小到大排列，运行套娃排序任务并采集专家数据。
---

# 套娃排序

将五个套娃按尺寸从小到大排列到桌面上的固定槽位。

## 任务配置

| 项目 | 配置 |
| --- | --- |
| 任务标识 | `sort_dolls_by_size` |
| 操作物体 | 五个不同尺寸的套娃 |
| 任务配置 | [sort_dolls_by_size.yml](https://github.com/CrysGate/SCALE-Bench/blob/main/configs/tasks/sort_dolls_by_size.yml) |

!!! info "运行准备"

    完成 [环境与资产准备](../getting-started.md#environment)，并准备任务配置引用的套娃资产及对应的 Piper 抓取数据。

## 专家数据采集 { #collect }

从仓库根目录采集一个 episode：

```bash title="专家数据采集"
uv run python scripts/run_demo_generation.py \
  --task sort_dolls_by_size \
  --num-envs 1 \
  --episodes 1 \
  --max-steps 1200 \
  --record-output outputs/sort-dolls \
  --dataset-name sort_dolls_by_size \
  --viz none
```

## 检查结果

结束日志会给出实际 HDF5 文件路径和成功率。数据写入 `outputs/sort-dolls/`，同名数据集已存在时会自动使用新文件名。

成功与失败的 episode 都会保留。通过 [数据浏览与回放](../getting-started.md#inspect) 检查录制结果；回放时将 `--task` 设置为 `sort_dolls_by_size`。

[加入 RGB-D 相机观测](../getting-started.md#collect){ .md-button }
[浏览其他任务](index.md){ .md-button }
