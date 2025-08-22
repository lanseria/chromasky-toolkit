# src/chromasky_toolkit/server.py

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .main import run_full_workflow

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ChromaSkyServer")

# --- 定时任务逻辑 ---
scheduler = AsyncIOScheduler()

def run_scheduled_job():
    """
    这是定时任务和手动触发要执行的函数。
    它会调用项目的核心工作流。
    """
    logger.info("====== [Job Runner] 开始执行完整工作流 ======")
    try:
        run_full_workflow()
        logger.info("====== [Job Runner] 完整工作流执行成功 ======")
    except Exception as e:
        logger.error(f"====== [Job Runner] 完整工作流执行失败: {e} ======", exc_info=True)

# --- FastAPI 应用生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 应用启动时执行
    logger.info("服务器启动，初始化定时任务...")
    scheduler.add_job(run_scheduled_job, 'cron', hour=1, minute=30, id="daily_chromasky_job")
    scheduler.start()
    yield
    # 应用关闭时执行
    logger.info("服务器关闭，停止定时任务...")
    scheduler.shutdown()

# --- 创建 FastAPI 应用实例 ---
app = FastAPI(lifespan=lifespan)

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
    background_tasks.add_task(run_scheduled_job)
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