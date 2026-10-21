# src/chromasky_toolkit/server.py

import logging
import mimetypes
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, BackgroundTasks, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import xarray as xr

from . import config, gallery
from .astronomy import AstronomyService
from .glow_index import GlowIndexCalculator
from .main import run_full_workflow

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ChromaSkyServer")

# --- 定时任务逻辑 ---
# 显式指定北京时区：容器默认可能是 UTC，cron 时刻会随之漂移。
# 频率本身是每 3 小时一档，但让触发时刻稳定在北京时间更符合预期。
scheduler = AsyncIOScheduler(timezone=ZoneInfo(config.LOCAL_TZ))


def _ensure_runtime_assets() -> None:
    """
    启动时自检地图底图与字体数据，缺失时自动补齐。
    场景：Docker 构建时下载数据的步骤可能因网络问题失败（或旧镜像未包含数据），
    且 map_data 不在任何持久化卷中，缺失会一直存在。这里在服务启动时自愈一次。
    """
    import subprocess
    import sys

    required_ok = all([
        config.CHINA_SHP_PATH.exists(),
        config.NINE_DASH_LINE_SHP_PATH.exists(),
        config.CITIES_CSV_PATH.exists(),
        (config.FONT_DIR / config.MAP_FONT_FILENAME).exists(),
    ])
    if required_ok:
        logger.info("✅ [自检] 地图底图与字体数据完整。")
        return

    logger.warning("[自检] 检测到地图/字体数据缺失，正在运行 tools/setup_map_data.py 补齐...")
    project_root = config.LOG_BASE_PATH
    try:
        result = subprocess.run(
            [sys.executable, str(project_root / "tools" / "setup_map_data.py")],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            logger.info("✅ [自检] 地图/字体数据补齐完成。")
        else:
            logger.error(
                f"[自检] 地图/字体数据补齐失败（退出码 {result.returncode}）。"
                f"输出: {result.stderr.strip() or result.stdout.strip()}"
            )
    except Exception as e:
        logger.error(f"[自检] 运行数据补齐脚本时出错: {e}")


def _run_scheduled_job():
    """定时任务入口：执行完整工作流，生成未来5天内所有日出日落事件。"""
    now_beijing = datetime.now(ZoneInfo(config.LOCAL_TZ))
    label = f"定时任务 {now_beijing.strftime('%H:%M')} 北京时间"
    logger.info(f"====== [Job Runner] {label} 开始执行 ======")
    try:
        run_full_workflow()
        logger.info(f"====== [Job Runner] {label} 执行成功 ======")
    except Exception as e:
        logger.error(f"====== [Job Runner] {label} 执行失败: {e} ======", exc_info=True)

# --- FastAPI 应用生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("服务器启动，初始化定时任务（每3小时执行一次）...")
    _ensure_runtime_assets()
    scheduler.add_job(
        _run_scheduled_job, 'cron', hour='0,3,6,9,12,15,18,21',
        id="chromasky_3hourly_job"
    )
    scheduler.start()
    yield
    logger.info("服务器关闭，停止定时任务...")
    scheduler.shutdown()

# --- 注册 WebP MIME 类型 ---
# Windows 的注册表/MIME 数据库不一定认识 .webp，mimetypes 会回退成 text/plain，
# 部分浏览器因此拒绝在 <img> 中渲染。显式注册，保证跨平台一致。
mimetypes.add_type("image/webp", ".webp")

# --- 创建 FastAPI 应用实例 ---
app = FastAPI(lifespan=lifespan)

# --- CORS 中间件，允许所有域名跨域访问 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 挂载静态文件目录 ---
# check_dir=False：目录缺失（如全新部署尚未产出 outputs/ 或前端 static/ 尚未就绪）
# 时服务仍可正常启动，而不是在 import 阶段直接崩溃。
app.mount(
    "/static",
    StaticFiles(directory=config.OUTPUTS_DIR, check_dir=False),
    name="static",
)
app.mount(
    "/assets",
    StaticFiles(directory=config.PROJECT_ROOT / "static", check_dir=False),
    name="assets",
)

# --- 设置模板引擎 ---
templates = Jinja2Templates(directory=config.PROJECT_ROOT / "templates")


# --- 数据装配辅助 ---
def _load_gallery(now: datetime) -> tuple[list[dict], dict]:
    """
    扫描存档并返回 (事件列表, 公共上下文)。

    同一份 now 同时传给扫描与上下文构造，保证状态判定一致。
    """
    events = gallery.scan_event_maps(now=now)
    return events, gallery.build_common_context(events, now=now)


# --- 今天是何时 ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    首页：最近的未来事件 Hero + 接下来列表 + 近日回看。

    上下文严格按 docs/web-ui.md 第 5.1/5.2 节提供；没有未来预报时 Hero
    由 gallery.select_hero 回退到最近一次存档（hero_kind="latest"）。
    """
    now = gallery.now_local()
    events, common = _load_gallery(now)
    home = gallery.build_home_context(events, now=now)
    context = {"request": request, "page": "home", **common, **home}
    return templates.TemplateResponse(request, "index.html", context)


# --- 未来预报页 ---
@app.get("/future", response_class=HTMLResponse)
async def read_future(request: Request):
    """未来预报：按天分组列出所有未结束事件（契约 5.3）。"""
    now = gallery.now_local()
    events, common = _load_gallery(now)
    future = gallery.build_future_context(events, now=now)
    context = {"request": request, "page": "future", **common, **future}
    return templates.TemplateResponse(request, "future.html", context)


# --- 历史存档页 ---
@app.get("/history", response_class=HTMLResponse)
async def read_history(
    request: Request,
    scope: str = Query("past", description="past / all / future"),
    event: str = Query("all", description="all / sunrise / sunset"),
    date_from: str = Query("", alias="from", description="起始日期 YYYY-MM-DD（含）"),
    date_to: str = Query("", alias="to", description="结束日期 YYYY-MM-DD（含）"),
    date_query: str = Query("", alias="date", description="精确日期；无存档时回退到最近一天"),
    sort: str = Query("desc", description="desc / asc"),
):
    """
    历史存档：筛选 + 按月分组 + 日期精确/最近查询（契约 5.4/5.5）。

    非法筛选值不返回 4xx：scope/event/sort 回退默认值，非法日期写入 filters_error。
    """
    now = gallery.now_local()
    events, common = _load_gallery(now)
    history = gallery.build_history_context(
        events,
        scope=scope,
        event=event,
        date_from=date_from,
        date_to=date_to,
        target_date=date_query,
        sort=sort,
        now=now,
    )
    context = {"request": request, "page": "history", **common, **history}
    return templates.TemplateResponse(request, "history.html", context)


# --- 旧归档链接兼容 ---
@app.get("/archive")
async def read_archive():
    """旧链接兼容：307 重定向到 /history。"""
    return RedirectResponse(url="/history", status_code=307)


# --- 事件列表 JSON API ---
@app.get("/api/events", response_class=JSONResponse)
async def api_events(
    scope: Literal["all", "past", "future"] = Query("all", description="all / past / future"),
    event: Literal["all", "sunrise", "sunset"] = Query("all", description="all / sunrise / sunset"),
    date_from: str = Query("", alias="from", description="起始日期 YYYY-MM-DD（含）"),
    date_to: str = Query("", alias="to", description="结束日期 YYYY-MM-DD（含）"),
    date_query: str = Query("", alias="date", description="精确日期；无存档时回退到最近一天"),
    limit: int = Query(50, ge=1, le=500, description="返回条数上限 1..500"),
):
    """
    事件列表查询（契约第 6 节）。

    返回 {"now", "count", "events"}；events 为按日期升序的事件对象，
    count 为本次响应实际返回的条数（已应用 limit）。
    """
    now = gallery.now_local()
    events = gallery.scan_event_maps(now=now)
    matched = gallery.filter_events(
        events,
        scope=scope,
        event=event,
        date_from=date_from,
        date_to=date_to,
        target_date=date_query,
        now=now,
    )
    matched = matched[:limit]
    return {
        "now": now.replace(microsecond=0).isoformat(),
        "count": len(matched),
        "events": matched,
    }


# --- 新增：API 端点，用于手动触发任务 ---
@app.post("/trigger-job", response_class=JSONResponse)
async def trigger_job_endpoint(background_tasks: BackgroundTasks):
    """异步触发一次完整的数据处理流程。"""
    logger.info("====== [API] 接收到手动触发任务请求 ======")
    background_tasks.add_task(_run_scheduled_job)
    return {"message": "任务已在后台开始运行，将生成未来5天内所有日出日落事件。请稍后刷新页面查看结果。"}


# --- 火烧云指数查询 API ---
@app.get("/api/glow-index", response_class=JSONResponse)
async def get_glow_index(
    lat: float = Query(..., ge=-90, le=90, description="纬度"),
    lon: float = Query(..., ge=-180, le=180, description="经度"),
    event: Literal["sunrise", "sunset"] = Query(..., description="日出或日落"),
    date: str = Query(..., description="日期，格式 YYYY-MM-DD"),
):
    """
    查询指定地点和日期的火烧云指数。
    根据经纬度计算真实的日出/日落时间，匹配最近的可用数据时间点。
    """
    # 解析日期
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，应为 YYYY-MM-DD")

    # 计算该点的真实日出/日落时间
    astro = AstronomyService()
    event_utc = astro._calculate_single_event_time(lat, lon, target_date, event)
    if event_utc is None:
        raise HTTPException(status_code=400, detail=f"该地点在 {date} 无{'日出' if event == 'sunrise' else '日落'}事件")

    date_str = target_date.strftime("%Y-%m-%d")

    # 在数据目录中查找离真实事件时间最近的数据文件
    # 数据文件名是北京时间(HHMM)，需将 UTC 转为本地时间后比较
    local_tz = ZoneInfo(config.LOCAL_TZ)
    event_local = event_utc.astimezone(local_tz)
    nearest_time = _find_nearest_data_time(date_str, event_local)
    if nearest_time is None:
        raise HTTPException(status_code=404, detail=f"未找到 {date_str} 的数据，请确认该日期已有数据下载")

    # 按优先级获取指数：预计算结果 > 原始数据实时计算
    scores = _load_precalculated_point(date_str, nearest_time, lat, lon)
    if scores is None:
        scores = _calculate_raw_point(date_str, nearest_time, lat, lon)
    if scores is None:
        raise HTTPException(status_code=404, detail=f"未找到 {date_str} 时间点 {nearest_time} 的数据")

    return {
        "lat": lat,
        "lon": lon,
        "date": date_str,
        "event": event,
        "event_time": event_local.strftime("%H:%M"),
        "data_time": f"{nearest_time[:2]}:{nearest_time[2:]}",
        **{k: round(v, 4) for k, v in scores.items()},
    }


def _find_nearest_data_time(date_str: str, event_local: datetime) -> str | None:
    """
    在预计算结果目录和原始数据目录中，查找离事件本地时间最近的数据时间点。
    数据文件名为北京时间 HHMM，event_local 也应为本地时间。
    """
    event_minutes = event_local.hour * 60 + event_local.minute
    candidates: set[str] = set()

    # 从预计算结果目录收集
    calc_dir = config.CALCULATION_OUTPUTS_DIR / date_str
    if calc_dir.exists():
        for f in calc_dir.glob("glow_index_result_*.nc"):
            candidates.add(f.stem.split("_")[-1])

    # 从原始数据目录收集
    data_dir = config.PROCESSED_DATA_DIR / "future" / date_str
    if data_dir.exists():
        for f in data_dir.glob("hcc_*.nc"):
            candidates.add(f.stem.split("_")[1])

    if not candidates:
        return None

    def time_diff(t: str) -> int:
        hh, mm = int(t[:2]), int(t[2:])
        return abs(hh * 60 + mm - event_minutes)

    return min(candidates, key=time_diff)


def _load_precalculated_point(date_str: str, time_str: str, lat: float, lon: float) -> dict | None:
    """从预计算结果中提取指定点、指定时间的指数。"""
    result_file = config.CALCULATION_OUTPUTS_DIR / date_str / f"glow_index_result_{time_str}.nc"
    if not result_file.exists():
        return None

    try:
        ds = xr.open_dataset(result_file)
        scores = {}
        for var in ["final_score"] + GlowIndexCalculator.ALL_FACTORS:
            if var in ds:
                scores[var] = float(ds[var].interp(latitude=lat, longitude=lon, method="linear").item())
        ds.close()
        return scores
    except Exception as e:
        logger.warning(f"读取预计算结果失败: {e}")
        return None


def _calculate_raw_point(date_str: str, time_str: str, lat: float, lon: float) -> dict | None:
    """从原始气象数据实时计算指定点、指定时间的指数。"""
    data_dir = config.PROCESSED_DATA_DIR / "future" / date_str
    required_vars = ["hcc", "mcc", "lcc", "aod550"]

    files = {var: data_dir / f"{var}_{time_str}.nc" for var in required_vars}
    if not all(f.exists() for f in files.values()):
        return None

    try:
        data_arrays = {var: xr.open_dataarray(fp).rename(var) for var, fp in files.items()}
        weather_ds = xr.Dataset(data_arrays)
        calculator = GlowIndexCalculator(weather_data=weather_ds)
        utc_time = datetime.fromisoformat(weather_ds.hcc.attrs["original_utc_time"])

        scores = calculator.calculate_for_point(lat, lon, utc_time)

        for da in data_arrays.values():
            da.close()
        return scores
    except Exception as e:
        logger.warning(f"实时计算失败: {e}")
        return None