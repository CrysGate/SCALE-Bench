<div class="home-hero">
  <p class="home-hero__kicker">ISAAC LAB / 双臂操作</p>
  <h1>SCALE-Bench</h1>
  <p class="home-hero__lead">可复现的操作任务与专家数据采集。</p>
  <div class="home-hero__actions">
    <a class="home-action home-action--primary" href="#tasks">浏览任务</a>
    <a class="home-action home-action--secondary" href="https://github.com/CrysGate/SCALE-Bench">查看源码</a>
  </div>
</div>

<section class="home-section" id="tasks">
  <div class="home-section__heading">
    <h2>任务</h2>
    <p>选择任务，查看专家数据采集命令。</p>
  </div>
  <div class="task-grid">
    <a class="task-tile" href="tasks/sort_dolls_by_size/">
      <span class="task-tile__number">01</span>
      <strong>套娃排序</strong>
      <span class="task-tile__description">按尺寸排列五个套娃。</span>
      <span class="task-tile__link">查看任务 <span aria-hidden="true">→</span></span>
    </a>
    <a class="task-tile" href="tasks/single_object_pick_and_place/">
      <span class="task-tile__number">02</span>
      <strong>单物体抓取与放置</strong>
      <span class="task-tile__description">将 bottle 直立放入目标槽位。</span>
      <span class="task-tile__link">查看任务 <span aria-hidden="true">→</span></span>
    </a>
    <a class="task-tile" href="tasks/largest_pick_and_place/">
      <span class="task-tile__number">03</span>
      <strong>最大物体抓取与放置</strong>
      <span class="task-tile__description">选出最大的物体并放入目标槽位。</span>
      <span class="task-tile__link">查看任务 <span aria-hidden="true">→</span></span>
    </a>
  </div>
</section>

## 运行前

按[项目安装说明](https://github.com/CrysGate/SCALE-Bench/blob/main/README.zh-CN.md#环境)准备环境及未纳入 Git 的 `Assets/` 资产包。任务命令均从仓库根目录执行，数据写入 `outputs/`。

任务页默认只记录关节状态、动作和评测结果。需要 RGB-D 相机数据时，在命令前加 `HEADLESS=1`，将 `--viz none` 改为 `--viz kit`，并追加 `--record-camera-observations`。

本地预览文档：

```bash
uvx --from mkdocs==1.6.1 --with mkdocs-material==9.6.20 mkdocs serve
```
