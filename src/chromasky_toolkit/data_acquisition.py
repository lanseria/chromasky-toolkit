# src/chromasky_toolkit/data_acquisition.py

import logging
import zipfile
import xarray as xr
from pathlib import Path
from datetime import datetime, date

# 从同级目录的 config.py 中导入配置
from . import config

# 懒加载 cdsapi，仅在需要时导入
cdsapi = None

# 获取一个模块级别的 logger
logger = logging.getLogger(__name__)

def _lazy_import_cdsapi():
    """懒加载 cdsapi，避免在不使用时成为硬性依赖。"""
    global cdsapi
    if cdsapi is None:
        try:
            import cdsapi as cds_lib
            cdsapi = cds_lib
        except ImportError:
            logger.error("cdsapi 库未安装。请运行 'uv pip install cdsapi'。")
            raise
    return cdsapi

# --- 内部辅助函数 (从 Notebook 迁移而来) ---

def _get_required_utc_dates_and_hours(target_local_date: date) -> dict:
    """根据本地日期和时间，计算出所需的 UTC 日期和小时。"""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        logger.error("zoneinfo 库需要 Python 3.9+。")
        raise
        
    local_tz = ZoneInfo(config.LOCAL_TZ)
    all_event_times = config.SUNRISE_EVENT_TIMES + config.SUNSET_EVENT_TIMES
    utc_date_hours = {}

    for time_str in all_event_times:
        local_dt = datetime.combine(target_local_date, datetime.strptime(time_str, '%H:%M').time(), tzinfo=local_tz)
        utc_dt = local_dt.astimezone(datetime.now(datetime.UTC).tzinfo.utcoffset(datetime.now(datetime.UTC)))
        
        utc_date_str = utc_dt.strftime('%Y-%m-%d')
        if utc_date_str not in utc_date_hours:
            utc_date_hours[utc_date_str] = set()
        utc_date_hours[utc_date_str].add(utc_dt.hour)
    return utc_date_hours

def _generate_analysis_report(ds: xr.Dataset) -> str:
    """根据 xarray.Dataset 对象，生成一份详细的 Markdown 格式的分析报告。"""
    # ... (这个函数从 Notebook 完整复制过来)
    report_lines = []
    source_file = Path(ds.encoding.get("source", "N/A")).name
    report_lines.append(f"# NetCDF 文件分析报告: `{source_file}`")
    # ... 其余部分和 Notebook 中的完全一样 ...
    return "\n".join(report_lines)

def _download_era5_past(target_local_date: date) -> Path | None:
    """
    下载 ERA5 历史数据（过去数据）的核心实现。
    """
    _lazy_import_cdsapi() # 确保 cdsapi 已导入

    if not (config.CDS_API_URL and config.CDS_API_KEY):
        logger.error("❌ CDS API 配置未在 .env 文件中找到，无法继续。")
        return None

    output_dir = config.ERA5_DATA_DIR / target_local_date.strftime('%Y-%m-%d')
    output_dir.mkdir(parents=True, exist_ok=True)
    final_output_file = output_dir / "era5_data.nc"
    temp_download_path = output_dir / "temp_download"
    report_file_path = final_output_file.with_suffix('.md')

    if final_output_file.exists():
        logger.info(f"✅ 最终数据文件已存在，跳过下载: {final_output_file}")
        return final_output_file
        
    # 下载逻辑...
    required_utc_info = _get_required_utc_dates_and_hours(target_local_date)
    if not required_utc_info:
        logger.warning("未能计算出任何需要下载的UTC日期和小时。")
        return None

    years, months, days, hours = set(), set(), set(), set()
    for utc_date_str, hours_set in required_utc_info.items():
        dt_obj = datetime.strptime(utc_date_str, '%Y-%m-%d')
        years.add(f"{dt_obj.year}")
        months.add(f"{dt_obj.month:02d}")
        days.add(f"{dt_obj.day:02d}")
        hours.update([f"{h:02d}:00" for h in hours_set])
    
    request_params = {
        'year': sorted(list(years)),
        'month': sorted(list(months)),
        'day': sorted(list(days)),
        'time': sorted(list(hours)),
    }
    
    logger.info("将为以下参数发起下载请求:")
    for key, value in request_params.items():
        logger.info(f"  > {key.capitalize()}: {value}")

    c = cdsapi.Client(timeout=600, quiet=False, url="https://cds.climate.copernicus.eu/api", key=config.CDS_API_KEY)
    area_bounds = [config.AREA_EXTRACTION[k] for k in ["north", "west", "south", "east"]]
    
    try:
        # 1. 下载到临时的文件，而不是直接命名为 .nc
        logger.info("正在向 CDS 服务器发送请求...")
        c.retrieve(
            'reanalysis-era5-single-levels',
            {
                'product_type': 'reanalysis',
                'format': 'netcdf', # 即使请求 netcdf, 服务器也可能返回 zip
                'variable': [
                    "high_cloud_cover", "medium_cloud_cover", "low_cloud_cover", 
                    "total_cloud_cover", "total_precipitation", "surface_pressure",
                    "2m_temperature", "2m_dewpoint_temperature"
                ],
                'area': area_bounds,
                **request_params
            },
            str(temp_download_path)
        )
        logger.info(f"✅ 临时文件已成功下载到: {temp_download_path}")

        # 2. 检查下载的是 ZIP 还是直接就是 NC
        if zipfile.is_zipfile(temp_download_path):
            logger.info("检测到下载文件为 ZIP 压缩包，开始解压...")
            with zipfile.ZipFile(temp_download_path, 'r') as zip_ref:
                # 寻找解压出来的 .nc 文件
                nc_files_in_zip = [f for f in zip_ref.namelist() if f.endswith('.nc')]
                if not nc_files_in_zip:
                    raise FileNotFoundError("ZIP 包中未找到任何 .nc 文件！")
                
                # 解压第一个找到的 .nc 文件
                source_nc_path = zip_ref.extract(nc_files_in_zip[0], path=output_dir)
                logger.info(f"已解压出 NetCDF 文件: {source_nc_path}")
                
                # 将解压出的文件重命名为我们最终想要的名字
                Path(source_nc_path).rename(final_output_file)
                logger.info(f"已将文件重命名为: {final_output_file}")
        else:
            # 如果不是 ZIP，说明直接下载的就是 NetCDF 文件
            logger.info("检测到下载文件为 NetCDF，直接重命名。")
            temp_download_path.rename(final_output_file)

        return final_output_file

    except Exception as e:
        logger.error(f"❌ 下载或解压过程中发生严重错误: {e}", exc_info=True)
        return None
    finally:
        # 4. 清理临时文件
        if temp_download_path.exists():
            temp_download_path.unlink()

    # 生成分析报告
    if final_output_file.exists() and not report_file_path.exists():
        try:
            with xr.open_dataset(final_output_file, engine="netcdf4") as ds:
                report_content = _generate_analysis_report(ds)
                report_file_path.write_text(report_content, encoding='utf-8')
                logger.info(f"✅ 分析报告已保存到: {report_file_path}")
        except Exception as e:
            logger.error(f"❌ 生成分析报告时出错: {e}")

    return final_output_file


# --- 主入口函数 ---

def fetch_weather_data(source: str, data_type: str, target_date_str: str) -> Path | None:
    """
    根据指定参数获取天气数据。

    Args:
        source (str): 数据源，支持 'ecmwf' 或 'gfs'。
        data_type (str): 数据类型，支持 'past' (历史) 或 'future' (预报)。
        target_date_str (str): 目标日期，格式为 'YYYYMMDD'。

    Returns:
        Path | None: 成功则返回数据文件路径，否则返回 None。
    """
    logger.info(f"--- 开始数据获取任务: source={source}, type={data_type}, date={target_date_str} ---")

    # 1. 参数验证
    supported_sources = ['ecmwf', 'gfs']
    if source not in supported_sources:
        logger.error(f"不支持的数据源: '{source}'。请选择 {supported_sources}")
        return None

    supported_types = ['past', 'future']
    if data_type not in supported_types:
        logger.error(f"不支持的数据类型: '{data_type}'。请选择 {supported_types}")
        return None

    try:
        target_date_obj = datetime.strptime(target_date_str, "%Y%m%d").date()
    except ValueError:
        logger.error(f"日期格式错误: '{target_date_str}'。请使用 'YYYYMMDD' 格式。")
        return None

    # 2. 根据参数分发到不同的处理函数
    if source == 'ecmwf':
        if data_type == 'past':
            # 这是我们已经实现的功能
            return _download_era5_past(target_date_obj)
        elif data_type == 'future':
            logger.warning("功能未实现: ECMWF 预报数据下载。")
            # 在这里可以调用 _download_ecmwf_forecast(target_date_obj)
            return None
    
    elif source == 'gfs':
        logger.warning("功能未实现: GFS 数据下载。")
        # 在这里可以调用 _download_gfs_data(target_date_obj, data_type)
        return None
    
    return None