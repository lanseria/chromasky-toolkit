# ChromaSky Toolkit ✨ - 火烧云指数工具包

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)

一个用于获取、处理并生成火烧云（晚霞/朝霞）指数地图的 Python 工具包。

本项目旨在自动化预测绚丽日出日落的完整流程：从下载最新的气象预报数据，到计算一个独特的“火烧云指数”，再到将结果可视化为高质量的地图。它非常适合气象爱好者、摄影师以及任何热爱美丽天空的人。

## 🗺️ 效果示例

下图是 ChromaSky Toolkit 生成的地图示例。该地图展示了**综合火烧云指数**，高亮区域代表在特定时间段内最有可能出现壮丽晚霞的地区。

*(强烈建议您将此占位符图片替换为由您自己脚本生成的真实图片)*
![Sample Output Map](https://i.imgur.com/gS2OV1Y.png "示例：火烧云指数预报地图")

## 🚀 项目特性

*   **自动化数据获取**: 自动从 **GFS** (全球预报系统) 获取最新的云量预报数据，并从 **CAMS** (哥白尼大气监测服务) 获取气溶胶预报数据。
*   **精密的评分模型**: 使用一个混合评分模型，综合考虑多种气象因子：
    *   **品质分 (Quality Score)**: 增强晚霞潜力的因子，如高云和中云的覆盖率，以及观测点与太阳方向上云边界的距离。
    *   **惩罚分 (Penalty Score)**: 影响观测效果的因子，如遮挡视线的低云和降低大气通透度的气溶胶（雾霾/污染）。
*   **高质量地图生成**: 使用 Matplotlib 和 Cartopy 创建视觉效果出色的精细地图，包含暗色主题、地理边界和城市标注。
*   **模块化命令行**: 工具被划分为清晰的步骤 (`获取` -> `计算` -> `绘制`)，可以独立运行，便于调试和灵活使用。
*   **高可配置性**: 通过一个中央配置文件，可以轻松调整地理区域、目标时间等参数。
*   **并行计算**: 利用多核 CPU 来显著加速指数在数据网格上的计算过程。

## ⚙️ 安装与配置

请按照以下步骤在您的本地环境中配置并运行 ChromaSky Toolkit。

### 1. 前提条件

*   Python 3.12 或更高版本。
*   一个 [哥白尼气候数据中心 (CDS)](https://cds.climate.copernicus.eu/#!/home) 账户，用于获取 API 密钥。

### 2. 克隆仓库

```bash
git clone https://github.com/lanseria/chromasky-toolkit.git
cd chromasky-toolkit
```

### 3. 创建虚拟环境并安装依赖

强烈建议使用虚拟环境。

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境 (Windows)
# venv\Scripts\activate
# 激活虚拟环境 (macOS/Linux)
source venv/bin/activate

# 安装本项目及其所有依赖
pip install .
```
此命令将安装 `pyproject.toml` 中列出的所有依赖项。

### 4. 配置 CDS API 密钥

本工具需要访问 CAMS 数据。

1.  登录 [CDS 网站](https://cds.climate.copernicus.eu/user/login)。
2.  在您的个人资料页面复制 UID 和 API 密钥 (格式类似于 `12345:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)。
3.  在项目根目录下创建一个名为 `.env` 的新文件。
4.  将您的 API 密钥添加到 `.env` 文件中，格式如下：

    ```env
    # .env
    CDS_API_KEY="UID:API_KEY"
    ```
    请将 `UID:API_KEY` 替换为您自己的真实凭据。

### 5. 下载地图底图数据

工具需要 shapefile 文件来绘制地理边界。我们提供了一个便捷脚本来自动下载和设置它们。

```bash
python tools/setup_map_data.py
```
这将会下载所需文件并将其放置在 `map_data/` 目录中。

至此，所有准备工作完成！

## ⌨️ 使用说明

您可以通过一个统一的命令行入口来控制本工具。您可以执行完整的流程，也可以分步执行。

### 执行完整流程

要运行从数据获取到地图生成的完整流程，只需执行主模块且不带任何参数：

```bash
python -m chromasky_toolkit.main
```

### 分步执行

这对于调试或仅需执行部分流程时非常有用。

*   **仅获取和预处理数据:**
    ```bash
    python -m chromasky_toolkit.main --acquire-only
    ```

*   **仅计算指数 (需要已获取的数据):**
    ```bash
    python -m chromasky_toolkit.main --calculate-only
    ```

*   **仅绘制地图 (需要已计算的结果):**
    ```bash
    python -m chromasky_toolkit.main --draw-only
    ```

*   **PNG 图片转换为 WebP 格式:**
    ```bash
    python -m chromasky_toolkit.main --convert-webp
    ```

*   **可视化输入数据 (用于调试):**
    此命令会为每个输入变量（高/中/低云, AOD）生成地图，帮助您检查输入数据是否正确。
    ```bash
    python -m chromasky_toolkit.main --visualize-inputs
    ```

所有输出结果将保存在 `outputs/` 目录中，并根据计算结果和地图分类存放在不同子目录。

## 🛠️ 自定义配置

您可以编辑 `src/chromasky_toolkit/config.py` 文件来定制工具的行为。一些关键选项包括：

*   `FUTURE_TARGET_EVENT_INTENTIONS`: 最重要的配置项。定义需要处理的未来事件（例如 `'today_sunset'`, `'tomorrow_sunrise'`）。
*   `CALCULATION_AREA`: 定义指数计算的核心地理范围。
*   `DISPLAY_AREA`: 定义最终输出地图上显示的地理范围。
*   `SUNSET_EVENT_TIMES` / `SUNRISE_EVENT_TIMES`: 指定需要生成预报的本地时间点。

## 🔬 工作原理

整个流程分为三个主要阶段：

1.  **数据获取**:
    *   脚本首先确定 GFS（云量）和 CAMS（气溶胶）当前可用的最新预报周期。
    *   根据配置中的地理区域和时间范围下载相关数据。
    *   将下载的 GRIB (GFS) 和 NetCDF (CAMS) 原始数据处理为标准化的 NetCDF 文件。关键一步是，CAMS 数据会被**重采样 (regrid)**到 GFS 的网格上，以确保空间对齐。

2.  **指数计算**:
    *   对于计算区域内的每个网格点，`GlowIndexCalculator` 会评估其出现绚丽霞光的潜力。
    *   它会计算一个**品质分**，基于正面因子：
        *   `云边界距离`: 在日出/日落方向上，与高云边界的距离是否处于最佳范围。
        *   `高云覆盖率 (HCC)`: 卷云等高云的存在是必要条件。
        *   `中云覆盖率 (MCC)`: 中云也能为天空增色。
    *   同时计算一个乘算的**惩罚分**，基于负面因子：
        *   `低云覆盖率 (LCC)`: 地平线上的低云会遮挡光线。
        *   `气溶胶光学厚度 (AOD)`: 过度的雾霾或污染会削弱光线，降低色彩饱和度。
    *   **最终的火烧云指数**通过以下公式得出: `最终得分 = 品质分 × 惩罚分`。

3.  **地图生成**:
    *   读取计算出的指数结果。
    *   为每个时间点生成单独的预报图，并生成一张**综合地图**，显示每个网格点在整个事件时段内的最高分（例如，整个日落期间的最佳潜力）。
    *   使用高斯平滑和插值技术来创建平滑且美观的色彩等值线。

## 📂 项目结构

```
chromasky-toolkit/
├── .env                  # (用户创建) 存放 API 密钥
├── data/                 # 下载和处理后的数据
│   ├── processed/
│   └── raw/
├── map_data/             # 地理 Shapefile 文件
├── outputs/              # 生成的输出文件
│   ├── calculations/     # 指数计算结果 (.nc)
│   └── maps/             # 输出的地图图片 (.png)
├── src/
│   └── chromasky_toolkit/  # 包的源代码
│       ├── __init__.py
│       ├── main.py         # 命令行入口
│       ├── config.py       # 中央配置文件
│       ├── data_acquisition.py # 数据获取与预处理逻辑
│       ├── processing.py   # 计算流程的编排
│       ├── glow_index.py   # 核心评分模型逻辑
│       ├── astronomy.py    # 太阳位置与天文事件计算
│       ├── map_drawer.py   # 地图可视化与绘制逻辑
│       └── ...
├── tools/
│   └── setup_map_data.py # 用于下载地图数据的辅助脚本
└── pyproject.toml        # 项目定义与依赖管理
```

```
docker build -t chromasky-toolkit .

docker run -d \
  -p 8000:8000 \
  --name chromasky-server \
  -v "$(pwd)/.env:/app/src/.env" \
  -v "$(pwd)/data:/app/src/data" \
  -v "$(pwd)/outputs:/app/src/outputs" \
  chromasky-toolkit

# 1. 创建一个 Docker 命名卷 (只需执行一次)
docker volume create chromasky-data
docker volume create chromasky-outputs

# 2. 运行容器，并将命名卷挂载到正确的路径
docker run -d --name chromasky-app -p 8000:8000 \
  -v chromasky-data:/app/data \
  -v chromasky-outputs:/app/outputs \
  -v "$(pwd)/.env:/app/.env" \
  chromasky-toolkit

```