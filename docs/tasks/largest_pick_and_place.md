---
description: 从同类物体中选出最大的一个，直立放到蓝色交付垫中央，支持奶茶杯和套娃。
---

# 最大物体抓取与放置

从同类、不同尺寸的物体中选择最大的一个，并将其直立放到蓝色交付垫中央。“最大”按资产元数据中的高度判定，最高者必须唯一。

默认场景包含一个 800g、两个 500g 和两个 300g [奶茶杯](../assets/bubble_tea_cup.md)，目标为 800g 杯，可用于模拟大杯订单出杯。套娃版本使用 `matryoshka_dolls/00000–00004`，五个相同外观的套娃高度分别为 13、11、9、7、5 cm，可用于挑选最大规格的商品并交付。两种版本共用指令与成功规则，按选中物体是否满足[放置标准](index.md#success)判定。

[默认配置](https://github.com/CrysGate/SCALE-Bench/blob/main/configs/tasks/largest_pick_and_place/default.yml)定义物体集合、布局、交付位置和成功条件。交付垫是相机可见的桌面标记，白色十字表示目标中心；垫子大小根据目标物体尺寸与位置容差确定。物体在垫子 Y 轴正方向一侧生成，初始摆放区边界与垫子边缘至少相隔 `minimum_source_target_gap_m`，默认 16 cm。预览中的绿色框表示该初始摆放区。

使用套娃版本或替换物体时见[选择任务配置与物体](index.md#variants)。可以通过 `--object-set` 换用其他同类物体的五个尺寸版本，无需修改选择或放置逻辑；尺寸元数据必须齐备，专家采集还需要最大物体对应机器人的抓取文件。

预览第二组相同外观、不同尺寸的套娃 `00005–00009`：

```bash
uv run python scripts/preview_scene.py \
  --task largest_pick_and_place \
  --task-config configs/tasks/largest_pick_and_place/matryoshka.yml \
  --object-set configs/tasks/object_sets/matryoshka_00005_00009.yml
```

## 批量采集 50 条轨迹 { #collect }

完成[环境与资产准备](../getting-started.md#environment)后，使用 25 个并行环境运行 50 个 episode：

```bash
uv run python scripts/run_demo_generation.py \
  --gpus all \
  --task largest_pick_and_place \
  --num-envs 25 \
  --episodes 50 \
  --record-output outputs/largest-pick-place \
  --dataset-name largest_pick_place \
  --viz none
```

按[数据浏览与回放](../getting-started.md#inspect)检查输出，回放时使用 `--task largest_pick_and_place`。

## 采集相机观测

```bash
HEADLESS=1 uv run python scripts/run_demo_generation.py \
  --gpus all \
  --task largest_pick_and_place \
  --num-envs 40 \
  --episodes 800 \
  --record-output outputs/largest_pick_and_place \
  --dataset-name largest_pick_and_place \
  --viz kit \
  --record-camera-observations
```
