
<div align="center">
  <img src="docs/logo.svg" alt="ChromaSky Toolkit Logo" width="150"/>
  <h1>ChromaSky Toolkit ✨</h1>
  <p><strong>一个用于获取、处理并生成火烧云（晚霞/朝霞）指数地图的 Python 工具包。</strong></p>
  
  <p>
    <a href="https://chroma-sky.sharee.top/" target="_blank">
      <img src="https://img.shields.io/badge/Live_Demo-访问在线地图-brightgreen?style=for-the-badge&logo=icloud" alt="Live Demo">
    </a>
  </p>
  
  <p>
    <img src="https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square" alt="Python Version">
    <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square" alt="License">
  </p>
</div>

本项目旨在自动化预测绚丽日出日落的完整流程：从下载最新的气象预报数据，到计算一个独特的“火烧云指数”，再到将结果可视化为高质量的地图。它非常适合气象爱好者、摄影师以及任何热爱美丽天空的人。

## 🗺️ 效果示例

下图是由 ChromaSky Toolkit 自动生成的**综合火烧云指数**地图。高亮区域代表在特定时间段内最有可能出现壮丽晚霞的地区。

![Sample Output Map](https://i.imgur.com/PNuK6b1.jpeg "示例：火烧云指数预报地图")

## 🚀 项目特性

*   🤖 **全自动数据流**: 自动从 **GFS** 获取云量预报，并从 **CAMS** 获取气溶胶数据。
*   🧠 **精密评分模型**: 独创的混合评分模型，综合评估**品质分**（高/中云形态、云边界距离）和**惩罚分**（低云遮挡、大气透明度）。
*   🎨 **高质量地图**: 使用 Matplotlib 和 Cartopy 创建视觉效果出色的暗色主题地图，包含地理边界和城市标注。
*   🐳 **容器化部署**: 提供优化的 `Dockerfile`，实现一键部署和稳定运行。
*   🌐 **Web 服务**: 内置 FastAPI 服务器，提供 Web 界面展示最新地图，并支持手动触发更新。
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
      --name chromasky-server \
      -p 8000:8000 \
      --env-file .env \
      -v chromasky-data:/app/data \
      -v chromasky-outputs:/app/outputs \
      --restart always \
      chromasky-toolkit
    ```

4.  **访问应用**
    打开浏览器，访问 `http://localhost:8000` 即可看到 Web 界面。
    *   首次运行时，页面可能为空。**快速点击主标题三次**可手动触发一次数据更新流程。
    *   定时任务将在每日凌晨 `1:30` 自动运行。

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

2.  **创建虚拟环境并安装依赖**
    ```bash
    # 创建虚拟环境
    python -m venv venv
    # 激活 (macOS/Linux)
    source venv/bin/activate
    # 激活 (Windows)
    # venv\Scripts\activate

    # 安装本项目及所有依赖
    pip install -e .
    ```

3.  **配置 CDS API 密钥**
    在项目根目录创建 `.env` 文件（方法同 Docker 部分）。

4.  **下载地图底图数据**
    ```bash
    python tools/setup_map_data.py
    ```
    此脚本会自动下载并设置绘图所需的地图边界和字体文件。

## ⌨️ 使用说明

### 启动 Web 服务

```bash
uvicorn src.chromasky_toolkit.server:app --reload
```

### 命令行工具

您可以通过命令行入口分步执行流程，非常适合调试。

*   **执行完整流程:**
    ```bash
    python -m src.chromasky_toolkit.main
    ```

*   **仅获取和预处理数据:**
    ```bash
    python -m src.chromasky_toolkit.main --acquire-only
    ```

*   **仅计算指数:**
    ```bash
    python -m src.chromasky_toolkit.main --calculate-only
    ```

*   **仅绘制地图:**
    ```bash
    python -m src.chromasky_toolkit.main --draw-only
    ```

*   **可视化输入数据 (用于调试):**
    ```bash
    python -m src.chromasky_toolkit.main --visualize-inputs
    ```

所有输出将保存在 `outputs/` 目录中。

## 🔬 工作原理

整个流程分为三个主要阶段：

1.  **数据获取**:
    *   脚本首先确定 GFS（云量）和 CAMS（气溶胶）当前可用的最新预报周期。
    *   根据配置下载相关数据，并将 CAMS 数据**重采样 (regrid)**到 GFS 的网格上，以确保空间对齐。

2.  **指数计算**:
    *   `GlowIndexCalculator` 对计算区域内的每个网格点，通过 `最终得分 = 品质分 × 惩罚分` 的公式进行评估。
    *   **品质分**: 评估正面因子，如 `云边界距离`、`高云覆盖率 (HCC)` 和 `中云覆盖率 (MCC)`。
    *   **惩罚分**: 评估负面因子，如 `低云覆盖率 (LCC)` 和 `气溶胶光学厚度 (AOD)`。

3.  **地图生成**:
    *   为每个时间点生成单独的预报图，并生成一张**综合地图**，显示整个事件时段内的最佳潜力。
    *   使用高斯平滑和插值技术来创建平滑且美观的色彩等值线。

## 📂 项目结构

```
chromasky-toolkit/
├── .env                  # (用户创建) 存放 API 密钥
├── data/                 # (运行时生成) 下载和处理后的数据
├── docs/                 # 文档和资源 (如 Logo)
├── fonts/                # (运行时生成) 下载的字体
├── map_data/             # (运行时生成) 地理 Shapefile
├── outputs/              # (运行时生成) 输出文件
├── src/
│   └── chromasky_toolkit/  # 源代码
│       ├── main.py         # 命令行入口
│       ├── server.py       # Web 服务
│       ├── config.py       # 中央配置文件
│       └── ...
├── templates/            # HTML 模板
├── tools/
│   └── setup_map_data.py # 辅助脚本
├── Dockerfile            # Docker 镜像定义
└── pyproject.toml        # 项目定义与依赖
```

## 🤝 贡献

欢迎任何形式的贡献！如果您有改进算法、修复 Bug 或添加新功能的想法，请随时提交 Pull Request 或创建 Issue。

## 📜 许可证

本项目采用 [MIT License](LICENSE) 授权。