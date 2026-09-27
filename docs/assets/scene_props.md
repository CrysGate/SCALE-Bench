---
description: 下载首批厨房、办公、园艺场景资产，转换 USD 并切换场景预设。
---

# 场景物品

厨房、办公和园艺预设包含静态背景与独立的操作物品。厨房操作现有奶茶杯，办公操作参数化空盒，园艺操作由 Poly Haven 花盆缩小得到的盆体。新增操作资产提供 Piper 抓取数据；大型果碗、键盘、鼠标、花瓶和花盆继续作为背景。

## 下载与转换

先完成[环境和 Assets 软链接准备](../getting-started.md#environment)，在项目根目录执行：

```bash
uv run python scripts/download_scene_assets.py
uv run python scripts/prepare_scene_assets.py
OMP_NUM_THREADS=1 uv run python scripts/prepare_manipulation_assets.py
```

下载约 770 MB，包含 Lightwheel 厨房归档。文件写入 `Assets/Imported/`，沿用 `Assets` 指向的独立数据仓库。重复下载会校验并复用源文件；转换会重新生成 USD、元数据和抓取文件。按上述顺序执行，最后生成资产侧的完整 `index.json` 与代码仓库的 `configs/assets/index.json` 尺寸及校验值索引。

下载资产保留源文件、纹理、许可原文 `LICENSE.txt`、署名 `ATTRIBUTION.txt`、固定版本及逐文件 SHA-256 清单 `source_manifest.json`；Lightwheel 的三个模块共用上一级来源目录。参数化和缩放物品的生成参数、源版本及文件校验值保存在 `metadata.json`。转换后的 USD 使用米制、Z 轴向上，原点位于可见几何的包围盒中心，纹理和引用保留为本地依赖。NVIDIA 模型使用 Isaac Sim 自带的 OmniPBR、OmniGlass 着色器。

| 资产目录 | 宽 × 深 × 高（cm） | 来源及许可 |
| --- | --- | --- |
| `fruit_bowl` | 37.11 × 37.11 × 20.77 | [NVIDIA Kitchen / Lightwheel](https://huggingface.co/datasets/nvidia/PhysicalAI-Robotics-Manipulation-Objects-Kitchen-MJCF)，CC BY 4.0；选用 `FruitBowl003`，水果与碗为一体模型 |
| `keyboard` | 44.20 × 14.20 × 2.02 | [NVIDIA Warehouse](https://huggingface.co/datasets/nvidia/PhysicalAI-SimReady-Warehouse-01)，CC BY 4.0 |
| `mouse` | 25.40 × 19.06 × 4.08 | [NVIDIA Warehouse](https://huggingface.co/datasets/nvidia/PhysicalAI-SimReady-Warehouse-01)，CC BY 4.0；源模型包含鼠标垫 |
| `ceramic_vase_01` | 20.49 × 20.64 × 40.14 | [James Ray Cock / Poly Haven](https://polyhaven.com/a/ceramic_vase_01)，CC0 |
| `planter_pot_clay` | 26.60 × 26.35 × 22.19 | [Amal Kumar / Poly Haven](https://polyhaven.com/a/planter_pot_clay)，CC0 |
| `lightwheel_kitchen/cabinet` | 234.09 × 62.16 × 239.69 | [Lightwheel Kitchen](https://github.com/LightwheelAI/Lightwheel_Kitchen)，CC BY-NC 4.0 |
| `lightwheel_kitchen/counter` | 114.96 × 76.13 × 85.84 | 同上 |
| `lightwheel_kitchen/coffee_machine` | 30.95 × 30.46 × 38.06 | 同上 |

尺寸来自源资产几何，未经过实物测量。果碗保留 MJCF 的 16 块凸碰撞分解，其水果与碗为一体，不是空容器。其他静态物品使用三角网格碰撞。厨房只加载选定的橱柜、台柜和咖啡机模块；房间原有地面和灯光被禁用，工作台支撑面由项目配置定义。

## 操作物品与容器尺寸

| 物品集合 | 外形宽 × 深 × 高（cm） | 质量（g） | 容器几何 |
| --- | --- | --- | --- |
| `kitchen_cup` / `kitchen_cup_large` | 使用现有 300g / 800g 奶茶杯规格 | 沿用原元数据 | 封闭杯体 |
| `packing_box_small` | 6.5 × 6.5 × 6.5 | 45 | 内腔 5.7 × 5.7 × 6.0 cm |
| `packing_box_large` | 8.0 × 8.0 × 8.0 | 65 | 内腔 7.2 × 7.2 × 7.5 cm |
| `planter_pot_small` | 6.65 × 6.59 × 5.55 | 45 | 原花盆的 0.25 倍 |
| `planter_pot_large` | 7.98 × 7.90 × 6.66 | 65 | 原花盆的 0.30 倍 |

空盒以五个凸盒共同定义可见表面和碰撞体，壁厚 4 mm、底厚 5 mm。花盆保留原纹理，以 CoACD 凸分解表示开放内腔，并在测得的盆底范围内补充平底碰撞面；视觉网格不再参与动态碰撞。两类新物品的摩擦系数均为 0.8，碰撞接触偏移为 1 mm。质量、摩擦和缩放是 `configs/assets/manipulation.yml` 中的仿真规格，不是实物标定结果。

花盆、花瓶元数据包含内腔深度、底厚、开口截面、壁厚和沿高度的径向采样。每个截面采样 64 个方向，覆盖外形高度的 10%–90%；`opening_measurement_z_object_m` 标明开口测量平面。这些几何估计用于检查开放内腔，不能直接作为装箱成功判据。CuRobo 仍使用保守外包围盒，因此容器内部运动规划属于后续任务阶段。

## 切换场景

三组配置位于 `configs/scene/kitchen.yml`、`office.yml`、`garden.yml`，保持原工作台尺寸、机械臂和相机安装关系。背景物品的占地范围参与初始布局采样和导入校验，同一尺寸也参与 CuRobo 避障。办公和园艺场景将采样区域下界设为 `y=-0.08 m`，让低矮容器与基座保持距离。

```bash
uv run python scripts/preview_scene.py \
  --task single_object_pick_and_place \
  --config configs/scene/kitchen.yml
```

采集厨房奶茶杯：

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --task-config configs/tasks/single_object_pick_and_place/containers.yml \
  --scene-config configs/scene/kitchen.yml \
  --object-set configs/tasks/object_sets/kitchen_cup.yml \
  --episodes 3 --base-seed 100 \
  --record-output outputs/kitchen \
  --dataset-name kitchen --viz none
```

采集办公空盒：

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --task-config configs/tasks/single_object_pick_and_place/containers.yml \
  --scene-config configs/scene/office.yml \
  --object-set configs/tasks/object_sets/packing_box_small.yml \
  --episodes 3 --base-seed 100 \
  --record-output outputs/office --dataset-name office --viz none
```

园艺场景使用 `garden.yml` 和 `planter_pot_small.yml`。将物品集合中的 `small` 换成 `large` 可检查最大规格，奶茶杯对应 `kitchen_cup_large.yml`。三个场景使用 `containers.yml` 的桌面中央目标位，为不同高度的物品留出释放和撤退空间；任务仍是现有单物体抓取放置。

回放时显式传入采集时相同的 `--scene-config`、`--task-config`、`--object-set` 和机器人配置。当前录制尚不包含完整配置及资产快照。

在 8 GB 显卡上录制双环境 RGB-D 时，使用 `--num-envs 2 --record-camera-observations --camera-config configs/cameras/d435_smoke.yml --viz kit`，无显示器时加 `HEADLESS=1`。该配置为 160×120；厨房双环境 640×480 连续录制会超出本次验收设备的显存，单次画面检查仍可使用原分辨率。

## 房间、桌面与照明

`room.room_position_env_m` 和 `room.yaw_env_rad` 控制房间相对单环境原点的摆放。`excluded_prim_paths` 是相对于源 USD 默认 prim 的路径模式，用于移除重复地面或家具；房间自带灯光统一禁用。进入机械臂范围的家具应按 `props` 添加，其元数据尺寸会同时参与采样避障和运动规划。

办公桌保留 `material_path` 的 MDL 入口。厨房和园艺桌采用 `pbr`，其中基础色使用 sRGB，OpenGL 法线及粗糙度、金属度使用线性数据；标量贴图可通过 `channel` 选择独立灰度图或 ORM 的通道。`texture_size_m` 是一张贴图在实物表面覆盖的宽和高，各面的纹理密度按实际尺寸计算。选择 PBR 时将 `material_path` 设为 `null`；桌面的可见几何、碰撞几何和支撑高度来自同一 `size_m`。

`lighting.profile_path` 可选择 `configs/lighting/soft.yml`、`side.yml` 或 `top.yml`。预设分别提供柔光、侧光与顶灯，可修改灯位、朝向、半径、颜色和强度。局部灯只照亮所属环境；HDRI 仍是全局共享，因此不同 HDRI 和照明预设需分批采集。省略 `profile_path` 时仅使用原有 HDRI。

## 生成资产预览

在有 NVIDIA GPU 的环境中运行：

```bash
uv run python scripts/render_asset_views.py \
  Assets/Imported/packing_box_small/model.usdc \
  Assets/Imported/packing_box_large/model.usdc \
  Assets/Imported/planter_pot_small/model.usdc \
  Assets/Imported/planter_pot_large/model.usdc \
  --output-dir Assets/Imported/previews/manipulation --panel-size 480
```

输出正面、侧面和俯视尺寸图，以及每个输入资产对应的单张图。图片按输入顺序编号。可替换输入 USD 预览背景物品；大尺寸家具与小操作物品分批渲染，避免共同比例尺让小物品难以辨认。

检查双环境的三路 RGB-D、背景摆放及材质与局部灯修改隔离：

```bash
HEADLESS=1 uv run python scripts/inspect_scene_assets.py \
  --scene-config configs/scene/garden.yml \
  --object-set configs/tasks/object_sets/planter_pot_small.yml \
  --output-dir outputs/garden-inspection --viz kit
```

该工具还会在开放容器中落入半径 3 mm、限速 0.1 m/s 的探球，检查碰撞体是否封口以及容器是否稳定贴桌。限速让探球在每个物理步内的移动距离小于薄壁底厚；该检查不覆盖高速投掷。结果保存为 RGB 图片、深度数组和 `report.json`。
