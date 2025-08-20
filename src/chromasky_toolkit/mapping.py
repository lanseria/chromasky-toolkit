# src/chromasky_toolkit/mapping.py

import logging
from pathlib import Path
from datetime import datetime, timezone
import xarray as xr

from . import config
from .processing import expand_target_events
from .map_drawer import generate_map_from_grid

logger = logging.getLogger(__name__)

def run_drawing():
    """
    执行完整的地图绘制流程。
    从 outputs/calculations 读取指数结果，生成分时地图和综合地图。
    """
    logger.info("====== 开始执行地图绘制流程 ======")

    target_events = expand_target_events()
    if not target_events:
        logger.warning("根据配置，没有找到任何需要绘制的未来事件。流程终止。")
        return

    # 用于生成综合图的数据收集器
    all_glow_index_arrays = []
    all_event_times = []

    for event_name, target_time_utc in target_events.items():
        logger.info(f"--- 正在为事件 '{event_name}' 绘制地图 ---")
        
        try:
            # 1. 解析事件详情并构建输入文件路径
            date_str, event_type, time_str = event_name.split('_')
            event_local_time_str = f"{time_str[:2]}:{time_str[2:]}"
            
            calc_dir = config.CALCULATION_OUTPUTS_DIR / date_str
            result_path = calc_dir / f"glow_index_result_{time_str}.nc"
            
            if not result_path.exists():
                raise FileNotFoundError(f"计算结果文件未找到: {result_path.relative_to(config.PROJECT_ROOT)}")

            # 2. 加载计算结果
            results_ds = xr.open_dataset(result_path)
            final_score_grid = results_ds['final_score']
            logger.info(f"  ✅ 成功加载指数结果文件: {result_path.name}")
            
            # 检查数据是否有效
            if final_score_grid.max() == 0:
                logger.warning(f"  - 事件 '{event_name}' 的最大指数为0，将生成一张空白地图。")

            # 3. 准备绘图参数
            map_title = (
                f"火烧云指数预报 ({event_type.capitalize()})\n"
                f"预报本地时间: {date_str} {event_local_time_str} ({config.LOCAL_TZ})\n"
                f"UTC 时间: {target_time_utc.strftime('%Y-%m-%d %H:%M')}"
            )
            
            output_dir = config.MAP_OUTPUTS_DIR / "individual" / date_str
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"glow_index_{date_str}_{time_str}.png"
            
            # 4. 调用绘图函数生成分时地图
            generate_map_from_grid(
                score_grid=final_score_grid,
                title=map_title,
                output_path=output_path,
                active_region_mask=None # 暂时不绘制活动掩码，以突出指数本身
            )
            logger.info(f"  ✅ 分时地图已保存至: {output_path.relative_to(config.PROJECT_ROOT)}")

            # 5. 收集数据用于生成综合图
            all_glow_index_arrays.append(final_score_grid)
            all_event_times.append(event_local_time_str)

        except FileNotFoundError as e:
            logger.warning(f"  - 缺少数据，无法为事件 '{event_name}' 绘图: {e}")
        except Exception as e:
            logger.error(f"  ❌ 在为事件 '{event_name}' 绘图时发生未知错误: {e}", exc_info=True)

    # --- 绘制综合最佳图 ---
    if all_glow_index_arrays:
        logger.info("\n" + "-"*20 + " 正在生成综合最佳指数图 " + "-"*20)
        try:
            # 1. 合并所有时间点的数据，并在时间维度上取最大值
            # 这会为每个地理格点选出其在所有时间点中的最高分
            combined_glow_index = xr.concat(all_glow_index_arrays, dim='time').max(dim='time')

            # 2. 准备标题和输出路径
            date_str = list(target_events.keys())[0].split('_')[0]
            event_type = list(target_events.keys())[0].split('_')[1]
            time_period_str = f"{min(all_event_times)} - {max(all_event_times)}"
            
            composite_map_title = (
                f"综合最佳火烧云指数 ({event_type.capitalize()})\n"
                f"预报日期: {date_str} | 时间段: {time_period_str} (本地时间)"
            )
            
            output_dir = config.MAP_OUTPUTS_DIR / "composite"
            output_dir.mkdir(parents=True, exist_ok=True)
            composite_map_output_path = output_dir / f"glow_index_composite_{date_str}_{event_type}.png"

            # 3. 调用绘图函数
            generate_map_from_grid(
                score_grid=combined_glow_index,
                title=composite_map_title,
                output_path=composite_map_output_path,
            )
            logger.info(f"✅ 综合最佳地图已保存至: {composite_map_output_path.relative_to(config.PROJECT_ROOT)}")

        except Exception as e:
            logger.error(f"❌ 生成综合地图时发生错误: {e}", exc_info=True)
    else:
        logger.warning("未能处理任何事件，无法生成综合地图。")

    logger.info("====== 地图绘制流程执行完毕！ ======")