# src/chromasky_toolkit/server.py

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, BackgroundTasks, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import xarray as xr

from . import config
from .astronomy import AstronomyService
from .glow_index import GlowIndexCalculator
from .main import run_full_workflow

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ChromaSkyServer")

# --- 定时任务逻辑 ---
scheduler = AsyncIOScheduler()

# 0点：生成今日朝霞 + 今日晚霞
MORNING_EVENTS = ['today_sunrise', 'today_sunset']
# 12点：生成今日晚霞(最新版) + 明日朝霞
NOON_EVENTS = ['today_sunset', 'tomorrow_sunrise']


def _run_job(event_intentions: list[str], label: str):
    """执行指定事件意图的工作流。"""
    logger.info(f"====== [Job Runner] {label} 开始执行 ======")
    try:
        run_full_workflow(event_intentions=event_intentions)
        logger.info(f"====== [Job Runner] {label} 执行成功 ======")
    except Exception as e:
        logger.error(f"====== [Job Runner] {label} 执行失败: {e} ======", exc_info=True)

# --- FastAPI 应用生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 应用启动时执行
    logger.info("服务器启动，初始化定时任务...")
    # 0:00 生成今日朝霞 + 今日晚霞
    scheduler.add_job(
        _run_job, 'cron', hour=0, minute=0,
        args=[MORNING_EVENTS, "0点任务(朝霞+晚霞)"],
        id="morning_chromasky_job"
    )
    # 12:00 生成今日晚霞(最新版) + 明日朝霞
    scheduler.add_job(
        _run_job, 'cron', hour=12, minute=0,
        args=[NOON_EVENTS, "12点任务(晚霞最新版+明日朝霞)"],
        id="noon_chromasky_job"
    )
    scheduler.start()
    yield
    # 应用关闭时执行
    logger.info("服务器关闭，停止定时任务...")
    scheduler.shutdown()

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
app.mount("/static", StaticFiles(directory=config.OUTPUTS_DIR), name="static")

# --- 设置模板引擎 ---
templates = Jinja2Templates(directory=config.PROJECT_ROOT / "templates")


# --- 新增：API 端点，用于手动触发任务 ---
@app.post("/trigger-job", response_class=JSONResponse)
async def trigger_job_endpoint(background_tasks: BackgroundTasks):
    """
    异步触发一次完整的数据处理流程。
    """
    logger.info("====== [API] 接收到手动触发任务请求 ======")
    # 手动触发使用 0 点任务配置（朝霞 + 晚霞）
    background_tasks.add_task(_run_job, MORNING_EVENTS, "手动触发")
    return {"message": "任务已在后台开始运行。请稍后刷新页面查看结果。"}


# --- 新的根路由 / ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    主页：只显示最新的两个事件组的综合图和分时图。
    """
    image_groups = []
    composite_dir = config.MAP_WEBP_OUTPUTS_DIR / "composite"

    if composite_dir.exists():
        # 1. 找到所有综合图并按名称（日期）降序排序，取最新的两个
        all_composites = sorted(composite_dir.glob("*.webp"), reverse=True)
        latest_composites = all_composites[:2]

        for composite_path in latest_composites:
            # 2. 从综合图文件名解析出日期和事件类型
            # e.g., 'glow_index_composite_2025-08-21_sunset' -> '2025-08-21'
            date_str = composite_path.stem.split('_')[-2]
            
            group_data = {
                "group_title": f"预报 - {date_str}",
                "composite_image": {
                    "title": composite_path.stem,
                    "url": f"/static/maps_webp/composite/{composite_path.name}"
                },
                "individual_images": []
            }
            
            # 3. 根据日期查找对应的分时图
            individual_dir = config.MAP_WEBP_OUTPUTS_DIR / "individual" / date_str
            if individual_dir.exists():
                for img_path in sorted(individual_dir.glob(f"*_{date_str}_*.webp")):
                    group_data["individual_images"].append({
                        "title": img_path.stem.replace("glow_index_", ""),
                        "url": f"/static/maps_webp/individual/{date_str}/{img_path.name}"
                    })
            
            image_groups.append(group_data)

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "image_groups": image_groups}
    )


# --- 新的归档路由 /archive ---
@app.get("/archive", response_class=HTMLResponse)
async def read_archive(request: Request):
    """
    归档页：展示所有生成的地图图片。
    """
    image_groups = []
    
    # 逻辑与旧版主页完全相同
    composite_dir = config.MAP_WEBP_OUTPUTS_DIR / "composite"
    if composite_dir.exists():
        composite_images = []
        for img_path in sorted(composite_dir.glob("*.webp"), reverse=True):
            composite_images.append({
                "title": img_path.stem,
                "url": f"/static/maps_webp/composite/{img_path.name}"
            })
        if composite_images:
            image_groups.append({"group_title": "综合最佳指数图", "images": composite_images})

    individual_dir = config.MAP_WEBP_OUTPUTS_DIR / "individual"
    if individual_dir.exists():
        date_dirs = sorted([d for d in individual_dir.iterdir() if d.is_dir()], reverse=True)
        for date_dir in date_dirs:
            date_images = []
            for img_path in sorted(date_dir.glob("*.webp")):
                date_images.append({
                    "title": img_path.stem.replace("glow_index_", ""),
                    "url": f"/static/maps_webp/individual/{date_dir.name}/{img_path.name}"
                })
            if date_images:
                image_groups.append({"group_title": f"分时指数图 - {date_dir.name}", "images": date_images})

    return templates.TemplateResponse(
        "archive.html",
        {"request": request, "image_groups": image_groups}
    )


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