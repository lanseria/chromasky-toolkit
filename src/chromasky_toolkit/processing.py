# src/chromasky_toolkit/processing.py

import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, List
import xarray as xr

from . import config
from .glow_index import GlowIndexCalculator

logger = logging.getLogger(__name__)

def expand_target_events() -> Dict[str, datetime]:
    """
    根据全局配置，将事件意图（如 'today_sunset'）展开为包含具体UTC时间的字典。
    返回的字典格式: {'YYYY-MM-DD_event_HHMM': datetime_object_utc}
    """
    simple_events = config.FUTURE_TARGET_EVENT_INTENTIONS
    local_tz = ZoneInfo(config.LOCAL_TZ)
    now_local = datetime.now(local_tz)
    today = now_local.date()
    tomorrow = today + timedelta(days=1)
    
    future_events: Dict[str, datetime] = {}
    
    event_map = {
        'today_sunrise': (today, config.SUNRISE_EVENT_TIMES),
        'today_sunset': (today, config.SUNSET_EVENT_TIMES),
        'tomorrow_sunrise': (tomorrow, config.SUNRISE_EVENT_TIMES),
        'tomorrow_sunset': (tomorrow, config.SUNSET_EVENT_TIMES),
    }
    
    for event_intention in simple_events:
        if event_intention in event_map:
            event_date, event_times = event_map[event_intention]
            event_type = event_intention.split('_')[1]
            for t_str in event_times:
                event_time = datetime.strptime(t_str, '%H:%M').time()
                dt_local = datetime.combine(event_date, event_time, tzinfo=local_tz)
                name = f"{event_date.strftime('%Y-%m-%d')}_{event_type}_{t_str.replace(':', '')}"
                future_events[name] = dt_local.astimezone(timezone.utc)
                
    return dict(sorted(future_events.items()))


def run_calculation():
    """
    执行完整的火烧云指数计算流程。
    从 processed 目录读取数据，计算指数，并将结果保存到 outputs 目录。
    """
    logger.info("====== 开始执行火烧云指数计算流程 ======")
    
    target_events = expand_target_events()
    if not target_events:
        logger.warning("根据配置，没有找到任何需要计算的未来事件。流程终止。")
        return

    for event_name, target_time_utc in target_events.items():
        logger.info(f"--- 正在为事件 '{event_name}' 计算指数 ---")

        try:
            # 1. 解析事件详情并构建输入文件路径
            date_str, event_type, time_str = event_name.split('_')
            data_dir = config.PROCESSED_DATA_DIR / "future" / date_str
            
            # 2. 加载所有必需的输入数据
            required_vars = ['hcc', 'mcc', 'lcc', 'aod550']
            data_arrays = {}
            for var in required_vars:
                file_path = data_dir / f"{var}_{time_str}.nc"
                if not file_path.exists():
                    raise FileNotFoundError(f"输入文件未找到: {file_path.relative_to(config.PROJECT_ROOT)}")
                data_arrays[var] = xr.open_dataarray(file_path)
            
            weather_dataset = xr.Dataset(data_arrays)
            logger.info("  ✅ 所有必需的云量数据加载成功。")

            # 3. 初始化计算器
            calculator = GlowIndexCalculator(weather_data=weather_dataset)
            
            # 4. 创建活动区域掩码 (只计算日出/日落区域)
            # 使用文件中记录的精确UTC时间
            observation_time_utc = datetime.fromisoformat(weather_dataset.hcc.attrs['original_utc_time'])
            active_mask = calculator.astro_service.create_event_mask(
                weather_dataset.latitude,
                weather_dataset.longitude,
                observation_time_utc,
                event=event_type, # 'sunrise' or 'sunset'
                window_minutes=config.EVENT_WINDOW_MINUTES
            )
            
            active_points_count = int(active_mask.sum())
            if active_points_count == 0:
                logger.warning(f"  - 在 {event_type} 时间窗口内没有找到任何活动区域，跳过计算。")
                continue
            logger.info(f"  - 将为 {active_points_count} 个活动格点计算指数...")

            # 5. 执行网格计算
            results_ds = calculator.calculate_for_grid(
                utc_time=observation_time_utc,
                active_mask=active_mask,
                factors=GlowIndexCalculator.ALL_FACTORS
            )

            # 6. 保存计算结果
            output_dir = config.CALCULATION_OUTPUTS_DIR / date_str
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"glow_index_result_{time_str}.nc"
            
            results_ds.attrs['description'] = f"Glow index calculation result for {event_name}"
            results_ds.attrs['calculation_utc_time'] = datetime.now(timezone.utc).isoformat()
            results_ds.to_netcdf(output_path)
            logger.info(f"  ✅ 指数计算结果已保存至: {output_path.relative_to(config.PROJECT_ROOT)}")

        except FileNotFoundError as e:
            logger.warning(f"  - 缺少数据，无法计算此事件: {e}")
        except Exception as e:
            logger.error(f"  ❌ 在为事件 '{event_name}' 计算时发生未知错误: {e}", exc_info=True)

    logger.info("====== 指数计算流程执行完毕！ ======")