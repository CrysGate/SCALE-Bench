---
description: 将五个套娃按高度排序到对应槽位，采集多物体抓取与放置轨迹。
---

# 套娃排序

将随机分布的五个套娃按高度从低到高放入对应槽位，默认沿桌面 Y 轴正方向排列。高度取自资产元数据；全部套娃同时满足各自槽位的[放置标准](index.md#success)才算成功。

[任务配置](https://github.com/CrysGate/SCALE-Bench/blob/main/configs/tasks/sort_dolls_by_size.yml)定义五个套娃资产及槽位位置。

## 采集一条轨迹 { #collect }

完成[环境与资产准备](../getting-started.md#environment)后运行：

```bash
uv run python scripts/run_demo_generation.py \
  --task sort_dolls_by_size \
  --record-output outputs/sort-dolls \
  --dataset-name sort_dolls_by_size \
  --viz none
```

按[数据浏览与回放](../getting-started.md#inspect)检查本次输出，回放时使用 `--task sort_dolls_by_size`。相机观测按[相机采集方式](../getting-started.md#collect)启用。
