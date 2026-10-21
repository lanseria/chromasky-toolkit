# src/chromasky_toolkit/image_converter.py

import logging
import sys
from dataclasses import dataclass, field
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


@dataclass
class ConversionPlan:
    """一次 PNG → WebP 增量转换的扫描结果（纯数据，无任何副作用）。

    Attributes:
        pending: 需要转换的源 PNG（目标 WebP 缺失或比源文件旧）。
        stale: 源 PNG 已不存在的目标 WebP（如历史分时图残留），应删除。
        up_to_date: 目标 WebP 已存在且不早于源 PNG，可跳过转换。
    """

    pending: list[Path] = field(default_factory=list)
    stale: list[Path] = field(default_factory=list)
    up_to_date: list[Path] = field(default_factory=list)


def plan_conversion(source_dir: Path, target_dir: Path) -> ConversionPlan:
    """扫描源 PNG 与目标 WebP，判定待转换 / 陈旧 / 已是最新三类文件。

    该函数是纯函数：只读取文件系统状态，不创建、不修改、不删除任何文件，
    便于单元测试与在 dry-run 场景下复用。

    约定 source_dir 与 target_dir 是「相对目录结构一一对应」的两个根目录：
    ``source_dir/a/b.png`` 对应 ``target_dir/a/b.webp``。

    Args:
        source_dir: PNG 源目录根（如 ``outputs/maps``）。
        target_dir: WebP 目标目录根（如 ``outputs/maps_webp``）。

    Returns:
        ConversionPlan: 三类路径列表，均按路径排序，来源为实际扫描到的文件。
        源目录不存在时返回空计划（不做任何「陈旧」推断，避免误删）。
    """
    plan = ConversionPlan()
    if not source_dir.exists():
        return plan

    # 已扫描到的源 PNG 对应的目标相对路径集合，用于反向判定陈旧 WebP
    expected_targets: set[str] = set()

    png_files = sorted(p for p in source_dir.rglob("*.png") if p.is_file())
    for png_path in png_files:
        relative_target = png_path.relative_to(source_dir).with_suffix(".webp")
        expected_targets.add(relative_target.as_posix())
        target_path = target_dir / relative_target
        # 增量转换：目标 WebP 已存在且不早于源文件时跳过，避免每次全量重转
        if target_path.is_file() and target_path.stat().st_mtime >= png_path.stat().st_mtime:
            plan.up_to_date.append(png_path)
        else:
            plan.pending.append(png_path)

    # 目标目录中「源 PNG 已不存在」的 WebP 视为陈旧文件
    if target_dir.exists():
        webp_files = sorted(p for p in target_dir.rglob("*.webp") if p.is_file())
        for webp_path in webp_files:
            relative_target = webp_path.relative_to(target_dir).as_posix()
            if relative_target not in expected_targets:
                plan.stale.append(webp_path)

    return plan


def _display_path(path: Path) -> str:
    """日志展示用路径：尽量使用相对项目根目录的形式，失败时回退绝对路径。"""
    try:
        return str(path.relative_to(config.LOG_BASE_PATH))
    except ValueError:
        return str(path)


def _convert_single_image(source_path: Path, source_dir: Path, target_dir: Path) -> tuple[str, str | None]:
    """
    将单个 PNG 图像转换为 WebP 格式。
    在单独的进程中运行。
    """
    try:
        # 构建目标路径：保持与源目录一致的相对结构
        relative_path = source_path.relative_to(source_dir)
        target_path = (target_dir / relative_path).with_suffix(".webp")

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

        return _display_path(source_path), _display_path(target_path)
    except Exception as e:
        logger.error(f"转换文件 {source_path.name} 失败: {e}")
        return _display_path(source_path), None


def _delete_stale_webp(stale_paths: list[Path]) -> int:
    """删除源 PNG 已不存在的陈旧 WebP，返回成功删除的数量。"""
    removed = 0
    for path in stale_paths:
        try:
            path.unlink()
            removed += 1
            logger.debug(f"  🗑️ 已删除陈旧 WebP: {_display_path(path)}")
        except FileNotFoundError:
            # 扫描到删除之间被其他进程删除：无需处理
            continue
        except OSError as e:
            logger.warning(f"删除陈旧 WebP 失败 {_display_path(path)}: {e}")
    return removed


def _prune_empty_dirs(root: Path) -> int:
    """自底向上删除清理后变空的子目录（保留 root 本身），返回删除数量。"""
    if not root.exists():
        return 0
    removed = 0
    # 按路径深度倒序，先删深层空目录，父目录才可能变为空
    directories = sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()  # 仅空目录能删除成功
            removed += 1
        except OSError:
            continue
    return removed


def run_conversion():
    """
    扫描 `outputs/maps` 目录下的所有 PNG 文件，并将它们并行转换为 WebP 格式，
    存放到 `outputs/maps_webp` 目录中。

    同时执行「陈旧 WebP 清理」：目标目录中源 PNG 已不存在的 `.webp`（例如已停用的
    分时图残留）会被删除，并清理因此变空的子目录，防止旧分时图再次出现在 Web 端。
    """
    logger.info("====== 开始执行 PNG 到 WebP 格式转换流程 ======")

    source_dir = config.MAP_OUTPUTS_DIR
    target_dir = config.MAP_WEBP_OUTPUTS_DIR

    if not source_dir.exists():
        logger.warning(f"源图片目录不存在: {source_dir}，跳过转换与陈旧文件清理。")
        return

    # 1. 先做一次纯扫描，得到待转换 / 陈旧 / 已最新三类文件
    plan = plan_conversion(source_dir, target_dir)

    # 2. 清理陈旧 WebP：源 PNG 已不存在的目标文件（如历史分时图残留）
    if plan.stale:
        removed_count = _delete_stale_webp(plan.stale)
        pruned_dir_count = _prune_empty_dirs(target_dir)
        message = f"清理陈旧 WebP: {removed_count} 个（对应源 PNG 已不存在）"
        if pruned_dir_count:
            message += f"，并移除 {pruned_dir_count} 个空目录"
        logger.info(message)
    else:
        logger.info("未发现需要清理的陈旧 WebP。")

    # 3. 增量转换
    if not plan.pending and not plan.up_to_date:
        logger.info("在源目录中未找到任何 PNG 文件。")
        logger.info("====== 格式转换流程执行完毕！ ======")
        return

    if plan.up_to_date:
        logger.info(f"跳过 {len(plan.up_to_date)} 个已是最新状态的 PNG 文件。")
    if not plan.pending:
        logger.info("所有图片均已转换完毕，无需处理。")
        logger.info("====== 格式转换流程执行完毕！ ======")
        return

    png_files = plan.pending
    logger.info(f"找到 {len(png_files)} 个 PNG 文件准备转换到 WebP 格式。")
    logger.info(f"目标目录: {_display_path(target_dir)}")
    logger.info(f"转换参数: Quality={WEBP_QUALITY}, Effort(Method)={WEBP_METHOD}")

    # 使用并行处理加速转换
    num_workers = config.NUM_WORKERS
    success_count = 0
    fail_count = 0

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(_convert_single_image, png_path, source_dir, target_dir)
            for png_path in png_files
        ]

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
