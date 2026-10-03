---
description: 浏览 SCALE-Bench 资产规格和各机械臂的抓取数据。
---

# 资产图鉴

资产保存在 [ScaleBench-Data 的 Assets 目录](https://modelscope.cn/datasets/CrysGate/ScaleBench-Data/tree/master/Assets)，下载与链接方式见[资产准备](../getting-started.md#environment)。

| 资产 | 规格 | 使用任务 |
| --- | --- | --- |
| [奶茶杯](bubble_tea_cup.md) | 300g、500g、800g | [最大物体抓取与放置](../tasks/largest_pick_and_place.md) |

## 刚体资产

| 资产 | 编号 | Piper / ARX X5 抓取数据（每个规格） |
| --- | --- | --- |
| [垃圾桶](bucket.md) | 000、001 | 未提供 |
| [罐头](can.md) | 000、001 | 1024 / 1024 |
| [可乐](coca.md) | 000、001 | 1024 / 1024 |
| [齿轮](gear.md) | 000、001 | 未提供 |
| [香水瓶](perfume.md) | 000 | 1024 / 1024 |
| [洗发水瓶](shampoo.md) | 000、001 | 未提供 |
| [保温杯](thermos_cup.md) | 000、001 | 1024 / 1024 |
| [牙膏](toothpaste.md) | 000 | 1024 / 1024 |

## 抓取数据 { #grasps }

专家采集使用与物体 USD 同目录的 `grasps-<机器人名>.yaml`，例如 `grasps-piper.yaml`。抓取数据中的 TCP 和夹爪关节定义需与所选机器人配置一致。
