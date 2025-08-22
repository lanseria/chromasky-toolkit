# src/chromasky_toolkit/mapping.py

import logging
import xarray as xr
import itertools

from . import config
from .processing import expand_target_events
from .map_drawer import generate_map_from_grid

logger = logging.getLogger(__name__)

def run_drawing():
    """
    执行完整的地图绘制流程。
    从 outputs/calculations 读取指数结果，为每个事件组（如 '日期_事件类型'）
    生成分时地图和一张综合最佳地图。
    """
    logger.info("====== 开始执行地图绘制流程 ======")

    target_events = expand_target_events()
    if not target_events:
        logger.warning("根据配置，没有找到任何需要绘制的未来事件。流程终止。")
        return

    # --- 核心修改：按 (日期_事件类型) 对事件进行分组 ---
    # 例如，将 '2025-08-21_sunset_1900' 和 '2025-08-21_sunset_2000' 分到 '2025-08-21_sunset' 组
    event_grouper = lambda name: "_".join(name.split('_')[:2])
    
    # 确保事件按我们想要分组的键排序
    sorted_events = sorted(target_events.items(), key=lambda item: event_grouper(item[0]))
    
    # 遍历每个事件组
    for group_key, group_events_iterator in itertools.groupby(sorted_events, key=lambda item: event_grouper(item[0])):
        
        group_events = list(group_events_iterator) # 将迭代器转换为列表
        group_date_str, group_event_type = group_key.split('_')

        logger.info(f"\n===== 开始处理事件组: {group_key} (共 {len(group_events)} 个时间点) =====")

        # 为每个组重置数据收集器
        all_glow_index_arrays = []
        all_event_times = []

        # 1. 绘制该组内所有分时地图
        for event_name, target_time_utc in group_events:
            logger.info(f"--- 正在为事件 '{event_name}' 绘制地图 ---")
            
            try:
                # 解析事件详情并构建输入文件路径
                date_str, event_type, time_str = event_name.split('_')
                event_local_time_str = f"{time_str[:2]}:{time_str[2:]}"
                
                calc_dir = config.CALCULATION_OUTPUTS_DIR / date_str
                result_path = calc_dir / f"glow_index_result_{time_str}.nc"
                
                if not result_path.exists():
                    raise FileNotFoundError(f"计算结果文件未找到: {result_path.relative_to(config.LOG_BASE_PATH)}")

                # 加载计算结果
                results_ds = xr.open_dataset(result_path)
                final_score_grid = results_ds['final_score']
                
                if final_score_grid.max() == 0:
                    logger.warning(f"  - 事件 '{event_name}' 的最大指数为0，将生成一张空白地图。")

                # 准备绘图参数
                map_title = (
                    f"火烧云指数预报 ({event_type.capitalize()})\n"
                    f"预报本地时间: {date_str} {event_local_time_str} ({config.LOCAL_TZ})\n"
                    f"UTC 时间: {target_time_utc.strftime('%Y-%m-%d %H:%M')}"
                )
                
                output_dir = config.MAP_OUTPUTS_DIR / "individual" / date_str
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"glow_index_{date_str}_{time_str}.png"
                
                # 调用绘图函数生成分时地图
                generate_map_from_grid(
                    score_grid=final_score_grid,
                    title=map_title,
                    output_path=output_path,
                )
                logger.info(f"  ✅ 分时地图已保存至: {output_path.relative_to(config.LOG_BASE_PATH)}")

                # 收集数据用于生成本组的综合图
                all_glow_index_arrays.append(final_score_grid)
                all_event_times.append(event_local_time_str)

            except FileNotFoundError as e:
                logger.warning(f"  - 缺少数据，无法为事件 '{event_name}' 绘图: {e}")
            except Exception as e:
                logger.error(f"  ❌ 在为事件 '{event_name}' 绘图时发生未知错误: {e}", exc_info=True)

        # 2. 为当前处理的组绘制综合最佳图
        if all_glow_index_arrays:
            logger.info(f"\n--- 正在为组 '{group_key}' 生成综合最佳指数图 ---")
            try:
                # 合并所有时间点的数据，并在时间维度上取最大值
                combined_glow_index = xr.concat(all_glow_index_arrays, dim='time').max(dim='time')

                # 准备标题和输出路径
                time_period_str = f"{min(all_event_times)} - {max(all_event_times)}"
                
                composite_map_title = (
                    f"综合最佳火烧云指数 ({group_event_type.capitalize()})\n"
                    f"预报日期: {group_date_str} | 时间段: {time_period_str} (本地时间)"
                )
                
                output_dir = config.MAP_OUTPUTS_DIR / "composite"
                output_dir.mkdir(parents=True, exist_ok=True)
                # 使用组的 key 来命名文件，确保唯一性
                composite_map_output_path = output_dir / f"glow_index_composite_{group_key}.png"

                # 调用绘图函数
                generate_map_from_grid(
                    score_grid=combined_glow_index,
                    title=composite_map_title,
                    output_path=composite_map_output_path,
                )
                logger.info(f"✅ 综合最佳地图已保存至: {composite_map_output_path.relative_to(config.LOG_BASE_PATH)}")

            except Exception as e:
                logger.error(f"❌ 生成组 '{group_key}' 的综合地图时发生错误: {e}", exc_info=True)
        else:
            logger.warning(f"未能处理组 '{group_key}' 的任何事件，无法生成综合地图。")

    logger.info("\n====== 地图绘制流程执行完毕！ ======")