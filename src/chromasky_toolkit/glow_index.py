# src/chromasky_toolkit/glow_index.py

import ephem
import logging
import numpy as np
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Optional, Literal, Tuple
import xarray as xr
from tqdm.auto import tqdm
import math

# --- 更新后的天文服务 ---
class AstronomyService:
    """提供基于地理坐标和日期的天文事件计算服务。"""

    def get_sun_position(self, lat: float, lon: float, utc_time: datetime) -> Dict[str, float]:
        # ... (此方法保持不变) ...
        observer = ephem.Observer()
        observer.lat = str(lat)
        observer.lon = str(lon)
        observer.date = utc_time
        observer.pressure = 0
        observer.horizon = '-0:34'
        sun = ephem.Sun()
        sun.compute(observer)
        return {"altitude": np.degrees(sun.alt), "azimuth": np.degrees(sun.az)}

    # --- 使用这个修正后的版本替换原来的方法 ---
    def _calculate_single_event_time(self, lat: float, lon: float, target_date: date, event: Literal["sunrise", "sunset"]) -> Optional[datetime]:
        """
        为单个点计算日出或日落的UTC时间。
        *** 已修正：确保查找的是目标日期当天的事件 ***
        """
        observer = ephem.Observer()
        observer.lat = str(lat)
        observer.lon = str(lon)
        observer.elevation = 0
        observer.horizon = '-0.833'
        sun = ephem.Sun()
        
        # 关键修正：将观测者的时钟设置在目标日期的【开始】(00:00 UTC)
        # 这样 next_rising 和 next_setting 都会在这一天内查找事件。
        observer.date = datetime.combine(target_date, time(0, 0), tzinfo=timezone.utc)
        
        try:
            if event == "sunrise":
                # 从当天的开始查找下一次日出
                event_time_pyephem = observer.next_rising(sun, use_center=True)
            else: # sunset
                # 从当天的开始查找下一次日落
                event_time_pyephem = observer.next_setting(sun, use_center=True)
            
            utc_dt = event_time_pyephem.datetime().replace(tzinfo=timezone.utc)

            # 一个额外的健全性检查：确保找到的事件仍在目标日期内 (UTC)
            if utc_dt.date() != target_date:
                # 这在极地区域或跨日界线时可能发生，对于我们的区域可以忽略，但加上更健壮
                return None

            return utc_dt
        except (ephem.AlwaysUpError, ephem.NeverUpError):
            return None
        except Exception:
            return None

    # --- 新增的核心方法 ---
    def create_event_mask(
        self,
        lats: xr.DataArray,
        lons: xr.DataArray,
        target_utc_time: datetime,
        event: Literal["sunrise", "sunset"],
        window_minutes: int = 60
    ) -> xr.DataArray:
        """
        为整个网格创建一个布尔掩码，标记出在目标时间窗口内发生指定天文事件的区域。

        Args:
            lats (xr.DataArray): 纬度坐标数组。
            lons (xr.DataArray): 经度坐标数组。
            target_utc_time (datetime): 观测的中心UTC时间。
            event (Literal["sunrise", "sunset"]): 要关注的天文事件。
            window_minutes (int, optional): 时间窗口的半径（分钟）。默认为60分钟。

        Returns:
            xr.DataArray: 与输入网格形状相同的布尔掩码。True表示需要计算。
        """
        logging.info(f"正在为 {event} 创建时间掩码，中心时间: {target_utc_time.strftime('%H:%M')} UTC, 窗口: ±{window_minutes}分钟")
        
        mask_grid = np.full((len(lats), len(lons)), False, dtype=bool)
        target_date = target_utc_time.date()
        time_window = timedelta(minutes=window_minutes)

        # 遍历网格计算每个点的事件时间
        with tqdm(total=len(lats) * len(lons), desc=f"Calculating {event} times") as pbar:
            for i, lat in enumerate(lats.values):
                for j, lon in enumerate(lons.values):
                    event_time_utc = self._calculate_single_event_time(lat, lon, target_date, event)
                    
                    # 如果该点有明确的日出/日落时间
                    if event_time_utc:
                        # 检查事件时间是否落在我们的目标窗口内
                        if abs(event_time_utc - target_utc_time) <= time_window:
                            mask_grid[i, j] = True
                    pbar.update(1)

        return xr.DataArray(
            mask_grid,
            coords={'latitude': lats, 'longitude': lons},
            dims=['latitude', 'longitude']
        )

# --- 核心算法实现 ---
class GlowIndexCalculator:
    """
    根据高云覆盖(hcc)数据，计算指定地点的火烧云指数。
    """
    
    # --- 可调参数 ---
    # 定义云的边界阈值，低于此值视为天空无云
    CLOUD_THRESHOLD = 0.1
    # 搜索云边界的最大距离（公里）
    MAX_SEARCH_DISTANCE_KM = 400.0
    # 搜索步长（公里）
    SEARCH_STEP_KM = 10.0
    # 得分最高的最佳距离（公里）
    OPTIMAL_DISTANCE_KM = 350.0
    # 地球平均半径（公里），用于测地线计算
    EARTH_RADIUS_KM = 6371.0


    def __init__(self, hcc_data: xr.DataArray):
        if not isinstance(hcc_data, xr.DataArray):
            raise TypeError("hcc_data 必须是 xarray.DataArray 类型")
        self.hcc_data = hcc_data
        self.astro_service = AstronomyService()
        logging.info("GlowIndexCalculator 初始化成功。")

    def _calculate_destination_point(self, lat: float, lon: float, bearing_deg: float, distance_km: float) -> Tuple[float, float]:
        """
        根据起点、方位角和距离计算终点坐标（测地线直接问题）。
        """
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        bearing_rad = math.radians(bearing_deg)
        
        angular_distance = distance_km / self.EARTH_RADIUS_KM

        dest_lat_rad = math.asin(
            math.sin(lat_rad) * math.cos(angular_distance) +
            math.cos(lat_rad) * math.sin(angular_distance) * math.cos(bearing_rad)
        )
        
        dest_lon_rad = lon_rad + math.atan2(
            math.sin(bearing_rad) * math.sin(angular_distance) * math.cos(lat_rad),
            math.cos(angular_distance) - math.sin(lat_rad) * math.sin(dest_lat_rad)
        )

        return math.degrees(dest_lat_rad), math.degrees(dest_lon_rad)

    def _get_hcc_at_point(self, lat: float, lon: float) -> float:
        """
        使用线性插值获取任意坐标点的高云覆盖率。
        """
        try:
            # 使用 fill_value=0 可以在插值超出边界时返回0
            interpolated_value = self.hcc_data.interp(
                latitude=lat, longitude=lon, method='linear', kwargs={"fill_value": 0}
            ).item()
            return interpolated_value
        except Exception:
            # 如果插值失败（例如点在数据范围之外很远），返回0
            return 0.0

    def _find_cloud_boundary_distance(self, start_lat: float, start_lon: float, sun_azimuth_deg: float) -> float:
        """
        沿太阳方位角方向搜索云的边界，并返回其距离。
        """
        for distance in np.arange(self.SEARCH_STEP_KM, self.MAX_SEARCH_DISTANCE_KM + self.SEARCH_STEP_KM, self.SEARCH_STEP_KM):
            # 计算搜索路径上的下一个点
            next_lat, next_lon = self._calculate_destination_point(start_lat, start_lon, sun_azimuth_deg, distance)
            
            # 获取该点的高云覆盖率
            hcc_at_next_point = self._get_hcc_at_point(next_lat, next_lon)
            
            # 如果云量低于阈值，我们找到了边界
            if hcc_at_next_point < self.CLOUD_THRESHOLD:
                # logging.debug(f"在 {distance:.1f} km 处找到云边界 (Hcc: {hcc_at_next_point:.2f})")
                return distance
        
        # 如果循环完成仍未找到边界，则返回最大搜索距离
        # logging.debug(f"在 {self.MAX_SEARCH_DISTANCE_KM} km 内未找到云边界。")
        return self.MAX_SEARCH_DISTANCE_KM
        
    def _score_from_distance(self, distance_km: float) -> float:
        """
        根据云边界的距离，使用三角形函数计算得分 (0.0 到 1.0)。
        """
        if distance_km >= self.MAX_SEARCH_DISTANCE_KM:
            return 0.0
        
        if distance_km <= self.OPTIMAL_DISTANCE_KM:
            # 在 0 到最佳距离之间，得分线性增加
            # 当 distance_km = OPTIMAL_DISTANCE_KM 时, score = 1.0
            score = distance_km / self.OPTIMAL_DISTANCE_KM
        else:
            # 在最佳距离到最大距离之间，得分线性减少
            # (distance_km - OPTIMAL_DISTANCE_KM) 是超出最佳距离的部分
            # (MAX_SEARCH_DISTANCE_KM - OPTIMAL_DISTANCE_KM) 是这段区间的总长度
            score = 1.0 - (distance_km - self.OPTIMAL_DISTANCE_KM) / (self.MAX_SEARCH_DISTANCE_KM - self.OPTIMAL_DISTANCE_KM)
            
        return max(0.0, score) # 确保得分不为负

    def _find_cloud_boundary_distance(self, start_lat: float, start_lon: float, sun_azimuth_deg: float) -> float:
        """
        沿太阳方位角方向搜索云的边界，并返回其距离。
        *** 已优化为矢量化插值 ***
        """
        num_steps = int(self.MAX_SEARCH_DISTANCE_KM / self.SEARCH_STEP_KM)
        distances = np.linspace(self.SEARCH_STEP_KM, self.MAX_SEARCH_DISTANCE_KM, num_steps)
        
        # 1. 一次性计算出射线上所有点的坐标
        ray_lats, ray_lons = self._calculate_destination_point_vectorized(start_lat, start_lon, sun_azimuth_deg, distances)

        # 2. 一次性对所有点进行插值
        try:
            hcc_on_ray = self.hcc_data.interp(
                latitude=xr.DataArray(ray_lats, dims="distance"),
                longitude=xr.DataArray(ray_lons, dims="distance"),
                method='linear',
                kwargs={"fill_value": 0}
            ).values
        except Exception:
            # 如果插值失败，则认为整条射线都没有云
            hcc_on_ray = np.zeros_like(distances)
            
        # 3. 找到第一个低于阈值的点的索引
        boundary_indices = np.where(hcc_on_ray < self.CLOUD_THRESHOLD)[0]
        
        if boundary_indices.size > 0:
            # 如果找到了边界，返回对应的距离
            first_boundary_index = boundary_indices[0]
            return distances[first_boundary_index]
        else:
            # 如果没找到，返回最大距离
            return self.MAX_SEARCH_DISTANCE_KM

    def _calculate_destination_point_vectorized(self, lat: float, lon: float, bearing_deg: float, distance_km: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        矢量化版本，接受一个距离数组，返回坐标数组。
        """
        lat_rad = np.radians(lat)
        lon_rad = np.radians(lon)
        bearing_rad = np.radians(bearing_deg)
        
        angular_distances = distance_km / self.EARTH_RADIUS_KM

        dest_lat_rad = np.arcsin(
            np.sin(lat_rad) * np.cos(angular_distances) +
            np.cos(lat_rad) * np.sin(angular_distances) * np.cos(bearing_rad)
        )
        
        dest_lon_rad = lon_rad + np.arctan2(
            np.sin(bearing_rad) * np.sin(angular_distances) * np.cos(lat_rad),
            np.cos(angular_distances) - np.sin(lat_rad) * np.sin(dest_lat_rad)
        )

        return np.degrees(dest_lat_rad), np.degrees(dest_lon_rad)

    def calculate_for_point(self, lat: float, lon: float, utc_time: datetime) -> float:
        """
        为单个点计算最终的火烧云指数。

        Args:
            lat (float): 观测点纬度
            lon (float): 观测点经度
            utc_time (datetime): 观测时的UTC时间

        Returns:
            float: 计算出的火烧云指数 (0.0 到 1.0)。
        """
        # 步骤 1: 检查头顶是否有云，没有则直接返回0分
        local_hcc = self._get_hcc_at_point(lat, lon)
        if local_hcc < self.CLOUD_THRESHOLD:
            return 0.0

        # 步骤 2: 获取太阳方位角
        sun_pos = self.astro_service.get_sun_position(lat, lon, utc_time)
        sun_azimuth = sun_pos['azimuth']
        # print(f"太阳方位角: {sun_azimuth:.2f} 度")

        # 步骤 3: 沿方位角寻找云边界距离
        boundary_distance = self._find_cloud_boundary_distance(lat, lon, sun_azimuth)
        # print(f"找到云边界距离: {boundary_distance:.2f} km")

        # 步骤 4: 根据距离计算最终得分
        score = self._score_from_distance(boundary_distance)

        return score
    
    # --- 网格计算方法 (已集成掩码优化) ---
    def calculate_for_grid(self, utc_time: datetime, active_mask: xr.DataArray) -> xr.DataArray:
        """
        为 hcc_data 网格中被掩码标记的区域计算火烧云指数。
        """
        logging.info(f"开始为网格的活动区域计算指数，时间: {utc_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        if not isinstance(active_mask, xr.DataArray) or active_mask.dtype != bool:
            raise TypeError("active_mask 必须是布尔型的 xarray.DataArray")

        lats = self.hcc_data.latitude
        lons = self.hcc_data.longitude
        
        glow_index_grid = xr.full_like(self.hcc_data, 0.0, dtype=np.float32)

        active_indices = np.argwhere(active_mask.values)
        logging.info(f"根据提供的掩码，将对 {len(active_indices)} 个点进行计算。")
        
        with tqdm(total=len(active_indices), desc="Calculating Glow Index") as pbar:
            for i, j in active_indices:
                lat, lon = lats.values[i], lons.values[j]
                score = self.calculate_for_point(lat, lon, utc_time)
                glow_index_grid[i, j] = score
                pbar.update(1)
        
        glow_index_grid.name = "glow_index"
        glow_index_grid.attrs['long_name'] = "Sunset/Sunrise Glow Index"
        glow_index_grid.attrs['units'] = "0-1"
        glow_index_grid.attrs['description'] = "Index predicting the quality of sunset/sunrise glow."
        glow_index_grid.attrs['utc_time'] = utc_time.isoformat()
        
        logging.info("网格计算完成。")
        return glow_index_grid