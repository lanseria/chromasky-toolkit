# src/chromasky_toolkit/server.py

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config
from .main import run_full_workflow  # 我们将从重构后的 main.py 导入

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ChromaSkyServer")

# --- 定时任务逻辑 ---
scheduler = AsyncIOScheduler()

def run_scheduled_job():
    """
    这是定时任务要执行的函数。
    它会调用项目的核心工作流。
    """
    logger.info("====== [Scheduler] 开始执行每日定时任务 ======")
    try:
        run_full_workflow()
        logger.info("====== [Scheduler] 每日定时任务执行成功 ======")
    except Exception as e:
        logger.error(f"====== [Scheduler] 每日定时任务执行失败: {e} ======", exc_info=True)

# --- FastAPI 应用生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 应用启动时执行
    logger.info("服务器启动，初始化定时任务...")
    # 添加定时任务：每天凌晨 1:30 执行一次
    # 使用 cron 触发器，可以非常灵活地定义时间
    scheduler.add_job(run_scheduled_job, 'cron', hour=1, minute=30, id="daily_chromasky_job")
    scheduler.start()
    # 立即触发一次，方便测试
    # run_scheduled_job()
    yield
    # 应用关闭时执行
    logger.info("服务器关闭，停止定时任务...")
    scheduler.shutdown()

# --- 创建 FastAPI 应用实例 ---
app = FastAPI(lifespan=lifespan)

# --- 挂载静态文件目录 ---
# 这样才能通过 URL 访问 outputs 目录下的图片
app.mount("/static", StaticFiles(directory=config.PROJECT_ROOT / "outputs"), name="static")

# --- 设置模板引擎 ---
templates = Jinja2Templates(directory=config.PROJECT_ROOT / "templates")


# --- 定义路由和视图函数 ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    主页路由，用于展示生成的地图图片。
    """
    image_groups = []
    
    # 1. 扫描 composite (综合图) 目录
    composite_dir = config.MAP_OUTPUTS_DIR / "composite"
    if composite_dir.exists():
        composite_images = []
        for img_path in sorted(composite_dir.glob("*.png"), reverse=True):
            composite_images.append({
                "title": img_path.stem,
                "url": f"/static/maps/composite/{img_path.name}"
            })
        if composite_images:
            image_groups.append({"group_title": "综合最佳指数图", "images": composite_images})

    # 2. 扫描 individual (分时图) 目录
    individual_dir = config.MAP_OUTPUTS_DIR / "individual"
    if individual_dir.exists():
        # 按日期倒序查找子目录
        date_dirs = sorted([d for d in individual_dir.iterdir() if d.is_dir()], reverse=True)
        for date_dir in date_dirs:
            date_images = []
            for img_path in sorted(date_dir.glob("*.png")):
                date_images.append({
                    "title": img_path.stem.replace("glow_index_", ""),
                    "url": f"/static/maps/individual/{date_dir.name}/{img_path.name}"
                })
            if date_images:
                image_groups.append({"group_title": f"分时指数图 - {date_dir.name}", "images": date_images})

    # 3. 渲染模板
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "image_groups": image_groups}
    )