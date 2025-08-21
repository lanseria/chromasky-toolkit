# src/chromasky_toolkit/data_acquisition.py

import logging
import requests
import json
import cdsapi
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Tuple, Dict, List, Optional # <--- MODIFIED
import xarray as xr
from .processing import expand_target_events

from . import config

logger = logging.getLogger(__name__)

# --- NEW: 定义一个模块级的变量来存储 GFS 网格模板 ---
_gfs_grid_template: Optional[xr.Dataset] = None

# ======================================================================
# --- GFS 数据获取与处理 ---
# ======================================================================

def _find_latest_available_gfs_run() -> Tuple[str, str] | None:
    """智能判断当前可用的最新 GFS 运行周期。"""
    logger.info("--- [GFS] 正在寻找最新的可用运行周期...")
    now_utc = datetime.now(timezone.utc)
    safe_margin = timedelta(hours=5)

    for i in range(10):
        potential_run_time = now_utc - timedelta(hours=i * 6)
        run_hour = (potential_run_time.hour // 6) * 6
        run_time_utc = potential_run_time.replace(hour=run_hour, minute=0, second=0, microsecond=0)
        
        if (now_utc - run_time_utc) >= safe_margin:
            run_date_str = run_time_utc.strftime('%Y%m%d')
            run_hour_str = f"{run_time_utc.hour:02d}"
            logger.info(f"✅ [GFS] 找到最新的可用运行周期: {run_date_str} {run_hour_str}z")
            return run_date_str, run_hour_str
            
    logger.error("❌ [GFS] 在过去24小时内未能找到任何可用的运行周期。")
    return None

def _process_gfs_grib_to_nc(grib_path: Path, target_time_utc: datetime):
    """将下载的GRIB2文件处理成多个标准的NetCDF文件，并保存网格模板。"""
    # <--- NEW: 引用全局模板变量 ---
    global _gfs_grid_template

    local_tz = ZoneInfo(config.LOCAL_TZ)
    try:
        ds = xr.open_dataset(
            grib_path,
            engine="cfgrib",
            filter_by_keys={'stepType': 'instant'},
            decode_timedelta=True  # <-- 添加此参数以消除警告并确保未来兼容性
        )
        
        # <--- NEW: 如果模板尚未创建，则创建它 ---
        if _gfs_grid_template is None:
            _gfs_grid_template = ds.copy() # 复制一份以备后用
            # 为了减小内存占用，可以只保留坐标
            # _gfs_grid_template = ds[[]].copy() # 这样只复制坐标和维度
            logger.info("✅ [Template] 已成功从 GFS 数据创建网格模板。")
            logger.debug(f"  - 模板网格尺寸: {_gfs_grid_template.dims}")
        
        local_dt = target_time_utc.astimezone(local_tz)
        local_date_str = local_dt.strftime('%Y-%m-%d')
        local_time_str_path = local_dt.strftime('%H%M')
        
        output_dir = config.PROCESSED_DATA_DIR / "future" / local_date_str
        output_dir.mkdir(parents=True, exist_ok=True)

        for short_name in config.GFS_VARS_LIST:
            if short_name in ds:
                data_slice = ds[short_name]
                if data_slice.max() > 1.0:
                    logger.debug(f"  - 归一化变量 '{short_name}' (原最大值: {data_slice.max().item():.2f})")
                    data_slice = data_slice / 100.0
                
                data_slice.attrs['units'] = '(0-1)'
                data_slice.attrs['standard_name'] = short_name
                data_slice.attrs['original_utc_time'] = target_time_utc.isoformat()
                
                output_path = output_dir / f"{short_name}_{local_time_str_path}.nc"
                data_slice.to_netcdf(output_path)
                logger.info(f"  ✅ [GFS] 已处理并保存: {output_path.relative_to(config.PROJECT_ROOT)}")
            else:
                logger.warning(f"  - 在GRIB文件中未找到变量: {short_name}")
    except Exception as e:
        logger.error(f"❌ [GFS] 处理 GRIB 文件 {grib_path.name} 时出错: {e}", exc_info=True)


def acquire_gfs_data(target_events: Dict[str, datetime]):
    """为指定的目标事件列表下载和处理GFS数据。"""
    run_info = _find_latest_available_gfs_run()
    if not run_info:
        return
    run_date, run_hour = run_info
    run_time_utc = datetime.strptime(f"{run_date}{run_hour}", "%Y%m%d%H").replace(tzinfo=timezone.utc)
    
    for event_name, target_time_utc in target_events.items():
        logger.info(f"--- [GFS] 开始处理事件: {event_name} ---")
        
        time_diff_hours = (target_time_utc - run_time_utc).total_seconds() / 3600
        if time_diff_hours < 0:
            logger.warning(f"  - 事件 '{event_name}' 的时间早于最新运行周期，跳过。")
            continue
        forecast_hour = round(time_diff_hours)
        
        raw_grib_dir = config.GFS_DATA_DIR / f"{run_date}_t{run_hour}z"
        raw_grib_dir.mkdir(parents=True, exist_ok=True)
        grib_path = raw_grib_dir / f"gfs_f{forecast_hour:03d}.grib2"
        
        if grib_path.exists() and grib_path.stat().st_size > 1024:
            logger.info(f"  - GRIB 数据已存在: {grib_path.name}，跳过下载。")
        else:
            logger.info(f"  - 正在为事件 '{event_name}' 下载 GRIB (预报时效: f{forecast_hour:03d})")
            params = {
                "file": f"gfs.t{run_hour}z.pgrb2.0p25.f{forecast_hour:03d}",
                "dir": f"/gfs.{run_date}/{run_hour}/atmos",
                "subregion": "", "leftlon": config.DOWNLOAD_AREA['west'], "rightlon": config.DOWNLOAD_AREA['east'],
                "toplat": config.DOWNLOAD_AREA['north'], "bottomlat": config.DOWNLOAD_AREA['south'],
                'var_HCDC': 'on', 'lev_high_cloud_layer': 'on',
                'var_MCDC': 'on', 'lev_middle_cloud_layer': 'on',
                'var_LCDC': 'on', 'lev_low_cloud_layer': 'on',
            }
            try:
                response = requests.get(config.GFS_BASE_URL, params=params, stream=True, timeout=300)
                response.raise_for_status()
                with open(grib_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
                logger.info(f"  ✅ [GFS] GRIB 数据已保存到: {grib_path.name}")
            except requests.RequestException as e:
                logger.error(f"  ❌ [GFS] GRIB 下载失败: {e}")
                continue
        
        # 无论是否下载，都进行处理
        _process_gfs_grib_to_nc(grib_path, target_time_utc)

# ======================================================================
# --- CAMS AOD 数据获取与处理 ---
# ======================================================================

def _find_latest_available_cams_run() -> Tuple[str, str] | None:
    """智能判断当前可用的最新 CAMS 运行周期 (00z 或 12z)。"""
    logger.info("--- [CAMS] 正在寻找最新的可用运行周期...")
    now_utc = datetime.now(timezone.utc)
    safe_margin = timedelta(hours=9)
    
    for i in range(4):
        potential_run_time = now_utc - timedelta(hours=i * 12)
        run_hour = 12 if 12 <= potential_run_time.hour < 24 else 0
        run_time_utc = potential_run_time.replace(hour=run_hour, minute=0, second=0, microsecond=0)

        if (now_utc - run_time_utc) >= safe_margin:
            run_date_str = run_time_utc.strftime('%Y-%m-%d')
            run_hour_str = f"{run_time_utc.hour:02d}:00"
            logger.info(f"✅ [CAMS] 找到最新的可用运行周期: {run_date_str} {run_hour_str} UTC")
            return run_date_str, run_hour_str
            
    logger.error("❌ [CAMS] 在过去48小时内未能找到任何满足安全边际的运行周期。")
    return None

# <--- MODIFIED: 整个函数都被重写以使用模板 ---
def _process_cams_nc_to_nc(raw_nc_path: Path, target_events: Dict[str, datetime], base_run_time: datetime):
    """
    将下载的包含多个时效的CAMS文件，分解、重采样到GFS网格，并保存为标准的单时效NetCDF文件。
    """
    global _gfs_grid_template # 引用全局模板

    # 检查模板是否存在，这是处理 CAMS 的前提
    if _gfs_grid_template is None:
        logger.error("❌ [CAMS] 未找到 GFS 网格模板，无法对 CAMS 数据进行重采样。请先成功运行 GFS 数据处理流程。")
        return

    local_tz = ZoneInfo(config.LOCAL_TZ)
    try:
        with xr.open_dataset(raw_nc_path, engine="netcdf4") as ds_cams_raw:
            logger.info(f"--- [CAMS] 开始处理原始 CAMS 文件: {raw_nc_path.name} ---")
            logger.debug(f"  - 原始CAMS网格尺寸: {ds_cams_raw.dims}")

            for event_name, target_time_utc in target_events.items():
                leadtime_hour = round((target_time_utc - base_run_time).total_seconds() / 3600)
                if leadtime_hour < 0:
                    continue
                
                target_forecast_period = timedelta(hours=leadtime_hour)
                # 1. 从原始CAMS数据中选择正确的时间片
                time_slice = ds_cams_raw.sel(forecast_period=target_forecast_period, method='nearest').squeeze()
                
                local_dt = target_time_utc.astimezone(local_tz)
                local_date_str = local_dt.strftime('%Y-%m-%d')
                local_time_str_path = local_dt.strftime('%H%M')
                output_dir = config.PROCESSED_DATA_DIR / "future" / local_date_str
                output_dir.mkdir(parents=True, exist_ok=True)
                
                # 2. 遍历需要处理的 CAMS 变量
                for short_name, cams_var_name in config.CAMS_VARS_MAP.items():
                    if short_name in time_slice:
                        original_slice = time_slice[short_name]

                        # 3. 【核心步骤】重采样到 GFS 网格
                        logger.info(f"  - 正在为事件 '{event_name}' 重采样变量 '{short_name}'...")
                        resampled_slice = original_slice.interp_like(
                            _gfs_grid_template, 
                            method='linear', 
                            kwargs={"fill_value": 0.0}
                        ).fillna(0.0)

                        # 4. 为重采样后的数据添加元数据
                        resampled_slice.attrs['standard_name'] = short_name
                        resampled_slice.attrs['original_utc_time'] = target_time_utc.isoformat()
                        resampled_slice.attrs['regridding_source'] = 'GFS grid'
                        
                        # 5. 保存重采样后的文件
                        output_path = output_dir / f"{short_name}_{local_time_str_path}.nc"
                        resampled_slice.to_netcdf(output_path)
                        logger.info(f"  ✅ [CAMS] 已处理并保存对齐后的文件: {output_path.relative_to(config.PROJECT_ROOT)}")

    except Exception as e:
        logger.error(f"❌ [CAMS] 处理原始 NetCDF 文件 {raw_nc_path.name} 时出错: {e}", exc_info=True)


def acquire_cams_data(target_events: Dict[str, datetime]):
    """为指定的目标事件列表下载和处理CAMS AOD数据。"""
    run_info = _find_latest_available_cams_run()
    if not run_info:
        return
    run_date_str, run_hour_str = run_info
    base_run_time = datetime.strptime(f"{run_date_str} {run_hour_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    
    leadtime_hours = {
        round((t - base_run_time).total_seconds() / 3600)
        for t in target_events.values()
    }
    valid_leadtime_hours = sorted([str(h) for h in leadtime_hours if h >= 0])
    
    if not valid_leadtime_hours:
        logger.warning("[CAMS] 没有需要下载的未来预报时效。")
        return
        
    raw_nc_dir = config.CAMS_AOD_DATA_DIR / f"{base_run_time.strftime('%Y%m%d')}_t{base_run_time.strftime('%H')}z"
    raw_nc_dir.mkdir(parents=True, exist_ok=True)
    raw_nc_path = raw_nc_dir / "aod_forecast_raw.nc"
    temp_dl_path = raw_nc_path.with_suffix('.tmp')

    if raw_nc_path.exists() and raw_nc_path.stat().st_size > 1024:
        logger.info(f"  - CAMS 原始数据已存在: {raw_nc_path.name}，跳过下载。")
    else:
        logger.info(f"--- [CAMS] 开始为运行周期 {run_date_str} {run_hour_str} 下载新数据 ---")
        logger.info(f"  - 将下载 {len(valid_leadtime_hours)} 个预报时效: {valid_leadtime_hours}")
        try:
            c = cdsapi.Client(url=config.CDS_API_URL, key=config.CDS_API_KEY, timeout=600, quiet=False)
            area_bounds = [config.DOWNLOAD_AREA[k] for k in ["north", "west", "south", "east"]]
            
            c.retrieve(
                config.CAMS_DATASET_NAME,
                {
                    'date': run_date_str, 'time': run_hour_str, 'format': 'netcdf',
                    'variable': list(config.CAMS_VARS_MAP.values()),
                    'leadtime_hour': valid_leadtime_hours, 'type': 'forecast', 'area': area_bounds
                },
                str(temp_dl_path)
            )
            
            if zipfile.is_zipfile(temp_dl_path):
                logger.info("  - 检测到ZIP包，正在解压...")
                with zipfile.ZipFile(temp_dl_path, 'r') as zip_ref:
                    nc_file_in_zip = zip_ref.namelist()[0]
                    zip_ref.extract(nc_file_in_zip, raw_nc_dir)
                    (raw_nc_dir / nc_file_in_zip).rename(raw_nc_path)
            else:
                temp_dl_path.rename(raw_nc_path)
            logger.info(f"  ✅ [CAMS] 原始数据已保存至: {raw_nc_path.name}")

        except Exception as e:
            logger.error(f"❌ [CAMS] 下载原始数据时出错: {e}", exc_info=True)
            return
        finally:
            if temp_dl_path.exists(): temp_dl_path.unlink()

    # 此处调用处理函数，它将内部使用全局模板
    _process_cams_nc_to_nc(raw_nc_path, target_events, base_run_time)

# ======================================================================
# --- 主执行函数 ---
# ======================================================================

def run_acquisition():
    """执行完整的数据获取和处理流程。"""
    logger.info("====== 开始执行数据获取与分析流程 ======")
    
    # 1. 确定需要处理的所有事件
    target_events = expand_target_events()
    if not target_events:
        logger.warning("根据配置，没有找到任何需要处理的未来事件。流程终止。")
        return
        
    logger.info(f"将要处理的事件共 {len(target_events)} 个:")
    for name, dt in target_events.items():
        logger.info(f"  - {name} (UTC: {dt.strftime('%Y-%m-%d %H:%M')})")
    
    # 2. 获取 GFS 数据（此过程将创建 _gfs_grid_template）
    logger.info("="*25 + " GFS 数据处理 " + "="*25)
    acquire_gfs_data(target_events)
    
    # 3. 获取 CAMS AOD 数据（此过程将使用 _gfs_grid_template）
    logger.info("="*25 + " CAMS AOD 数据处理 " + "="*25)
    acquire_cams_data(target_events)
    
    logger.info("====== 数据获取与分析流程执行完毕！ ======")