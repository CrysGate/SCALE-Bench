# OBJ -> USD 资产转换

[English](README.md)

`convert_obj_to_usd.py` 用 Isaac Sim 的 Asset Converter 批量处理 OBJ 资产，
并生成可直接用于刚体仿真的标准 USD。脚本还可以从 XLSX 元数据读取质量和
尺寸，按 `x/y/z` 三个轴分别缩放模型，并把对齐后的 OBJ 导出到单独目录。

## 运行环境

脚本需要 Isaac Sim 6.0.1 及项目依赖。运行时会以 headless 模式启动
`SimulationApp`，因此不能在 Isaac Sim 运行时初始化之前导入 `pxr` 或
`omni`。

```bash
uv run python src/assets_gen/convert_obj_to_usd.py \
  --assets-root ./assets \
  --folders ./assets/vase ./assets/mug \
  --metadata-xlsx ./assets/sample.xlsx \
  --output-root ./converted-obj \
  --usd-output-root ./converted-usd
```

如果不传 `--folders`，默认扫描 `<assets-root>/vase`；如果不传
`--metadata-xlsx`，默认使用 `<assets-root>/sample.xlsx`。默认输出目录是
`<assets-root>/../rigid assets`。这些默认值是相对路径，不依赖某台机器的用户
目录。

## 处理流程

1. 可选地在扫描目录中解压 ZIP。Git LFS pointer 会被识别并跳过，ZIP 成员路径
   会经过目录穿越检查。
2. 递归查找 OBJ，并按真实路径去重。
3. 使用 Asset Converter 直接从原始 OBJ 生成 USD，测量源 AABB，并读取匹配的元数据。
4. 创建固定拓扑：`/root/{_materials,visual,collision}`。源层级变换、物理尺寸缩放
   和 up-axis 对齐会烘焙进 visual/collision 网格；随后将网格 AABB 中心平移到
   `/root` 原点，使刚体 root 表示几何中心。
5. 在 `/root` 写入刚体、质量和 `scale_x/scale_y/scale_z`；在 collision 网格上设置
   PhysX 凸分解碰撞体；在 `/root` 写入 `real_x/real_y/real_z`。
6. 碰撞网格最多保留 500000 个三角面，凸分解使用 `maxConvexHulls=128`、
   `errorPercentage=0.010001`；略高于 0.01，避免 float32 舍入后低于凸分解
   下限。视觉网格不做简化。
7. 保存 `Aligned.usd`，生成 `metadata.json`，将引用的材质资源复制到 `textures/`
   并改写为相对路径，同时递归复制 MDL 的相对模块依赖；转换临时文件自动清理。对应的 `Aligned.obj` 导出到独立目录。

单个输入目录中的 USD 输出文件名固定为 `Aligned.usd`。导出的 OBJ 保持相对于
`--assets-root` 的目录结构，例如：

```text
assets/vase/001/model.obj
converted-usd/vase/001/Aligned.usd
converted-usd/vase/001/metadata.json
converted-usd/vase/001/textures/
converted-obj/vase/001/Aligned.obj
```

指定 `--usd-output-root` 后，每个资产目录与 Geniesim 示例一致，包含
`Aligned.usd`、`metadata.json` 和 `textures/`。未指定时仍在源 OBJ 目录输出，
保留源文件。已有 USD 默认跳过，重新生成包需要 `--force`。

生成的 JSON 使用 `physics.size`（最终 x/y/z 尺寸，单位米）、`physics.mass`
（实际采用的质量，单位 kg）和 `physics.friction`（与 USD 一致，当前为 1.0）。
这些值来自当前资产，不复制示例资产的数值。

## 元数据格式

脚本只读取工作簿的第一个 worksheet。第一行是表头，支持以下列名：

- 名称：`name`、`object`、`名称`、`物体`
- 质量：`mass(kg)`、`mass(g)`、`mass`、`weight`、`重量`、`质量`
- 尺寸：`x`、`y`、`z`

名称可以跨多行留空，脚本会沿用上一行的名称。
尺寸列的数值默认按厘米解释，可通过
`--dimension-unit m|cm|mm` 修改。质量列的单位优先从表头判断，
也可以通过 `--metadata-mass-unit auto|g|kg` 指定回退单位。

当元数据缺失时，使用 `--mass`（默认 `0.1 kg`）和 `--scale`（默认 `1.0`）作为
回退值。
每个轴独立计算缩放比例；缺失某个轴的尺寸时，仅该轴使用回退缩放。

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--assets-root PATH` | 资产根目录，默认 `assets` |
| `--folders PATH ...` | 要扫描的目录 |
| `--metadata-xlsx PATH` | 元数据工作簿 |
| `--output-root PATH` | 导出 OBJ 的根目录 |
| `--usd-output-root PATH` | USD 资产包根目录，保留源目录相对结构 |
| `--mass KG` | 缺少质量元数据时的回退质量 |
| `--scale VALUE` | 缺少尺寸元数据时的回退缩放 |
| `--force` | 覆盖已有 `Aligned.usd` |
| `--max-models N` | 最多成功转换的模型数，`0` 表示不限制 |
| `--extract-zips` | 转换前递归解压 ZIP |

`--scale-axis` 仅为兼容旧调用保留，当前始终按三个轴独立计算，传入非 `auto`
值会显示弃用警告。

## 注意事项

- Asset Converter 配置为合并网格；如果转换结果不是恰好一个 Mesh，脚本会
  拒绝继续，以避免生成错误的碰撞体。
- `Aligned.usd` 和 `Aligned.obj` 是同一批处理结果的一对文件。反向 OBJ 导出失败
  会将该资产计为失败，而不会报告为成功。
- 失败资产不会中断后续资产处理；程序结束时会输出找到、成功、跳过和
  失败数量。
