
<div align="center">
  <img src="docs/logo.png" alt="ChromaSky Toolkit Logo" width="150"/>
  <h1>ChromaSky Toolkit ✨</h1>
  <p><strong>一个用于获取、处理并生成火烧云（晚霞/朝霞）指数地图的 Python 工具包。</strong></p>
  
  <p>
    <img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square" alt="Python Version">
    <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square" alt="License">
  </p>
</div>

本项目旨在自动化预测绚丽日出日落的完整流程：从下载最新的气象预报数据，到计算一个独特的“火烧云指数”，再到将结果可视化为高质量的**综合最佳图**（每场日出/日落只保留一张），并提供 Web 界面浏览、检索与手动更新。它非常适合气象爱好者、摄影师以及任何热爱美丽天空的人。


## 🚀 项目特性

*   🤖 **全自动数据流**: 自动从 **GFS** 获取云量预报，并从 **CAMS** 获取气溶胶数据。
*   🧠 **精密评分模型**: 独创的混合评分模型，综合评估**品质分**（高/中云形态、云边界距离）和**惩罚分**（低云遮挡、大气透明度）。
*   🎨 **高质量地图**: 使用 Matplotlib 和 Cartopy 创建视觉效果出色的暗色主题地图，包含地理边界和城市标注。
*   🖼️ **只保留综合最佳图**: 每场日出/日落只生成一张「综合最佳火烧云指数图」，分时图已停用（不再生成、不再存储、不再展示）。
*   🐳 **容器化部署**: 提供优化的 `Dockerfile`，实现一键部署和稳定运行。
*   🌐 **Web 服务与 UI**: 内置 FastAPI 服务器，提供首页 / 未来预报 / 历史存档三个页面，支持按日期检索与手动触发更新。
*   🗂️ **XYZ 瓦片生成**: 自动将指数叠加层切割为标准 XYZ 瓦片（Web Mercator），可直接用于 MapLibre / Mapbox GL JS 等前端地图库。
*   ⚙️ **高可配置性**: 通过中央配置文件，轻松调整地理区域、目标时间等参数。
*   ⚡ **并行计算**: 利用多核 CPU 显著加速指数计算过程。

## ⚙️ 快速开始 (Docker 推荐)

使用 Docker 是运行本项目的最简单、最可靠的方式。

### 前提条件

*   已安装 [Docker](https://www.docker.com/get-started/)。
*   一个 [哥白尼气候数据中心 (CDS)](https://cds.climate.copernicus.eu/#!/home) 账户，用于获取 API 密钥。

### 运行步骤

1.  **克隆仓库**
    ```bash
    git clone https://github.com/lanseria/chromasky-toolkit.git
    cd chromasky-toolkit
    ```

2.  **创建并配置 `.env` 文件**
    在项目根目录下创建一个名为 `.env` 的文件，并填入您的 CDS API 密钥：
    ```env
    # .env
    CDS_API_KEY="UID:API_KEY"
    # (可选) XYZ 瓦片输出到宿主机的路径，默认为 ./chroma-sky-tiles
    # TILES_HOST_PATH=/data/tiles
    ```
    请将 `UID:API_KEY` 替换为您自己的真实凭据。

3.  **构建并运行 Docker 容器**
    我们使用 **Docker 命名卷 (Named Volumes)** 来持久化存储下载的数据和生成的图片，这是最佳实践。

    ```bash
    # 步骤 1: 构建 Docker 镜像 (首次构建或代码更新后执行)
    docker build -t chromasky-toolkit .

    # 步骤 2: (可选) 创建命名卷，只需执行一次
    docker volume create chromasky-data
    docker volume create chromasky-outputs

    # 步骤 3: 运行容器
    docker run -d \
      --name chromasky-app \
      -p 8000:8000 \
      -v "$(pwd)/.env:/app/.env" \
      -v chromasky-data:/app/data \
      -v chromasky-outputs:/app/outputs \
      -v "$(pwd)/chroma-sky-tiles:/app/chroma-sky-tiles" \
      --restart always \
      chromasky-toolkit
    ```

    也可以直接使用仓库自带的 `docker-compose.yml`（端口映射为 **8002:8000**，并会读取根目录 `.env`）：

    ```bash
    docker compose up -d
    ```

4.  **访问应用**
    打开浏览器访问 `http://localhost:8000`（使用 `docker compose` 时为 `http://localhost:8002`）。
    *   首页展示最近一场进行中 / 即将开始的日出或日落综合图；没有未来预报时自动回退到最近一次存档。
    *   若页面为空，点击右上角「更新预报」按钮（等价于 `POST /trigger-job`）触发一次完整流程，首次运行需要较长时间。
    *   定时任务默认每 **3 小时**自动运行一次（cron `0,3,6,9,12,15,18,21`），无需手动干预。

## 💻 本地环境安装 (适用于开发者)

如果您希望直接在本地环境运行和修改代码。

### 1. 前提条件

*   Python 3.12 或更高版本。
*   拥有 CDS 账户及 API 密钥。

### 2. 安装步骤

1.  **克隆仓库**
    ```bash
    git clone https://github.com/lanseria/chromasky-toolkit.git
    cd chromasky-toolkit
    ```

2.  **安装依赖（推荐使用 uv）**
    ```bash
    # 安装 uv（如尚未安装）
    pip install uv

    # 按 uv.lock 创建 .venv 并安装项目及全部依赖
    uv sync
    ```
    > 也可以使用传统方式：`python -m venv venv`，激活后执行 `pip install -e .`。

3.  **配置 CDS API 密钥**
    在项目根目录创建 `.env` 文件（方法同 Docker 部分）。

4.  **下载地图底图数据**
    ```bash
    uv run python tools/setup_map_data.py
    ```
    此脚本会自动下载并设置绘图所需的地图边界和字体文件。

## ⌨️ 使用说明

### 启动 Web 服务

```bash
uv run uvicorn src.chromasky_toolkit.server:app --reload
```

启动后访问 `http://127.0.0.1:8000`。服务的定时任务会每 3 小时自动跑一次完整流程；也可以随时点击页面上的「更新预报」或调用 `POST /trigger-job` 手动触发。

### Web 界面

| 路由 | 说明 |
|------|------|
| `/` | 首页：最近一场「进行中 / 即将开始」的日出或日落综合图 Hero，加上「接下来」与「近日回看」 |
| `/future` | 未来预报：按天分组列出已生成存档且尚未结束的日出/日落事件（任务覆盖今天起 5 天） |
| `/history` | 历史存档：按时间范围、事件类型、精确日期筛选，结果按月分组展示 |
| `/archive` | 兼容旧链接，`307` 重定向到 `/history` |
| `/api/events` | 事件列表 JSON，支持 `scope` / `event` / `from` / `to` / `date` / `limit`（1–500） |
| `/api/glow-index` | 单点指数查询，详见 [docs/glow-index-api.md](docs/glow-index-api.md) |
| `POST /trigger-job` | 手动触发一次完整工作流（页面右上角「更新预报」按钮调用的就是它） |

- **数据新鲜度**：导航栏展示最近一张综合图的生成时间，以及「N 分钟前 / N 小时前 / N 天前」。
- **倒计时**：进行中/即将开始的事件会显示倒计时（JS 每 30 秒刷新；禁用 JS 时显示绝对时间窗口）。
- **灯箱**：点击任意地图打开大图（原生 `<dialog>`，支持 Esc、点击遮罩或关闭按钮退出）。
- **历史查询参数**：`scope`（`past` 已结束 / `all` 全部 / `future` 未来）、`event`（`all` / `sunrise` / `sunset`）、`from`、`to`、`date`（精确日期；该日无存档时自动回退到最接近的一天）、`sort`（`desc` / `asc`）。非法日期不会报 4xx，只在页面上提示并忽略。

### 命令行工具

您可以通过命令行入口分步执行流程，非常适合调试。

*   **执行完整流程:**
    ```bash
    uv run python -m src.chromasky_toolkit.main
    ```

*   **仅获取和预处理数据:**
    ```bash
    uv run python -m src.chromasky_toolkit.main --acquire-only
    ```

*   **仅计算指数:**
    ```bash
    uv run python -m src.chromasky_toolkit.main --calculate-only
    ```

*   **仅绘制地图（只生成综合最佳图）:**
    ```bash
    uv run python -m src.chromasky_toolkit.main --draw-only
    ```

*   **可视化输入数据 (用于调试):**
    ```bash
    uv run python -m src.chromasky_toolkit.main --visualize-inputs
    ```

*   **从已有数据重新生成 XYZ 瓦片:**
    ```bash
    uv run python -m src.chromasky_toolkit.main --generate-tiles
    ```

*   **PNG 转 WebP 格式（含陈旧 WebP 清理）:**
    ```bash
    uv run python -m src.chromasky_toolkit.main --convert-webp
    ```

所有输出将保存在 `outputs/` 目录中，XYZ 瓦片保存在 `chroma-sky-tiles/`。

### 清理历史分时图（升级后建议执行一次）

旧版本会把每个时间点的分时图写入 `outputs/maps/individual/` 与 `outputs/maps_webp/individual/`。新版本已不再生成这类图，可用脚本清理历史残留（**默认 dry-run，只预览不删除**）：

```bash
# 预览将删除的内容（历史分时图目录 + 源 PNG 已不存在的陈旧 WebP）
uv run python tools/cleanup_legacy_maps.py

# 确认无误后真正删除
uv run python tools/cleanup_legacy_maps.py --yes
```

脚本只会操作 `outputs/` 内的路径，不会触碰综合图（`composite/`）、`outputs/calculations/` 与 `chroma-sky-tiles/`。

## 🗺️ 地理范围配置

系统采用三级地理范围结构，逐级向外扩展，保证图幅边缘渲染完整、边界计算准确：

| 范围 | 用途 | 默认值 |
|------|------|--------|
| `DISPLAY_AREA` | 地图图幅与 XYZ 瓦片的可见范围 | 西 72°E / 东 136°E / 南 2°N / 北 54°N |
| `CALCULATION_AREA` | 火烧云指数实际计算的格点范围 | 展示范围四周外扩 1° |
| `DOWNLOAD_AREA` | 从服务器下载数据的范围 | 计算范围四周外扩 15° |

默认图幅**完整覆盖整个中国大陆及南海诸岛（含九段线，最南至曾母暗沙约 3.9°N，最东至黑龙江与乌苏里江汇合处约 135.1°E）**。

所有边界均可在 `.env` 中用环境变量精细覆盖，无需修改代码（详见 `.env.example`）：

```env
# 展示范围（地图图幅）
DISPLAY_NORTH=54
DISPLAY_SOUTH=2
DISPLAY_WEST=72
DISPLAY_EAST=136

# 计算范围（缺省 = 展示范围四周外扩 CALC_MARGIN_DEGREES）
CALC_MARGIN_DEGREES=1
# 也可单独指定任一边界
#CALC_SOUTH=10

# 下载缓冲区（度）
DOWNLOAD_BUFFER_DEGREES=15
```

> ⚠️ 注意：若将计算范围收缩得比展示范围小，图幅中超出计算范围的区域将没有指数数据（空白）。

## 🧪 测试

本项目使用 `pytest` 进行测试，`freezegun` 用于模拟时间。

```bash
# 运行全部测试（其中一个测试会调用真实 CAMS API，需要 CDS_API_KEY）
uv run pytest tests/ -v

# 跳过真实网络调用（推荐的本地/CI 方式）
uv run pytest tests/ -q -k "not TestCAMSAPICall"

# 运行单个测试文件
uv run pytest tests/test_midnight_download.py -v
```

设置 `CDS_API_KEY` 环境变量后可启用实际 CAMS API 调用测试：

```bash
CDS_API_KEY="UID:API_KEY" uv run pytest tests/ -v
```

## 🔬 工作原理

整个流程分为五个主要阶段：

1.  **数据获取**:
    *   脚本首先确定 GFS（云量）和 CAMS（气溶胶）当前可用的最新预报周期。
    *   根据配置下载相关数据，并将 CAMS 数据**重采样 (regrid)**到 GFS 的网格上，以确保空间对齐。

2.  **指数计算**:
    *   `GlowIndexCalculator` 对计算区域内的每个网格点，通过 `最终得分 = 品质分 × 惩罚分` 的公式进行评估。
    *   **品质分**: 评估正面因子，如 `云边界距离`、`高云覆盖率 (HCC)` 和 `中云覆盖率 (MCC)`。
    *   **惩罚分**: 评估负面因子，如 `低云覆盖率 (LCC)` 和 `气溶胶光学厚度 (AOD)`。

3.  **综合最佳图生成**:
    *   遍历每个「日期 + 事件」组内的所有时间点计算结果，逐格取最大值，合成为**唯一一张综合最佳图**，显示整个事件时段内的最佳潜力。
    *   分时图已停用：不再逐时间点出图，也不再创建 `outputs/maps/individual/`。
    *   使用高斯平滑和插值技术来创建平滑且美观的色彩等值线。

4.  **图片格式转换与清理**:
    *   将生成的 PNG 地图批量转换为 WebP 格式，优化 Web 加载速度（增量转换，未变化的文件跳过）。
    *   删除「源 PNG 已不存在」的陈旧 WebP（例如旧分时图残留），并清理因此变空的子目录。

5.  **XYZ 瓦片生成**:
    *   将综合指数叠加层切割为 XYZ 瓦片（Web Mercator 投影，256×256 RGBA PNG）。
    *   瓦片保留透明通道，可直接叠加在 MapLibre / Mapbox 等地图引擎上。
    *   详细的瓦片路径规则和接入方式见 [docs/tiles-api.md](docs/tiles-api.md)。

### 存档文件与 Web 数据来源

综合图是唯一的存档产物，Web 页面通过扫描下列目录构建事件列表：

```
outputs/maps/composite/      glow_index_composite_{YYYY-MM-DD}_{sunrise|sunset}.png
outputs/maps_webp/composite/ glow_index_composite_{YYYY-MM-DD}_{sunrise|sunset}.webp
```

页面优先使用 WebP，缺失时回退 PNG；「生成时间」取自图片文件的修改时间（mtime）。
Web UI 的字段与接口契约见 [docs/web-ui.md](docs/web-ui.md)。

## 📂 项目结构

```
chromasky-toolkit/
├── .env                  # (用户创建) 存放 API 密钥
├── chroma-sky-tiles/     # (运行时生成) XYZ 瓦片输出目录
├── data/                 # (运行时生成) 下载和处理后的数据
├── docs/                 # 文档和资源 (如 Logo、Web UI 契约)
├── fonts/                # (运行时生成) 下载的字体
├── map_data/             # (运行时生成) 地理 Shapefile
├── outputs/              # (运行时生成) 输出文件
│   ├── calculations/     #   指数计算结果 (.nc)
│   ├── maps/composite/   #   综合最佳图 PNG
│   └── maps_webp/composite/ # 综合最佳图 WebP（Web 页面优先使用）
├── src/
│   ├── chromasky_toolkit/  # 源代码
│   │   ├── main.py         # 命令行入口
│   │   ├── server.py       # FastAPI Web 服务与定时任务
│   │   ├── gallery.py      # Web UI 图库数据层（扫描/筛选/分组）
│   │   ├── config.py       # 中央配置文件
│   │   ├── mapping.py      # 综合最佳图绘制
│   │   ├── image_converter.py # PNG → WebP 转换与陈旧文件清理
│   │   ├── tile_generator.py # XYZ 瓦片生成
│   │   └── ...
│   ├── templates/          # Jinja2 模板 (base/index/future/history)
│   └── static/             # Web UI 静态资源 (app.css / app.js)
├── tools/
│   ├── setup_map_data.py   # 下载地图底图与字体
│   └── cleanup_legacy_maps.py # 清理历史分时图与陈旧 WebP
├── Dockerfile            # Docker 镜像定义
├── docker-compose.yml    # Docker Compose 编排
└── pyproject.toml        # 项目定义与依赖
```

## 🤝 贡献

欢迎任何形式的贡献！如果您有改进算法、修复 Bug 或添加新功能的想法，请随时提交 Pull Request 或创建 Issue。

## 📜 许可证

本项目采用 MIT License 授权。