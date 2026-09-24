# 套娃排序

将五个套娃按尺寸从小到大排列到桌面上的固定槽位。运行前需准备任务配置引用的套娃资产及对应的 Piper 抓取数据。

从仓库根目录采集一个 episode：

```bash title="专家数据采集"
uv run python scripts/run_demo_generation.py \
  --task sort_dolls_by_size \
  --num-envs 1 \
  --episodes 1 \
  --max-steps 1200 \
  --record-output outputs/sort-dolls \
  --dataset-name sort_dolls_by_size \
  --viz none
```

结束日志会给出实际的 HDF5 文件路径和成功率；同名数据集已存在时会自动使用新文件名。
