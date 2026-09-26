---
description: 浏览 SCALE-Bench 资产规格和各机械臂的抓取数据。
---

# 资产图鉴

资产保存在 [ScaleBench-Data 的 Assets 目录](https://modelscope.cn/datasets/CrysGate/ScaleBench-Data/tree/master/Assets)，下载与链接方式见[资产准备](../getting-started.md#environment)。

| 资产 | 规格 | 使用任务 |
| --- | --- | --- |
| [奶茶杯](bubble_tea_cup.md) | 300g、500g、800g | [最大物体抓取与放置](../tasks/largest_pick_and_place.md) |
| [场景物品](scene_props.md) | 厨房模块、果碗、键盘、鼠标、花瓶、双规格空盒与花盆 | 三场景背景及代表物品抓取放置 |

## 抓取数据

专家采集使用与物体 USD 同目录的 `grasps-<机器人名>.yaml`，例如 `grasps-piper.yaml`。抓取数据中的 TCP 和夹爪关节定义需与所选机器人配置一致。

每种规格、每种机械臂的抓取数据目标为 **1024 条**。资产页按核对日期记录可加载的候选数量；任务执行成功率需通过实际运行评测。
