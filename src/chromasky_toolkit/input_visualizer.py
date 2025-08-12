# src/chromasky_toolkit/input_visualizer.py

import logging
from pathlib import Path
import xarray as xr

from . import config
from .processing import expand_target_events
from .map_drawer import generate_map_from_grid

logger = logging.getLogger(__name__)

# 定义我们想要可视化的所有输入变量
VARS_TO_VISUALIZE = ['hcc', 'mcc', 'lcc', 'aod550']

def run_input_visualization():
    """
    执行输入数据的可视化流程。
    为 processed 目录中每个时间点的 hcc, mcc, lcc, aod550 数据生成地图。
    """
    logger.info("====== 开始执行输入数据可视化流程 ======")

    target_events = expand_target_events()
    if not target_events:
        logger.warning("根据配置，没有找到任何需要可视化的未来事件。流程终止。")
        return

    for event_name, target_time_utc in target_events.items():
        logger.info(f"--- 正在为事件 '{event_name}' 可视化输入数据 ---")
        
        date_str, event_type, time_str = event_name.split('_')
        event_local_time_str = f"{time_str[:2]}:{time_str[2:]}"
        data_dir = config.PROCESSED_DATA_DIR / "future" / date_str

        if not data_dir.exists():
            logger.warning(f"  - 数据目录不存在，跳过事件: {data_dir}")
            continue

        for var_name in VARS_TO_VISUALIZE:
            file_path = data_dir / f"{var_name}_{time_str}.nc"
            
            if not file_path.exists():
                logger.warning(f"  - 输入文件未找到，跳过: {file_path.relative_to(config.PROJECT_ROOT)}")
                continue

            try:
                # 加载数据
                data_slice = xr.open_dataarray(file_path)
                logger.info(f"  - 正在处理: {file_path.name}")

                # 准备绘图参数
                long_name = data_slice.attrs.get('long_name', var_name.upper())
                units = data_slice.attrs.get('units', 'N/A')

                map_title = (
                    f"{long_name} ({units})\n"
                    f"预报本地时间: {date_str} {event_local_time_str} ({config.LOCAL_TZ})"
                )

                output_dir = config.MAP_OUTPUTS_DIR / "input_data" / date_str
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"{var_name}_{date_str}_{time_str}.png"

                # 调用通用绘图函数
                generate_map_from_grid(
                    score_grid=data_slice,
                    title=map_title,
                    output_path=output_path,
                )
                logger.info(f"    ✅ 地图已保存至: {output_path.relative_to(config.PROJECT_ROOT)}")

            except Exception as e:
                logger.error(f"    ❌ 在为 {file_path.name} 绘图时发生错误: {e}", exc_info=True)

    logger.info("====== 输入数据可视化流程执行完毕！ ======")