# OBJ -> USD 资产转换

[English](README.md)

`convert_obj_to_usd.py` 用 Isaac Sim 的 Asset Converter 批量处理 OBJ 资产，
并生成可直接用于刚体仿真的标准 USD。脚本还可以从 XLSX 元数据读取质量和
尺寸，按 `x/y/z` 三个轴分别缩放模型，并把对齐后的 OBJ 导出到单独目录。

## 运行环境

需要 Isaac Sim 6.0.1 及项目依赖。

```bash
uv run python src/assets_gen/convert_obj_to_usd.py \
  --assets-root ./assets \
  --folders ./assets/vase ./assets/mug \
  --metadata-xlsx ./assets/sample.xlsx \
  --output-root ./converted-obj \
  --usd-output-root ./converted-usd
```

默认扫描 `<assets-root>/vase`，读取 `<assets-root>/sample.xlsx`，
并将 OBJ 导出到 `<assets-root>/../rigid assets`。

## 输出

脚本将 OBJ 转为包含碰撞体的对齐 USD，导出对齐后的 OBJ，并在
`metadata.json` 中记录最终尺寸、质量和摩擦系数。输出保留相对于
`--assets-root` 的目录结构：

```text
assets/vase/001/model.obj
converted-usd/vase/001/Aligned.usd
converted-usd/vase/001/metadata.json
converted-usd/vase/001/textures/
converted-obj/vase/001/Aligned.obj
```

未指定 `--usd-output-root` 时，USD 输出到源 OBJ 目录。已有资产默认跳过；
使用 `--force` 重新生成，转换失败时保留旧文件。

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
- 失败资产不会中断后续处理；只要有资产转换失败，进程就返回非零退出码。
