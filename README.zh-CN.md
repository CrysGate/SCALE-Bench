# SCALE-Bench

[English](README.md) | [简体中文](README.zh-CN.md) | [在线文档](https://crysgate.github.io/SCALE-Bench/)

SCALE-Bench 是基于 Isaac Lab 的双臂操作基准，用于运行桌面操作任务和采集专家演示数据。它提供场景预览、CuRobo 运动规划、任务成功评测，以及 HDF5 数据浏览和回放。

## 操作任务

| 任务 | 目标 |
| --- | --- |
| [单物体抓取与放置](docs/tasks/single_object_pick_and_place.md) | 将随机位置的瓶子直立放入固定槽位 |
| [套娃排序](docs/tasks/sort_dolls_by_size.md) | 将五个套娃按高度从低到高放入对应槽位 |
| [最大物体抓取与放置](docs/tasks/largest_pick_and_place.md) | 选择最高的物体并放入目标槽位，默认使用奶茶杯 |

任务通过种子和布局文件复现场景，机器人、相机和任务配置使用 YAML 管理。

## 开始使用

先完成[环境与资产准备](https://crysgate.github.io/SCALE-Bench/getting-started/#environment)。资产托管在 [ScaleBench-Data](https://modelscope.cn/datasets/CrysGate/ScaleBench-Data)，通过项目根目录的 `Assets` 软链接使用。

预览单物体任务：

```bash
uv run python scripts/preview_scene.py --task single_object_pick_and_place
```

采集一条专家轨迹：

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz none
```

结果保存为 HDF5，包含关节状态、动作和评测结果。后续操作见[相机采集、数据浏览与回放](https://crysgate.github.io/SCALE-Bench/getting-started/#collect)。

## 更多用法

- [任务指南](docs/tasks/index.md)：任务定义与成功条件。
- [资产图鉴](docs/assets/index.md)：资产规格与抓取数据。
- [脚本用法](scripts/README.md)：布局复现、批量采集、调试和视频导出。
- [OBJ 转 USD](src/assets_gen/README.zh-CN.md)：转换自己的物体资产。
- [文档规范](DOCUMENTATION.md)：内容取舍、页面分工和文档验证。

## 许可证

[MIT License](LICENSE)
