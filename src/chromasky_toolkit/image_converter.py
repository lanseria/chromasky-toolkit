# src/chromasky_toolkit/image_converter.py

import logging
import sys
from pathlib import Path
from PIL import Image
from tqdm.auto import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

from . import config

logger = logging.getLogger("ImageConverter")


def _tqdm(iterable=None, **kwargs):
    """非 TTY 环境（容器/重定向日志）下禁用进度条，避免污染日志输出。"""
    kwargs.setdefault('disable', not sys.stderr.isatty())
    return tqdm(iterable, **kwargs)

# 定义 WebP 转换参数
WEBP_QUALITY = 75
WEBP_METHOD = 4  # 0=fast, 6=slowest; 4 is a good balance

def _convert_single_image(source_path: Path) -> tuple[str, str | None]:
    """
    将单个 PNG 图像转换为 WebP 格式。
    在单独的进程中运行。
    """
    try:
        # 构建目标路径
        relative_path = source_path.relative_to(config.MAP_OUTPUTS_DIR)
        target_path = (config.OUTPUTS_DIR / "maps_webp" / relative_path).with_suffix(".webp")
        
        # 确保目标目录存在
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 打开图像并转换
        with Image.open(source_path) as img:
            # 确保图像是 RGBA 模式以保留透明度
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            img.save(
                target_path,
                'WEBP',
                quality=WEBP_QUALITY,
                method=WEBP_METHOD
            )
        
        return str(source_path.relative_to(config.LOG_BASE_PATH)), str(target_path.relative_to(config.LOG_BASE_PATH))
    except Exception as e:
        logger.error(f"转换文件 {source_path.name} 失败: {e}")
        return str(source_path.relative_to(config.LOG_BASE_PATH)), None

def run_conversion():
    """
    扫描 `outputs/maps` 目录下的所有 PNG 文件，并将它们并行转换为 WebP 格式，
    存放到 `outputs/maps_webp` 目录中。
    """
    logger.info("====== 开始执行 PNG 到 WebP 格式转换流程 ======")
    
    source_dir = config.MAP_OUTPUTS_DIR
    target_dir = config.OUTPUTS_DIR / "maps_webp"

    if not source_dir.exists():
        logger.warning(f"源图片目录不存在: {source_dir}，跳过转换。")
        return

    # 扫描所有 .png 文件
    png_files = list(source_dir.glob("**/*.png"))
    if not png_files:
        logger.info("在源目录中未找到任何 PNG 文件。")
        logger.info("====== 格式转换流程执行完毕！ ======")
        return

    # 增量转换：目标 WebP 已存在且不早于源文件时跳过，避免每次全量重转
    pending_files = []
    skipped_count = 0
    for png_path in png_files:
        relative_path = png_path.relative_to(config.MAP_OUTPUTS_DIR)
        target_path = (target_dir / relative_path).with_suffix(".webp")
        if target_path.exists() and target_path.stat().st_mtime >= png_path.stat().st_mtime:
            skipped_count += 1
            continue
        pending_files.append(png_path)

    if skipped_count:
        logger.info(f"跳过 {skipped_count} 个已是最新状态的 PNG 文件。")
    if not pending_files:
        logger.info("所有图片均已转换完毕，无需处理。")
        logger.info("====== 格式转换流程执行完毕！ ======")
        return

    png_files = pending_files
    logger.info(f"找到 {len(png_files)} 个 PNG 文件准备转换到 WebP 格式。")
    logger.info(f"目标目录: {target_dir.relative_to(config.LOG_BASE_PATH)}")
    logger.info(f"转换参数: Quality={WEBP_QUALITY}, Effort(Method)={WEBP_METHOD}")
    
    # 使用并行处理加速转换
    num_workers = config.NUM_WORKERS
    success_count = 0
    fail_count = 0

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_convert_single_image, png_path) for png_path in png_files]
        
        with _tqdm(total=len(futures), desc="Converting to WebP") as pbar:
            for future in as_completed(futures):
                source, result = future.result()
                if result:
                    success_count += 1
                    logger.debug(f"  ✅ {source} -> {result}")
                else:
                    fail_count += 1
                pbar.update(1)

    logger.info(f"转换完成: {success_count} 个成功, {fail_count} 个失败。")
    logger.info("====== 格式转换流程执行完毕！ ======")