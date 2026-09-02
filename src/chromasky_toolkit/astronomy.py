import ephem
import logging
import numpy as np
from datetime import datetime, date, time, timedelta, timezone
from functools import lru_cache
from typing import Dict, Optional, Literal
import xarray as xr
from tqdm.auto import tqdm

logger = logging.getLogger(__name__)


@lru_cache(maxsize=100_000)
def _cached_event_time(
    lat: float, lon: float, target_date: date, event: str
) -> Optional[datetime]:
    """
    计算单个点的日出/日落 UTC 时间，并按 (坐标, 日期, 事件类型) 缓存。
    同一天同一事件的多次时间窗口掩码计算只需算一次。
    """
    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    observer.elevation = 0
    observer.horizon = '-0:833'
    sun = ephem.Sun()

    observer.date = datetime.combine(target_date, time(0, 0), tzinfo=timezone.utc)

    try:
        if event == "sunrise":
            event_time_pyephem = observer.next_rising(sun, use_center=True)
        else:  # sunset
            event_time_pyephem = observer.next_setting(sun, use_center=True)

        utc_dt = event_time_pyephem.datetime().replace(tzinfo=timezone.utc)

        if utc_dt.date() != target_date:
            return None
        return utc_dt
    except (ephem.AlwaysUpError, ephem.NeverUpError):
        return None
    except Exception as e:
        logger.debug(f"在 ({lat}, {lon}) 计算天文事件时出错: {e}")
        return None


class AstronomyService:
    """提供基于地理坐标和日期的天文事件计算服务。"""

    def get_sun_position(self, lat: float, lon: float, utc_time: datetime) -> Dict[str, float]:
        """计算指定地点和时间的太阳位置（高度角和方位角）。"""
        observer = ephem.Observer()
        observer.lat = str(lat)
        observer.lon = str(lon)
        observer.date = utc_time
        observer.pressure = 0
        observer.horizon = '-0:34'
        sun = ephem.Sun()
        sun.compute(observer)
        return {"altitude": np.degrees(sun.alt), "azimuth": np.degrees(sun.az)}

    def get_sun_azimuth_batch(self, lats: np.ndarray, lons: np.ndarray, utc_time: datetime) -> np.ndarray:
        """
        批量计算一批点的太阳方位角（度），结果与逐点调用 get_sun_position 一致。
        ephem 无矢量化接口，此处复用同一个 Observer 对象以减少开销。
        """
        observer = ephem.Observer()
        observer.date = utc_time
        observer.pressure = 0
        observer.horizon = '-0:34'
        sun = ephem.Sun()
        azimuths = np.empty(len(lats), dtype=np.float64)
        for k in range(len(lats)):
            observer.lat = str(lats[k])
            observer.lon = str(lons[k])
            sun.compute(observer)
            azimuths[k] = np.degrees(sun.az)
        return azimuths

    def _calculate_single_event_time(self, lat: float, lon: float, target_date: date, event: Literal["sunrise", "sunset"]) -> Optional[datetime]:
        """为单个点计算日出或日落的UTC时间。"""
        return _cached_event_time(lat, lon, target_date, event)

    def create_event_mask(
        self,
        lats: xr.DataArray,
        lons: xr.DataArray,
        target_utc_time: datetime,
        event: Literal["sunrise", "sunset"],
        window_minutes: int = 60
    ) -> xr.DataArray:
        """为整个网格创建一个布尔掩码，标记出在目标时间窗口内发生指定天文事件的区域。"""
        logger.info(f"正在为 {event} 创建时间掩码，中心时间: {target_utc_time.strftime('%H:%M')} UTC, 窗口: ±{window_minutes}分钟")
        
        mask_grid = np.full((len(lats), len(lons)), False, dtype=bool)
        target_date = target_utc_time.date()
        time_window = timedelta(minutes=window_minutes)

        lon_values = lons.values
        with tqdm(total=len(lats), desc=f"Calculating {event} times") as pbar:
            for i, lat in enumerate(lats.values):
                for j, lon in enumerate(lon_values):
                    event_time_utc = _cached_event_time(lat, lon, target_date, event)
                    if event_time_utc and abs(event_time_utc - target_utc_time) <= time_window:
                        mask_grid[i, j] = True
                pbar.update(1)

        return xr.DataArray(
            mask_grid,
            coords={'latitude': lats, 'longitude': lons},
            dims=['latitude', 'longitude']
        )