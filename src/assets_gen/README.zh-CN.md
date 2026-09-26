# OBJ 转 USD

[English](README.md)

将自己的 OBJ 批量转换为带碰撞体的 USD，按元数据设置尺寸和质量，并导出对齐后的 OBJ。运行前完成[项目环境安装](https://crysgate.github.io/SCALE-Bench/getting-started/#environment)。

## 准备输入

以下示例使用 `assets/vase/300g/model.obj` 及其材质文件。将尺寸和质量写入 `assets/sample.xlsx` 的第一个工作表，首行为表头：

| name | mass(kg) | x | y | z |
| --- | --- | --- | --- | --- |
| vase | 0.3 | 9 | 9 | 13.5 |

`name` 对应物体目录名；同名物体有多个质量规格时，用 `300g` 这样的目录名区分。尺寸默认单位为厘米，其他单位通过 `--dimension-unit m` 或 `--dimension-unit mm` 指定。质量可使用 `mass(kg)` 或 `mass(g)` 表头。

## 转换

```bash
uv run python src/assets_gen/convert_obj_to_usd.py \
  --assets-root assets \
  --folders assets/vase \
  --metadata-xlsx assets/sample.xlsx \
  --output-root converted-obj \
  --usd-output-root converted-usd
```

对应输出：

```text
converted-usd/vase/300g/Aligned.usd
converted-usd/vase/300g/metadata.json
converted-usd/vase/300g/textures/
converted-obj/vase/300g/Aligned.obj
```

`metadata.json` 保存实际尺寸（米）、质量（千克）和摩擦系数。移动 USD 资产时，一并保留该目录下的元数据和纹理。

## 补充用法

- **没有匹配的元数据**：使用 `--mass` 指定千克质量、`--scale` 指定缩放倍数，默认分别为 `0.1` 和 `1.0`。单个轴缺少尺寸时，只有该轴使用回退缩放。
- **先检查少量模型**：加入 `--max-models 1`，最多成功转换一个模型。
- **重新生成**：已有 USD 默认跳过，加入 `--force` 覆盖；省略 `--usd-output-root` 会将 USD 写入源 OBJ 所在目录。

结束时检查转换、跳过和失败数量。失败模型不影响后续模型处理；任一模型转换失败时，进程返回非零退出码。
