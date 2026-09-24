# 单物体抓取与放置

抓起随机位置的 bottle，将其直立放入固定目标槽位。运行前需准备 bottle 资产及对应的 Piper 抓取数据。

从仓库根目录采集一个 episode：

```bash
uv run python scripts/run_demo_generation.py \
  --task single_object_pick_and_place \
  --num-envs 1 \
  --episodes 1 \
  --max-steps 1200 \
  --record-output outputs/bottle-pick-place \
  --dataset-name bottle_pick_place \
  --viz none
```

结束日志会给出实际的 HDF5 文件路径和成功率；同名数据集已存在时会自动使用新文件名。
