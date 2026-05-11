# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ChromaSky Toolkit 是一个 Python 火烧云（晚霞/朝霞）指数预测工具。它自动从 GFS（云量预报）和 CAMS（气溶胶数据）下载气象数据，通过混合评分模型计算火烧云指数，并生成高质量的指数地图。Python 3.12+，使用 uv 管理依赖。

## Commands

```bash
# 安装依赖
pip install -e .

# 初始化地图底图数据（首次运行必须）
python tools/setup_map_data.py

# 命令行工作流
python -m src.chromasky_toolkit.main                       # 完整流程
python -m src.chromasky_toolkit.main --acquire-only        # 仅下载+预处理数据
python -m src.chromasky_toolkit.main --calculate-only      # 仅计算指数
python -m src.chromasky_toolkit.main --draw-only           # 仅绘制地图
python -m src.chromasky_toolkit.main --visualize-inputs    # 调试：可视化输入数据
python -m src.chromasky_toolkit.main --convert-webp        # PNG → WebP 转换

# Web 服务
uvicorn src.chromasky_toolkit.server:app --reload

# Docker
docker build -t chromasky-toolkit .
docker compose up -d
```

## Architecture

### 数据流水线（四阶段）

1. **数据获取** (`data_acquisition.py`): 下载 GFS 云量 + CAMS 气溶胶数据，将 CAMS 重采样到 GFS 网格，保存为 `.nc` 文件到 `data/processed/future/`
2. **事件展开** (`processing.py`): 将配置中的事件意图（如 `today_sunset`）展开为具体 UTC 时间点
3. **指数计算** (`glow_index.py`): `GlowIndexCalculator` 逐网格评分：`最终得分 = 品质分(云边界距离/HCC/MCC) × 惩罚分(LCC/AOD)`，支持多核并行
4. **地图生成** (`mapping.py` → `map_drawer.py`): Matplotlib + Cartopy 暗色主题地图，含高斯平滑，输出到 `outputs/maps/`

### 核心模块

| 模块 | 职责 |
|------|------|
| `config.py` | 中央配置：地理范围、时间窗口（按季节自动切换）、所有路径常量 |
| `astronomy.py` | 天文计算：日出/日落时间、太阳位置 |
| `server.py` | FastAPI Web 服务，APScheduler 定时任务（每日 1:30 UTC） |
| `image_converter.py` | PNG → WebP 转换 |
| `input_visualizer.py` | 输入数据调试可视化 |
| `utils.py` | 通用工具函数 |

### 关键设计

- **地理范围三级结构**: `DISPLAY_AREA`（展示）→ `CALCULATION_AREA`（计算）→ `DOWNLOAD_AREA`（下载缓冲，各扩展 15°）
- **季节自适应时间窗口**: `config.py` 根据当前月份自动切换日出/日落时间段（冬/夏/春秋）
- **事件驱动**: 所有计算围绕 `FUTURE_TARGET_EVENT_INTENTIONS` 配置的事件展开
- **数据格式**: 中间数据为 NetCDF (`.nc`)，最终输出 PNG/WebP

### 路径约定

- 源码在 `src/chromasky_toolkit/`
- `config.py` 中 `PROJECT_ROOT` = `src/` 目录，所有数据路径使用 `PROJECT_ROOT.parent / "xxx"` 指向项目根目录下的 `data/`、`outputs/`、`map_data/`、`fonts/`
- 运行前需要 `.env` 文件配置 `CDS_API_KEY`（格式: `UID:API_KEY`）

## Code Style

- 使用中文注释
- 日志使用 `logging` 模块，logger 命名按模块区分
- 类型注解使用 Python 3.12+ 语法（`str | None` 而非 `Optional[str]`）
