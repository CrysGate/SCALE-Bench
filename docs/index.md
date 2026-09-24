# ScaleBench

ScaleBench 是基于 Isaac Lab 的双臂操作项目。这里提供三个任务的目标说明和专家数据采集命令。

运行命令前，先按[项目安装说明](https://github.com/CrysGate/learn-isaac/blob/main/README.zh-CN.md#环境)准备环境和未纳入 Git 的 `Assets/` 资产包。以下命令都从仓库根目录执行，数据写入 `outputs/`。

## 任务

- [套娃排序](tasks/sort_dolls_by_size.md)
- [单物体抓取与放置](tasks/single_object_pick_and_place.md)
- [最大物体抓取与放置](tasks/largest_pick_and_place.md)

任务页中的命令默认只记录关节状态、动作和评测结果。需要同时记录 RGB-D 相机数据时，在命令前加 `HEADLESS=1`，将 `--viz none` 改为 `--viz kit`，并追加 `--record-camera-observations`。

本地预览文档：

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.6.20 mkdocs serve
```
