# src/chromasky_toolkit/map_drawer.py
import argparse
import logging
from pathlib import Path
import io

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.font_manager as fm
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
    # 步骤 1: 优先加载项目内的自定义字体
    custom_font_path = config.FONT_DIR / config.MAP_FONT_FILENAME
    if custom_font_path.exists():
        logger.info(f"✅ 找到项目自定义字体: {custom_font_path}")
        # 将字体文件添加到 matplotlib 的字体管理器中
        fm.fontManager.addfont(str(custom_font_path))
        # 设置 matplotlib 使用该字体
        plt.rcParams['font.sans-serif'] = [config.MAP_FONT_NAME]
        logger.info(f"已将默认字体设置为 '{config.MAP_FONT_NAME}'。")
        CHINESE_FONT_FOUND = True
    else:
        logger.warning(f"未在 {config.FONT_DIR} 找到自定义字体 '{config.MAP_FONT_FILENAME}'。将尝试扫描系统字体。")

    # 步骤 2: 如果自定义字体未找到，则扫描系统字体作为备用方案
    if not CHINESE_FONT_FOUND:
        CHINESE_FONT_KEYWORDS = [
            'SimSun', 'SimHei', 'Microsoft YaHei', 'DengXian', 'FangSong', 'KaiTi',
            'PingFang SC', 'Hiragino Sans GB',
            'Noto Sans CJK SC', 'WenQuanYi Micro Hei',
            'Heiti', 'Songti', 'Kaiti'
        ]
        font_manager = fm.FontManager()
        for font in font_manager.ttflist:
            if any(keyword in font.name for keyword in CHINESE_FONT_KEYWORDS):
                logger.info(f"✅ 找到可用的系统备用中文字体: '{font.name}'。将其设置为默认字体。")
                plt.rcParams['font.sans-serif'] = [font.name]
                CHINESE_FONT_FOUND = True
                break
    
    # 步骤 3: 最终检查和配置
    if CHINESE_FONT_FOUND:
        logger.info(f"最终使用的字体列表: {plt.rcParams['font.sans-serif']}")
    else:
        logger.warning("系统中仍未找到任何可用的中文字体。中文将无法正常显示。")
        
    # 无论如何，都设置此项以正确显示负号
    plt.rcParams['axes.unicode_minus'] = False

except Exception as e:
    logger.warning(f"设置字体时发生未知错误: {e}")


# --- 4. 核心绘图函数 ---
def generate_map_from_grid(
    score_grid: xr.DataArray, 
    title: str, 
    output_path: Path | None = None,
    active_region_mask: xr.DataArray | None = None # 新增的可选参数
) -> bytes | None:
    """
    根据给定的数据网格生成一张精美的暗色主题地图。
    *** 新版本: 可以额外绘制一个活动区域掩码的轮廓。***

    Args:
        score_grid (xr.DataArray): 包含地理坐标和数值的数据网格。
        title (str): 地图的标题。
        output_path (Path | None, optional): 保存地图的文件路径。如果为 None，则不保存文件。
        active_region_mask (xr.DataArray | None, optional): 
            一个布尔类型的掩码，用于在图上高亮显示计算区域。

    Returns:
        bytes | None: 成功则返回 PNG 图像的二进制数据，失败则返回 None。
    """
    logger.info(f"--- [绘图] 开始生成地图: {title} ---")
    fig = None  # 初始化 fig 变量
    try:
        # 数据预处理
        scores_for_smoothing = score_grid.fillna(0).values
        smoothed_scores = gaussian_filter(scores_for_smoothing, sigma=1.5)
        smoothed_grid = xr.DataArray(smoothed_scores, coords=score_grid.coords, dims=score_grid.dims)
        interp_factor = 4
        orig_lats, orig_lons = smoothed_grid.latitude.values, smoothed_grid.longitude.values
        new_lats = np.linspace(orig_lats.min(), orig_lats.max(), len(orig_lats) * interp_factor)
        new_lons = np.linspace(orig_lons.min(), orig_lons.max(), len(orig_lons) * interp_factor)
        high_res_grid = smoothed_grid.interp(latitude=new_lats, longitude=new_lons, method='cubic')
        lats, lons, scores = high_res_grid.latitude.values, high_res_grid.longitude.values, high_res_grid.values

        if np.all(np.isnan(scores)) or np.nanmax(scores) == 0:
            logger.warning("输入数据为空或全为零，将绘制一张空白底图。")
            scores[:] = np.nan
        else:
            scores[scores < np.nanmax(scores) * 0.05] = np.nan

        # 绘图设置
        proj = ccrs.PlateCarree()
        fig = plt.figure(figsize=(12, 10), facecolor='black')
        ax = fig.add_subplot(1, 1, 1, projection=proj)
        ax.set_facecolor('black')
        area_bounds = [config.DISPLAY_AREA[k] for k in ["west", "east", "south", "north"]]
        ax.set_extent(area_bounds, crs=ccrs.PlateCarree())
        ax.add_feature(cfeature.OCEAN.with_scale('50m'), facecolor='#0c0a09', zorder=0)
        ax.add_feature(cfeature.LAND.with_scale('50m'), facecolor='#1c1917', edgecolor='none', zorder=0)


        # --- 核心改动：绘制活动区域掩码 ---
        if active_region_mask is not None:
            logger.info("正在绘制活动区域掩码轮廓...")
            # 将布尔掩码转换为浮点数（True->1.0, False->0.0）以便绘制等高线
            mask_values = active_region_mask.astype(float)
            
            # 我们只关心值为 0.5 的等高线，这正好是 True 和 False 的边界
            ax.contour(
                active_region_mask.longitude, 
                active_region_mask.latitude,
                mask_values,
                levels=[0.5], # 只画出 0.5 的等高线，即区域的边界
                colors='cyan',  # 使用醒目的青色
                linewidths=1.5,
                linestyles='--', # 使用虚线
                transform=proj,
                zorder=3  # zorder 确保它在数据之上，在城市标注之下
            )
        
        # 绘制核心数据
        if not np.all(np.isnan(scores)):
            chromasky_cmap = mcolors.LinearSegmentedColormap.from_list("chromasky", list(zip(config.CHROMA_SKY_COLOR_NODES, config.CHROMA_SKY_COLORS)))
            levels = np.linspace(np.nanmin(scores), np.nanmax(scores), 100)
            contour_fill = ax.contourf(lons, lats, scores, levels=levels, cmap=chromasky_cmap, transform=proj, extend='max', zorder=1)
            cbar = fig.colorbar(contour_fill, ax=ax, orientation='vertical', pad=0.02, shrink=0.8)
            cbar.set_label(f"{score_grid.attrs.get('long_name', score_grid.name)} ({score_grid.attrs.get('units', 'N/A')})", color='white')
            cbar.ax.yaxis.set_tick_params(color='white')
            plt.setp(plt.getp(cbar.ax.axes, 'yticklabels'), color='white')

        # 添加地理边界
        if not all([config.CHINA_SHP_PATH.exists(), config.NINE_DASH_LINE_SHP_PATH.exists()]):
            logger.error(f"地图数据文件未在 '{config.MAP_DATA_DIR}' 目录中找到。请运行 `python tools/setup_map_data.py`")
        else:
            ax.add_geometries(shapereader.Reader(str(config.CHINA_SHP_PATH)).geometries(), proj, facecolor='none', edgecolor='#a8a29e', linewidth=0.5, zorder=2)
            ax.add_geometries(shapereader.Reader(str(config.NINE_DASH_LINE_SHP_PATH)).geometries(), proj, facecolor='none', edgecolor='#a8a29e', linewidth=1.0, zorder=2)
        ax.add_feature(cfeature.COASTLINE.with_scale('50m'), edgecolor='#78716c', linewidth=0.5, zorder=2)

        # 添加城市标注
        if config.CITIES_CSV_PATH.exists():
            df_cities = pd.read_csv(config.CITIES_CSV_PATH)
            ax.plot(df_cities['lon'], df_cities['lat'], 'o', color='white', markersize=2, alpha=0.7, transform=proj, zorder=4)
            for _, city in df_cities.iterrows():
                display_name = city['name'] if CHINESE_FONT_FOUND else city['name_en']
                ax.text(city['lon'] + 0.1, city['lat'] + 0.1, display_name, color='white', fontsize=8, alpha=0.8, transform=proj, zorder=4)
        else:
            logger.warning(f"未找到城市数据文件: {config.CITIES_CSV_PATH}，跳过城市绘制。")

        # 添加网格线和标题
        gl = ax.gridlines(crs=proj, draw_labels=True, linewidth=0.5, color='#44403c', alpha=0.8, linestyle='--')
        gl.top_labels, gl.right_labels = False, False
        gl.xlabel_style, gl.ylabel_style = {'color': 'white', 'size': 10}, {'color': 'white', 'size': 10}
        ax.set_title(title, fontsize=18, color='white', pad=20)
        
        # 将图像保存到内存中
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight', pad_inches=0.1, transparent=True, facecolor=fig.get_facecolor())
        img_buffer.seek(0)
        image_data = img_buffer.read()
        
        # 可选：保存到磁盘
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(image_data)
            logger.info(f"--- [绘图] 地图已成功保存到: {output_path} ---")

        return image_data

    except Exception as e:
        logger.error(f"❌ 绘图或保存时发生错误: {e}", exc_info=True)
        return None
    finally:
        # 确保无论如何都关闭图形，释放内存
        if fig:
            plt.close(fig)


# --- 5. 用于自测的 __main__ 部分 ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="地图绘制模块自测工具")
    parser.add_argument("-o", "--output", type=str, default="map_drawer_self_test.png", help="输出图片的文件名。")
    args = parser.parse_args()

    logger.info("===== 正在以独立模式运行 map_drawer.py 进行自测 =====")
    
    # 创建模拟数据
    lats = np.arange(config.DISPLAY_AREA["south"], config.DISPLAY_AREA["north"], 0.25)
    lons = np.arange(config.DISPLAY_AREA["west"], config.DISPLAY_AREA["east"], 0.25)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    center_lon, center_lat = 115, 30
    sigma_lon, sigma_lat = 10, 8
    exponent = -((lon_grid - center_lon)**2 / (2 * sigma_lon**2) + (lat_grid - center_lat)**2 / (2 * sigma_lat**2))
    scores = 0.8 * np.exp(exponent) # 模拟云量 (0-1)
    sample_grid = xr.DataArray(scores, coords={'latitude': lats, 'longitude': lons}, dims=['latitude', 'longitude'],
                                name='hcc', attrs={'units': '(0-1)', 'long_name': 'High Cloud Cover'})

    output_dir = config.PROJECT_ROOT / "debug_maps"
    output_file_path = output_dir / args.output

    # 调用绘图函数
    img_bytes = generate_map_from_grid(score_grid=sample_grid, title="Map Drawer Self-Test Map", output_path=output_file_path)
    
    if img_bytes:
        print(f"\n✅ 模块自测成功！验证地图已保存到: {output_file_path.resolve()}")
        print(f"   并成功返回了 {len(img_bytes) / 1024:.1f} KB 的图像数据。")
    else:
        print("\n❌ 模块自测失败。")