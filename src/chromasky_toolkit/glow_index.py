import logging
import math
import numpy as np
from datetime import datetime
from typing import Tuple, Dict, List
import xarray as xr
from tqdm.auto import tqdm

# --- 核心改动：从新的 astronomy 模块导入服务 ---
from .astronomy import AstronomyService

class GlowIndexCalculator:
    """
    根据高云覆盖(hcc)数据，计算指定地点或整个网格的火烧云指数。
    """
    
    # --- 可调参数 ---
    CLOUD_THRESHOLD = 0.1       # 头顶高云覆盖率的最低阈值，低于此值指数为0
    OPTIMAL_HCC = 0.5           # 得分最高的最优高云覆盖率 (50%)
    
    MAX_SEARCH_DISTANCE_KM = 400.0
    SEARCH_STEP_KM = 10.0
    OPTIMAL_DISTANCE_KM = 350.0
    
    EARTH_RADIUS_KM = 6371.0

    CONSECUTIVE_CLEAR_STEPS = 3 # 需要连续3个步长（30km）都是晴空才算找到边界
    CLOUD_ZERO_THRESHOLD = 0.1

    ALL_FACTORS = ['score_boundary', 'score_hcc', 'score_mcc', 'score_lcc']

    def __init__(self, weather_data: xr.Dataset):
        """
        初始化计算器。

        Args:
            weather_data (xr.Dataset): 一个 xarray Dataset，必须包含 'hcc', 'mcc', 'lcc' 三个 DataArray。
        """
        required_vars = ['hcc', 'mcc', 'lcc']
        if not all(var in weather_data for var in required_vars):
            raise KeyError(f"weather_data 中必须包含以下变量: {required_vars}")
            
        self.weather_data = weather_data
        self.astro_service = AstronomyService()
        logging.info("GlowIndexCalculator 初始化成功，已加载 hcc, mcc, lcc 数据。")
    
    # --- 辅助方法 ---
    def _get_value_at_point(self, var_name: str, lat: float, lon: float) -> float:
        """通用方法：从 weather_data 中插值获取指定变量的值。"""
        try:
            return self.weather_data[var_name].interp(
                latitude=lat, longitude=lon, method='linear', kwargs={"fill_value": 0}
            ).item()
        except Exception:
            return 0.0
    
    # --- 因子 1: 云边界距离评分 ---
    def _score_from_boundary_distance(self, distance_km: float) -> float:
        """根据云边界的距离，使用三角形函数计算得分 (0.0 到 1.0)。"""
        if distance_km >= self.MAX_SEARCH_DISTANCE_KM:
            return 0.0
        if distance_km <= self.OPTIMAL_DISTANCE_KM:
            return distance_km / self.OPTIMAL_DISTANCE_KM
        else:
            score = 1.0 - (distance_km - self.OPTIMAL_DISTANCE_KM) / (self.MAX_SEARCH_DISTANCE_KM - self.OPTIMAL_DISTANCE_KM)
            return max(0.0, score)

    # --- 因子 2: 高云覆盖率评分 ---
    def _score_from_hcc(self, hcc: float) -> float:
        """根据高云覆盖率计算得分。在 OPTIMAL_HCC 处得分最高，向两侧递减。"""
        if hcc <= self.OPTIMAL_HCC:
            # 在 0 到最佳值之间，线性增加
            return hcc / self.OPTIMAL_HCC if self.OPTIMAL_HCC > 0 else 0.0
        else:
            # 在最佳值到 1.0 之间，线性减少
            denominator = 1.0 - self.OPTIMAL_HCC
            return 1.0 - (hcc - self.OPTIMAL_HCC) / denominator if denominator > 0 else 0.0

    # --- 因子 3: 中云覆盖率评分 ---
    def _score_from_mcc(self, mcc: float) -> float:
        """根据中云覆盖率计算得分。中云越少，分数越高。"""
        # 线性惩罚：mcc=0 -> score=1; mcc=1 -> score=0
        return 1.0 - mcc

    # --- 因子 4: 低云覆盖率评分 ---
    def _score_from_lcc(self, lcc: float) -> float:
        """根据低云覆盖率计算得分。低云越少，分数越高。"""
        # 线性惩罚：lcc=0 -> score=1; lcc=1 -> score=0
        return 1.0 - lcc

    # --- 核心计算逻辑 ---
    def calculate_for_point(
        self,
        lat: float,
        lon: float,
        utc_time: datetime,
        factors: List[str] = ALL_FACTORS
    ) -> Dict[str, float]:
        """
        为单个点计算最终的火烧云指数及其所有分项得分。
        *** 新版本: 可以选择性地使用一部分因子来计算最终得分。***
        """
        # 1. 验证传入的因子是否有效
        for factor in factors:
            if factor not in self.ALL_FACTORS:
                raise ValueError(f"无效的因子: '{factor}'. 可用因子为: {self.ALL_FACTORS}")

        # 2. 获取该点的所有云量数据
        local_hcc = self._get_value_at_point('hcc', lat, lon)
        local_mcc = self._get_value_at_point('mcc', lat, lon)
        local_lcc = self._get_value_at_point('lcc', lat, lon)

        # 3. 前提条件检查：头顶无高云，则与云相关的因子得分为0
        if local_hcc < self.CLOUD_THRESHOLD:
            # 即使头顶无云，边界分数也可能非0，但通常我们认为此时 glow index 为0
            return {
                'final_score': 0.0, 'score_boundary': 0.0, 'score_hcc': 0.0,
                'score_mcc': self._score_from_mcc(local_mcc),
                'score_lcc': self._score_from_lcc(local_lcc)
            }

        # 4. 无论如何都计算出所有可能的分项得分
        sun_pos = self.astro_service.get_sun_position(lat, lon, utc_time)
        boundary_distance = self._find_cloud_boundary_distance(lat, lon, sun_pos['azimuth'])
        all_scores = {
            'score_boundary': self._score_from_boundary_distance(boundary_distance),
            'score_hcc': self._score_from_hcc(local_hcc),
            'score_mcc': self._score_from_mcc(local_mcc),
            'score_lcc': self._score_from_lcc(local_lcc)
        }

        # 5. 根据用户选择的因子计算最终得分
        final_score = 1.0
        for factor_name in factors:
            final_score *= all_scores[factor_name]
        
        # 将最终得分添加到要返回的字典中
        all_scores['final_score'] = final_score
        
        return all_scores

    def _find_cloud_boundary_distance(self, start_lat: float, start_lon: float, sun_azimuth_deg: float) -> float:
        """
        沿太阳方位角方向搜索，直到找到云量【几乎为零】的第一个点，将其视为边界。
        *** 新逻辑: 严格寻找云结束的地方 (hcc ≈ 0)。***
        """
        num_steps = int(self.MAX_SEARCH_DISTANCE_KM / self.SEARCH_STEP_KM)
        distances = np.linspace(self.SEARCH_STEP_KM, self.MAX_SEARCH_DISTANCE_KM, num_steps)
        
        # 1. 获取整条射线上的云量值
        ray_lats, ray_lons = self._calculate_destination_point_vectorized(start_lat, start_lon, sun_azimuth_deg, distances)
        try:
            hcc_on_ray = self.weather_data['hcc'].interp(
                latitude=xr.DataArray(ray_lats, dims="distance"),
                longitude=xr.DataArray(ray_lons, dims="distance"),
                method='linear',
                kwargs={"fill_value": 0}
            ).values
        except Exception:
            # 如果插值失败，则认为整条射线都没有云
            # 对于这个逻辑，如果插值失败意味着我们立刻就出了边界
            return self.SEARCH_STEP_KM

        # 2. 找到【第一个】云量几乎为零的点的索引
        # 使用我们定义的 CLOUD_ZERO_THRESHOLD 来进行判断
        true_boundary_indices = np.where(hcc_on_ray < self.CLOUD_ZERO_THRESHOLD)[0]

        if true_boundary_indices.size > 0:
            # 如果找到了云量为零的点，返回第一个该点的距离
            first_true_boundary_index = true_boundary_indices[0]
            return distances[first_true_boundary_index]
        else:
            # 如果整条射线上云量都大于零，说明云层非常广阔，光线无法穿透
            return self.MAX_SEARCH_DISTANCE_KM

    def _calculate_destination_point_vectorized(self, lat: float, lon: float, bearing_deg: float, distance_km: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """矢量化版本，接受一个距离数组，返回坐标数组。"""
        lat_rad, lon_rad, bearing_rad = np.radians(lat), np.radians(lon), np.radians(bearing_deg)
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

    def _score_from_distance(self, distance_km: float) -> float:
        """根据云边界的距离，使用三角形函数计算得分。"""
        if distance_km >= self.MAX_SEARCH_DISTANCE_KM:
            return 0.0
        if distance_km <= self.OPTIMAL_DISTANCE_KM:
            return distance_km / self.OPTIMAL_DISTANCE_KM
        else:
            score = 1.0 - (distance_km - self.OPTIMAL_DISTANCE_KM) / (self.MAX_SEARCH_DISTANCE_KM - self.OPTIMAL_DISTANCE_KM)
            return max(0.0, score)

    
    def calculate_for_grid(
        self,
        utc_time: datetime,
        active_mask: xr.DataArray,
        factors: List[str] = ALL_FACTORS # 将参数传递到网格计算中
    ) -> xr.Dataset:
        """为网格中的活动区域计算火烧云指数，并返回包含所有分数的 Dataset。"""
        logging.info(f"开始为网格活动区域计算指数，使用因子: {factors}")
        
        # 创建一个空的 Dataset 用于存放所有结果
        results_ds = xr.Dataset(
            {
                'final_score': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
                'score_boundary': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
                'score_hcc': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
                'score_mcc': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
                'score_lcc': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
            }
        )
        
        lats, lons = self.weather_data.latitude, self.weather_data.longitude
        active_indices = np.argwhere(active_mask.values)
        
        with tqdm(total=len(active_indices), desc=f"Calculating Glow Index ({len(factors)} factors)") as pbar:
            for i, j in active_indices:
                lat, lon = lats.values[i], lons.values[j]
                # 将 factors 参数传递给单点计算函数
                scores = self.calculate_for_point(lat, lon, utc_time, factors=factors)
                for score_name, value in scores.items():
                    results_ds[score_name][i, j] = value
                pbar.update(1)
        
        results_ds.attrs['factors_used'] = str(factors)
        
        logging.info("多因子网格计算完成。")
        return results_ds