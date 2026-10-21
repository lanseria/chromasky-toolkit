## Project Overview

ChromaSky Toolkit 是一个 Python 火烧云（晚霞/朝霞）指数预测工具。它自动从 GFS（云量预报）和 CAMS（气溶胶数据）下载气象数据，通过混合评分模型计算火烧云指数，并生成高质量的指数地图（每场日出/日落只保留一张综合最佳图）。Python 3.12+，使用 uv 管理依赖。

## Commands

```bash
# 安装依赖（按 uv.lock 创建 .venv）
uv sync

# 初始化地图底图数据（首次运行必须）
uv run python tools/setup_map_data.py

# 命令行工作流
uv run python -m src.chromasky_toolkit.main                       # 完整流程
uv run python -m src.chromasky_toolkit.main --acquire-only        # 仅下载+预处理数据
uv run python -m src.chromasky_toolkit.main --calculate-only      # 仅计算指数
uv run python -m src.chromasky_toolkit.main --draw-only           # 仅绘制综合图
uv run python -m src.chromasky_toolkit.main --visualize-inputs    # 调试：可视化输入数据
uv run python -m src.chromasky_toolkit.main --convert-webp        # PNG → WebP 转换（含陈旧清理）
uv run python -m src.chromasky_toolkit.main --generate-tiles      # 从已有结果重新生成 XYZ 瓦片

# Web 服务（/、/future、/history、/api/events、POST /trigger-job）
uv run uvicorn src.chromasky_toolkit.server:app --reload

# 清理历史分时图残留（默认 dry-run，加 --yes 才真正删除）
uv run python tools/cleanup_legacy_maps.py
uv run python tools/cleanup_legacy_maps.py --yes

# 测试与静态检查（跳过真实 CAMS API 调用）
uv run pytest tests/ -q -k "not TestCAMSAPICall"
uv run python -m compileall -q src tools

# Docker
docker build -t chromasky-toolkit .
docker compose up -d   # 宿主机端口 8002 → 容器 8000
```

## Architecture

### 数据流水线（五阶段）

1. **数据获取** (`data_acquisition.py`): 下载 GFS 云量 + CAMS 气溶胶数据，将 CAMS 重采样到 GFS 网格，保存为 `.nc` 文件到 `data/processed/future/`
2. **事件展开** (`processing.py`): `expand_all_future_events()` 覆盖今天起 5 天内所有日出/日落时间点
3. **指数计算** (`glow_index.py`): `GlowIndexCalculator` 逐网格评分：`最终得分 = 品质分(云边界距离/HCC/MCC) × 惩罚分(LCC/AOD)`，支持多核并行；结果存 `outputs/calculations/{date}/glow_index_result_{HHMM}.nc`
4. **地图生成** (`mapping.py` → `map_drawer.py`): Matplotlib + Cartopy 暗色主题地图，含高斯平滑。**分时图已停用**，每个「日期 + 事件」只输出一张综合最佳图 `outputs/maps/composite/glow_index_composite_{date}_{event}.png`
5. **转换与瓦片** (`image_converter.py` → `tile_generator.py`): PNG→WebP 增量转换并清理陈旧 WebP；再基于综合图生成 XYZ 瓦片到 `chroma-sky-tiles/`

完整工作流由 `main.run_full_workflow()` 串起；`server.py` 用 APScheduler 每 3 小时（cron `0,3,6,9,12,15,18,21`）触发一次，也可 `POST /trigger-job` 手动触发。

### Web UI

| 路由 | 说明 |
|------|------|
| `GET /` | 首页：Hero（进行中 / 最近未来事件，无未来时回退最近存档）+「接下来」+「近日回看」 |
| `GET /future` | 未来预报：按天分组列出已生成存档且未结束的事件 |
| `GET /history` | 历史存档：`scope` / `event` / `from` / `to` / `date` / `sort` 筛选，按月分组 |
| `GET /archive` | 307 重定向到 `/history`（兼容旧链接） |
| `GET /api/events` | 事件列表 JSON（`limit` 1–500） |
| `POST /trigger-job` | 手动触发完整工作流 |
| `GET /api/glow-index` | 单点指数查询 |
| `/static/*` | `outputs/` 目录（WebP/PNG 图片） |
| `/assets/*` | `src/static/` 目录（CSS/JS） |

- `gallery.py`: 扫描 `outputs/maps_webp/composite/`（缺失时回退 `outputs/maps/composite/`），构造事件对象、状态判定、Hero 选择、筛选与月份分组；所有时间按 `Asia/Shanghai`，生成时间取文件 mtime
- 模板在 `src/templates/`（`base.html` / `index.html` / `future.html` / `history.html`），静态资源在 `src/static/`
- 字段与路由契约见 `docs/web-ui.md`

### 核心模块

| 模块 | 职责 |
|------|------|
| `config.py` | 中央配置：地理范围、时间窗口（`event_times_for_date` 按目标日期月份选季节）、所有路径常量 |
| `astronomy.py` | 天文计算：日出/日落时间、太阳位置 |
| `server.py` | FastAPI Web 服务 + APScheduler 定时任务（每 3 小时） |
| `gallery.py` | Web UI 图库数据层：扫描综合图、状态判定、Hero、筛选、月份分组 |
| `main.py` | 命令行入口与 `run_full_workflow()` |
| `mapping.py` | 只生成综合最佳图（分时图已停用） |
| `image_converter.py` | PNG → WebP 增量转换 + 陈旧 WebP 清理（`plan_conversion`） |
| `tile_generator.py` | 基于综合图生成 XYZ 瓦片 |
| `input_visualizer.py` | 输入数据调试可视化 |
| `tools/cleanup_legacy_maps.py` | 清理历史 `individual` 目录与陈旧 WebP（默认 dry-run） |

### 关键设计

- **地理范围三级结构**: `DISPLAY_AREA`（展示）→ `CALCULATION_AREA`（计算）→ `DOWNLOAD_AREA`（下载缓冲，各扩展 15°）
- **季节自适应时间窗口**: 导入时按当前月份选择 `SUNRISE_EVENT_TIMES` / `SUNSET_EVENT_TIMES`；查看历史或未来日期时用 `config.event_times_for_date(target_date, event)` 按目标日期的月份选季节，不能用「当前季节」推断
- **事件驱动**: 所有计算围绕「今天起 5 天内」的所有日出/日落事件展开（`expand_all_future_events`）
- **存档产物**: 综合图是唯一存档产物（`outputs/maps/composite/` → `outputs/maps_webp/composite/`）；分时图（`individual`）不再生成、存储、展示，历史残留用 `tools/cleanup_legacy_maps.py` 清理
- **数据格式**: 中间数据为 NetCDF (`.nc`)，最终输出 PNG/WebP，地图叠加层另有 XYZ 瓦片

### 路径约定

- 源码在 `src/chromasky_toolkit/`；模板在 `src/templates/`；静态资源在 `src/static/`
- `config.py` 中 `PROJECT_ROOT` = `src/` 目录，`LOG_BASE_PATH` = 项目根目录；数据路径使用 `PROJECT_ROOT.parent / "xxx"` 指向项目根目录下的 `data/`、`outputs/`、`map_data/`、`fonts/`、`chroma-sky-tiles/`
- 运行前需要 `.env` 文件配置 `CDS_API_KEY`（格式: `UID:API_KEY`），可选 `TILES_HOST_PATH`、`GITHUB_ACCELERATE`、`NUM_WORKERS` 与 `DISPLAY_*` / `CALC_*` / `DOWNLOAD_*` 地理范围变量

## Code Style

- 使用中文注释
- 日志使用 `logging` 模块，logger 命名按模块区分
- 类型注解使用 Python 3.12+ 语法（`str | None` 而非 `Optional[str]`）