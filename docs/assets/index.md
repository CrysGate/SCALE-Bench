---
description: 浏览 SCALE-Bench 资产规格和各机械臂的抓取数据。
---

# 资产图鉴

资产保存在 [ScaleBench-Data 的 Assets 目录](https://modelscope.cn/datasets/CrysGate/ScaleBench-Data/tree/master/Assets)，下载与链接方式见[资产准备](../getting-started.md#environment)。

| 资产 | 规格 | 使用任务 |
| --- | --- | --- |
| [奶茶杯](bubble_tea_cup.md) | 300g、500g、800g | [最大物体抓取与放置](../tasks/largest_pick_and_place.md) |

## 材质与灯光 {#appearance}

可选外观池包含以下 [Poly Haven](https://polyhaven.com/) 资源：

| 用途 | 资源 | 规格 |
| --- | --- | --- |
| 桌面 | `wood_table_001`、`wood_table`、`kitchen_wood`、`plywood`、`oak_veneer_01`、`walnut_veneer` | 2K 色彩、OpenGL 法线、粗糙度 JPG |
| 地板 | `laminate_floor_02`、`wood_floor`、`floor_tiles_06`、`concrete_floor_02`、`terrazzo_tiles`、`rubber_tiles`、`marble_01`、`granite_tile` | 2K 色彩、OpenGL 法线、粗糙度 JPG |
| 室内灯光 | `small_empty_room_1`、`carpentry_shop_02`、`studio_small_09`、`brown_photostudio_03`、`art_studio`、`empty_workshop`、`unfinished_office`、`white_studio_02` | 4K HDRI |

在项目根目录运行 `uv run python scripts/download_appearance_assets.py`，约下载 300 MB。每种材质的 MDL 与贴图一起保存在 `Assets/Material/PolyHaven/<名称>/`，HDRI 位于 `Assets/Background/PolyHaven/`。脚本校验文件大小与 MD5，重复运行会跳过校验通过的贴图，并重新生成 MDL；手工修改的 MDL 会被覆盖。`configs/appearance/polyhaven.yml` 保存材质与灯光池配置及资产引用。

资源采用 [CC0 1.0](https://polyhaven.com/license)，可用于仿真、数据生成及商业用途。`Assets/PolyHaven_appearance_manifest.json` 保存每项来源、作者及下载校验信息。批次选择、预览和回放用法见[材质与灯光操作说明](https://github.com/CrysGate/SCALE-Bench/blob/main/scripts/README.md#材质与灯光)。

## 抓取数据

专家采集使用与物体 USD 同目录的 `grasps-<机器人名>.yaml`，例如 `grasps-piper.yaml`。抓取数据中的 TCP 和夹爪关节定义需与所选机器人配置一致。

每种规格、每种机械臂的抓取数据目标为 **1024 条**。资产页按核对日期记录可加载的候选数量；任务执行成功率需通过实际运行评测。
