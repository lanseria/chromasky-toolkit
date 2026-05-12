# src/chromasky_toolkit/tile_generator.py

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import gaussian_filter
import matplotlib.colors as mcolors
import itertools

from . import config

logger = logging.getLogger(__name__)


def tile_to_wgs84(z: int, x: int, y: int, tile_size: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """将瓦片内每个像素转换为 WGS84 经纬度坐标。

    Returns:
        (lats, lons): 形状为 (tile_size, tile_size) 的二维数组
    """
    n = 2 ** z
    px = np.arange(tile_size) + 0.5
    py = np.arange(tile_size) + 0.5

    # 全局像素坐标
    pixel_x = x * tile_size + px
    pixel_y = y * tile_size + py

    # 归一化坐标 [0, 1]
    norm_x = pixel_x / (n * tile_size)
    norm_y = pixel_y / (n * tile_size)

    norm_x_grid, norm_y_grid = np.meshgrid(norm_x, norm_y)

    # 经度: 直接线性映射
    lons = norm_x_grid * 360.0 - 180.0

    # 纬度: Web Mercator 逆变换
    lat_rad = np.arctan(np.sinh(np.pi * (1.0 - 2.0 * norm_y_grid)))
    lats = np.degrees(lat_rad)

    return lats, lons


def get_tiles_for_area(area: dict, z: int) -> list[tuple[int, int, int]]:
    """计算指定缩放级别下覆盖给定区域的所有瓦片坐标。

    Args:
        area: 地理范围字典，包含 north/south/west/east
        z: 缩放级别

    Returns:
        [(z, x, y), ...] 瓦片坐标列表
    """
    n = 2 ** z

    # 经度 → x
    x_min = max(0, int(np.floor((area["west"] + 180) / 360.0 * n)))
    x_max = min(n - 1, int(np.floor((area["east"] + 180) / 360.0 * n)))

    # 纬度 → y (Web Mercator)
    def lat_to_y(lat: float) -> int:
        lat_rad = np.radians(np.clip(lat, -85.051, 85.051))
        y = int(np.floor((1.0 - np.log(np.tan(lat_rad) + 1.0 / np.cos(lat_rad)) / np.pi) / 2.0 * n))
        return max(0, min(n - 1, y))

    y_min = lat_to_y(area["north"])
    y_max = lat_to_y(area["south"])

    tiles = []
    for tx in range(x_min, x_max + 1):
        for ty in range(y_min, y_max + 1):
            tiles.append((z, tx, ty))

    return tiles


def prepare_tile_data(score_grid: xr.DataArray) -> tuple[RegularGridInterpolator | None, float]:
    """预处理数据并构建插值器。

    与 map_drawer.py 使用相同的预处理流程：高斯平滑 → 4x 三次插值 → 阈值过滤。

    Returns:
        (interpolator, score_max): 插值器和全局最大值。数据为空时返回 (None, 0)
    """
    # 高斯平滑
    scores_for_smoothing = score_grid.fillna(0).values
    smoothed_scores = gaussian_filter(scores_for_smoothing, sigma=1.5)
    smoothed_grid = xr.DataArray(smoothed_scores, coords=score_grid.coords, dims=score_grid.dims)

    # 4x 三次插值
    interp_factor = 4
    orig_lats = smoothed_grid.latitude.values
    orig_lons = smoothed_grid.longitude.values
    new_lats = np.linspace(orig_lats.min(), orig_lats.max(), len(orig_lats) * interp_factor)
    new_lons = np.linspace(orig_lons.min(), orig_lons.max(), len(orig_lons) * interp_factor)
    high_res_grid = smoothed_grid.interp(latitude=new_lats, longitude=new_lons, method='cubic')
    scores = high_res_grid.values

    if np.all(np.isnan(scores)) or np.nanmax(scores) == 0:
        return None, 0.0

    # 阈值过滤：小于最大值 5% 的设为 NaN
    score_max = np.nanmax(scores)
    scores[scores < score_max * 0.05] = np.nan

    interpolator = RegularGridInterpolator(
        (high_res_grid.latitude.values, high_res_grid.longitude.values),
        scores,
        method='linear',
        bounds_error=False,
        fill_value=np.nan,
    )

    return interpolator, float(score_max)


def create_colormap_lut() -> np.ndarray:
    """预计算 256 色颜色查找表。

    Returns:
        (256, 4) uint8 数组，每行为 RGBA 值
    """
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "chromasky", list(zip(config.CHROMA_SKY_COLOR_NODES, config.CHROMA_SKY_COLORS))
    )
    lut = cmap(np.linspace(0, 1, 256))
    return (lut * 255).astype(np.uint8)


def generate_single_tile(
    z: int,
    x: int,
    y: int,
    interpolator: RegularGridInterpolator,
    score_max: float,
    cmap_lut: np.ndarray,
    tile_size: int = 256,
) -> Image.Image:
    """渲染单个瓦片为 RGBA 图像。

    Args:
        z, x, y: 瓦片坐标
        interpolator: 数据插值器
        score_max: 全局最大值（用于归一化）
        cmap_lut: 颜色查找表
        tile_size: 瓦片尺寸

    Returns:
        PIL RGBA Image
    """
    lats, lons = tile_to_wgs84(z, x, y, tile_size)

    # 采样数据
    points = np.stack([lats.ravel(), lons.ravel()], axis=-1)
    sampled = interpolator(points).reshape(tile_size, tile_size)

    # 归一化到 [0, 1]
    normalized = np.where(np.isnan(sampled), 0, sampled / score_max)
    normalized = np.clip(normalized, 0, 1)

    # 查颜色表
    indices = (normalized * 255).astype(np.int32)
    indices = np.clip(indices, 0, 255)
    rgba = cmap_lut[indices]  # (tile_size, tile_size, 4)

    # NaN 区域设为透明
    nan_mask = np.isnan(sampled)
    rgba[nan_mask, 3] = 0

    return Image.fromarray(rgba.astype(np.uint8), 'RGBA')


def generate_tiles_for_event(
    score_grid: xr.DataArray,
    group_key: str,
    base_path: Path | None = None,
    zoom_levels: range | None = None,
    tile_size: int | None = None,
) -> int:
    """为单个事件组生成 XYZ 瓦片。

    Args:
        score_grid: 综合火烧云指数数据
        group_key: 事件组标识，如 "2026-05-11_sunset"
        base_path: 瓦片输出根目录，默认使用 config.TILE_OUTPUT_DIR
        zoom_levels: 缩放级别范围，默认 config.TILE_ZOOM_MIN 到 TILE_ZOOM_MAX
        tile_size: 瓦片尺寸，默认 config.TILE_SIZE

    Returns:
        生成的瓦片总数
    """
    if base_path is None:
        base_path = config.TILE_OUTPUT_DIR
    if zoom_levels is None:
        zoom_levels = range(config.TILE_ZOOM_MIN, config.TILE_ZOOM_MAX + 1)
    if tile_size is None:
        tile_size = config.TILE_SIZE

    # 从 group_key 推导瓦片文件名: "2026-05-11_sunset" -> "20260511-sunset"
    date_str, event_type = group_key.split('_')
    tile_name = date_str.replace('-', '') + '-' + event_type

    logger.info(f"开始为事件 '{group_key}' 生成 XYZ 瓦片 (文件名: {tile_name}.png)")

    # 预处理数据
    interpolator, score_max = prepare_tile_data(score_grid)
    if interpolator is None or score_max == 0:
        logger.warning(f"事件 '{group_key}' 数据为空或全为零，跳过瓦片生成。")
        return 0

    # 预计算颜色查找表
    cmap_lut = create_colormap_lut()

    total_count = 0
    for z in zoom_levels:
        tiles = get_tiles_for_area(config.DISPLAY_AREA, z)
        z_count = 0

        for tz, tx, ty in tiles:
            tile_img = generate_single_tile(tz, tx, ty, interpolator, score_max, cmap_lut, tile_size)

            output_path = base_path / str(tz) / str(tx) / str(ty) / f"{tile_name}.png"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            tile_img.save(output_path, 'PNG')
            z_count += 1

        total_count += z_count
        logger.info(f"  Zoom {z}: 已生成 {z_count} 个瓦片")

    logger.info(f"事件 '{group_key}' 瓦片生成完毕，共 {total_count} 个")

    # 更新瓦片资源清单
    update_tiles_manifest(date_str.replace('-', ''), event_type)

    return total_count


def run_tile_generation():
    """从已有计算结果重新生成 XYZ 瓦片（独立模式，不绘制地图）。"""
    from .processing import expand_target_events

    logger.info("====== 开始执行 XYZ 瓦片生成流程 ======")

    target_events = expand_target_events()
    if not target_events:
        logger.warning("没有找到需要处理的事件。")
        return

    event_grouper = lambda name: "_".join(name.split('_')[:2])
    sorted_events = sorted(target_events.items(), key=lambda item: event_grouper(item[0]))

    for group_key, group_events_iterator in itertools.groupby(
        sorted_events, key=lambda item: event_grouper(item[0])
    ):
        group_events = list(group_events_iterator)
        all_arrays = []

        for event_name, _ in group_events:
            date_str, event_type, time_str = event_name.split('_')
            result_path = config.CALCULATION_OUTPUTS_DIR / date_str / f"glow_index_result_{time_str}.nc"
            if result_path.exists():
                ds = xr.open_dataset(result_path)
                all_arrays.append(ds['final_score'])
            else:
                logger.warning(f"  计算结果文件未找到: {result_path}")

        if all_arrays:
            combined = xr.concat(all_arrays, dim='time').max(dim='time')
            count = generate_tiles_for_event(combined, group_key)
            logger.info(f"组 '{group_key}': 已生成 {count} 个瓦片")
        else:
            logger.warning(f"组 '{group_key}': 没有可用的计算数据")

    logger.info("====== XYZ 瓦片生成流程执行完毕！ ======")


def update_tiles_manifest(date: str, event: str) -> None:
    """更新瓦片资源清单文件。

    Args:
        date: 日期字符串，格式 YYYYMMDD
        event: 事件类型，sunrise 或 sunset
    """
    manifest_path = config.TILE_MANIFEST_PATH
    now = datetime.now().astimezone().isoformat()

    # 读取已有清单
    if manifest_path.exists():
        with open(manifest_path, encoding='utf-8') as f:
            manifest = json.load(f)
    else:
        manifest = {"lastUpdated": now, "resources": []}

    # 查找并更新或追加
    for item in manifest["resources"]:
        if item["date"] == date and item["event"] == event:
            item["generatedAt"] = now
            break
    else:
        manifest["resources"].append({
            "date": date,
            "event": event,
            "generatedAt": now,
        })

    manifest["lastUpdated"] = now

    # 按日期+事件排序
    manifest["resources"].sort(key=lambda r: (r["date"], r["event"]))

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info(f"瓦片清单已更新: {date} {event}")
