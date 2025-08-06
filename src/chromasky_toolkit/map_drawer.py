# src/chromasky_toolkit/map_drawer.py

import argparse
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.io import shapereader
import numpy as np
import xarray as xr
import pandas as pd
from scipy.ndimage import gaussian_filter

from . import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MapDrawer")

# --- 关键修正：智能字体设置 ---
CHINESE_FONT_FOUND = False
try:
    # 只有当 config.MAP_FONT 有具体值时，才尝试设置它
    if config.MAP_FONT:
        plt.rcParams['font.sans-serif'] = [config.MAP_FONT]
        logger.info(f"已尝试设置指定字体: '{config.MAP_FONT}'。")
    
    # 无论是否设置特定字体，都设置这个以正确显示负号
    plt.rcParams['axes.unicode_minus'] = False
    
    # 一个简单的检查，看系统默认字体是否支持中文“你”
    # 这比检查特定字体更通用
    if 'SimHei' in plt.rcParams['font.sans-serif'] or \
        'Microsoft YaHei' in plt.rcParams['font.sans-serif'] or \
        'PingFang SC' in plt.rcParams['font.sans-serif']:
        CHINESE_FONT_FOUND = True
        logger.info(f"检测到系统默认字体支持中文。当前字体列表: {plt.rcParams['font.sans-serif']}")
    
except Exception as e:
    logger.warning(f"设置字体时发生错误: {e}")

if not CHINESE_FONT_FOUND:
    logger.warning("未检测到主流中文字体，中文可能无法正常显示。")

def generate_map_from_grid(data_grid: xr.DataArray, title: str, output_path: Path):
    """
    根据给定的数据网格生成一张精美的暗色主题地图。
    *** 已更新为最终的暗色主题样式 ***
    """
    print(f"--- 正在为 '{title}' 生成暗色主题地图... ---")

    # --- 数据预处理 ---
    # 高斯平滑和插值，让视觉效果更平滑
    scores_for_smoothing = data_grid.fillna(0).values
    smoothed_scores = gaussian_filter(scores_for_smoothing, sigma=1.5)
    smoothed_grid = xr.DataArray(smoothed_scores, coords=data_grid.coords, dims=data_grid.dims)
    
    interp_factor = 4
    orig_lats, orig_lons = smoothed_grid.latitude.values, smoothed_grid.longitude.values
    new_lats = np.linspace(orig_lats.min(), orig_lats.max(), len(orig_lats) * interp_factor)
    new_lons = np.linspace(orig_lons.min(), orig_lons.max(), len(orig_lons) * interp_factor)
    high_res_grid = smoothed_grid.interp(latitude=new_lats, longitude=new_lons, method='cubic')
    
    lats, lons, scores = high_res_grid.latitude.values, high_res_grid.longitude.values, high_res_grid.values
    
    # 过滤掉非常低的值，让地图主区域更突出
    if np.nanmax(scores) > 0:
        scores[scores < np.nanmax(scores) * 0.05] = np.nan

    proj = ccrs.PlateCarree()
    fig = plt.figure(figsize=(12, 10), facecolor='black')
    ax = fig.add_subplot(1, 1, 1, projection=proj)
    ax.set_facecolor('black')
    ax.set_extent([config.AREA_EXTRACTION[k] for k in ["west", "east", "south", "north"]], crs=proj)

    # 1. 设置深色背景
    ax.add_feature(cfeature.OCEAN.with_scale('50m'), facecolor='#0c0a09', zorder=0)
    ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor='#1c1917', edgecolor='none', zorder=0)

    # 2. 使用您喜欢的 ChromaSky 色彩映射表
    colors = ["#3b82f6", "#fde047", "#f97316", "#ef4444", "#ec4899"] # 蓝 -> 黄 -> 橙 -> 红 -> 粉
    nodes = [0.0, 0.5, 0.7, 0.85, 1.0]
    chromasky_cmap = mcolors.LinearSegmentedColormap.from_list("chromasky", list(zip(nodes, colors)))
    
    # 动态设置等值线级别
    min_val, max_val = np.nanmin(scores), np.nanmax(scores)
    levels = np.linspace(min_val, max_val, 100) if min_val < max_val else [min_val]
    
    # 绘制填充等值线图 (这是我们的核心数据)
    contour_fill = ax.contourf(lons, lats, scores, levels=levels, cmap=chromasky_cmap, transform=proj, extend='max', zorder=1)

    
    if not all([config.CHINA_SHP_PATH.exists(), config.NINE_DASH_LINE_SHP_PATH.exists()]):
        logger.error(f"地图数据文件未在 '{config.MAP_DATA_DIR}' 目录中找到。")
    ax.add_geometries(shapereader.Reader(str(config.CHINA_SHP_PATH)).geometries(), proj,
                        edgecolor='#a8a29e', facecolor='none', linewidth=0.5, zorder=2)
    ax.add_geometries(shapereader.Reader(str(config.NINE_DASH_LINE_SHP_PATH)).geometries(), proj,
                        edgecolor='#a8a29e', facecolor='none', linewidth=1.0, zorder=2)
    ax.add_feature(cfeature.COASTLINE.with_scale('50m'), edgecolor='#78716c', linewidth=0.5, zorder=2)

    # 4. (可选) 添加城市标注
    if config.CITIES_CSV_PATH.exists():
        df_cities = pd.read_csv(config.CITIES_CSV_PATH)
        ax.plot(df_cities['lon'], df_cities['lat'], 'o', color='white', markersize=2, alpha=0.7, transform=proj, zorder=4)

    # 5. 设置白色的网格线、标题和标签
    gl = ax.gridlines(crs=proj, draw_labels=True, linewidth=0.5, color='#44403c', alpha=0.8, linestyle='--')
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {'color': 'white', 'size': 10}
    gl.ylabel_style = {'color': 'white', 'size': 10}

    ax.set_title(title, fontsize=18, color='white', pad=20)
    cbar = fig.colorbar(contour_fill, ax=ax, orientation='vertical', pad=0.02, shrink=0.8)
    cbar.set_label(f"{data_grid.attrs.get('long_name', data_grid.name)} ({data_grid.attrs.get('units', 'N/A')})", color='white')
    cbar.ax.yaxis.set_tick_params(color='white')
    plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')

    # 6. 保存为带透明背景的图片
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=200, bbox_inches='tight', pad_inches=0.1, transparent=True, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"✅ 暗色主题地图已成功保存到: {output_path}")


# --- 7. 更新 __main__ 部分以进行自测 ---
if __name__ == "__main__":
    logger.info("===== 正在以独立模式运行 map_drawer.py 进行自测 =====")
    
    # 创建一个模拟的数据网格 (DataArray)
    lats = np.arange(config.AREA_EXTRACTION["south"], config.AREA_EXTRACTION["north"], 0.25)
    lons = np.arange(config.AREA_EXTRACTION["west"], config.AREA_EXTRACTION["east"], 0.25)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    center_lon, center_lat = 115, 30
    sigma_lon, sigma_lat = 10, 8
    exponent = -((lon_grid - center_lon)**2 / (2 * sigma_lon**2) + (lat_grid - center_lat)**2 / (2 * sigma_lat**2))
    scores = 1.0 * np.exp(exponent) # 云量范围是 0-1
    sample_grid = xr.DataArray(
        scores, 
        coords={'latitude': lats, 'longitude': lons}, 
        dims=['latitude', 'longitude'],
        name='High Cloud Cover',
        attrs={'units': '(0-1)', 'long_name': 'High Cloud Cover'}
    )

    # 定义输出路径
    output_dir = config.PROJECT_ROOT / "debug_maps"
    output_file_path = output_dir / "map_drawer_self_test.png"

    # 调用绘图函数
    generate_map_from_grid(
        score_grid=sample_grid, 
        title="Map Drawer Self-Test Map", 
        output_path=output_file_path
    )
    
    print(f"\n✅ 模块自测成功！验证地图已保存到: {output_file_path.resolve()}")