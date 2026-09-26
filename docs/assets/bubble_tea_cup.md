---
description: 奶茶杯的尺寸、质量与 Piper、ARX X5 抓取数据。
---

# 奶茶杯

`bubble_tea_cup` 提供 300g、500g、800g 三种规格，用于[最大物体抓取与放置](../tasks/largest_pick_and_place.md)。资产目录为 `Assets/Object/Rigid/bubble_tea_cup/`，各规格分别保存 USD 和抓取文件。

## 外观与规格

=== "正面"

    [![300g、500g、800g 奶茶杯正面及尺寸](objects/bubble_tea_cup/front.png)](objects/bubble_tea_cup/front.png)

=== "侧面"

    [![300g、500g、800g 奶茶杯侧面及尺寸](objects/bubble_tea_cup/side.png)](objects/bubble_tea_cup/side.png)

=== "俯视图"

    [![300g、500g、800g 奶茶杯俯视图及尺寸](objects/bubble_tea_cup/top.png)](objects/bubble_tea_cup/top.png)

| 规格 | 宽 × 深 × 高（cm） | 质量（kg） |
| --- | --- | --- |
| 300g | 9 × 9 × 13.5 | 0.3 |
| 500g | 9 × 9 × 15 | 0.5 |
| 800g | 10 × 10 × 18 | 0.8 |

尺寸与质量取自各规格的 `metadata.json`。三种资产的摩擦系数均为 1.0，使用凸分解碰撞体。

## 抓取数据

核对日期：2026-09-25。每个规格、每种机械臂的目标均为 1024 条。

| 规格 | Piper | ARX X5 |
| --- | --- | --- |
| 300g | 1024 | 548 |
| 500g | 1024 | 587 |
| 800g | 1024 | 68 |
