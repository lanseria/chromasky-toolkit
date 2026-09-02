# src/chromasky_toolkit/glow_index.py

import logging
import math
import numpy as np
from datetime import datetime
from typing import Tuple, Dict, List
import xarray as xr
from scipy.interpolate import RegularGridInterpolator

from .astronomy import AstronomyService

class GlowIndexCalculator:
    """
    根据多种气象因子，使用混合评分模型计算火烧云指数。
    新模型: 最终得分 = (品质分) * (惩罚分)
    """
    
    # --- 类常量与配置 ---
    CLOUD_THRESHOLD = 0.1
    MAX_SEARCH_DISTANCE_KM = 500.0
    SEARCH_STEP_KM = 10.0
    OPTIMAL_DISTANCE_KM = 400.0
    EARTH_RADIUS_KM = 6371.0
    CLOUD_ZERO_THRESHOLD = 0.1

    # 定义所有可用的评分因子名称
    ALL_FACTORS = ['score_boundary', 'score_hcc', 'score_mcc', 'score_lcc', 'score_aod550']
    
    # 定义品质因子的默认权重 (总和为10)
    DEFAULT_WEIGHTS = {
        'score_boundary': 8.0,  # 云边界距离是最重要的品质因子
        'score_hcc':      1.0,  # 高云形态
        'score_mcc':      1.0,  # 中云形态也作为品质的一部分
    }

    def __init__(self, weather_data: xr.Dataset, weights: Dict[str, float] = None):
        """
        初始化计算器。
        """
        required_vars = ['hcc', 'mcc', 'lcc', 'aod550']
        if not all(var in weather_data for var in required_vars):
            missing_vars = [var for var in required_vars if var not in weather_data]
            raise KeyError(f"weather_data 中必须包含以下变量，但缺失了: {missing_vars}")
            
        self.weather_data = weather_data
        self.astro_service = AstronomyService()
        
        if weights:
            self.weights = self.DEFAULT_WEIGHTS.copy()
            self.weights.update(weights)
        else:
            self.weights = self.DEFAULT_WEIGHTS.copy()
        
        self._normalize_weights()
        logging.info("GlowIndexCalculator 初始化成功，使用品质因子权重: %s", self.weights)
    
    def _normalize_weights(self):
        """确保品质因子的权重之和为1，便于理解和调试。"""
        quality_factor_names = ['score_boundary', 'score_hcc', 'score_mcc']
        total_weight = sum(self.weights.get(f, 0) for f in quality_factor_names)
        if total_weight > 0 and not math.isclose(total_weight, 1.0):
            logging.info(f"品质因子权重之和不为1 (当前为: {total_weight:.2f})，已自动归一化。")
            for key in quality_factor_names:
                if key in self.weights:
                    self.weights[key] /= total_weight
    
    # ==========================================================
    # --- 评分函数 (函数本身不变，但其作用已重新分类) ---
    # ==========================================================

    def _score_from_boundary_distance(self, distance_km: float) -> float:
        """品质因子1: 云边界距离"""
        if distance_km >= self.MAX_SEARCH_DISTANCE_KM: return 0.0
        if distance_km <= self.OPTIMAL_DISTANCE_KM: return distance_km / self.OPTIMAL_DISTANCE_KM
        score = 1.0 - (distance_km - self.OPTIMAL_DISTANCE_KM) / (self.MAX_SEARCH_DISTANCE_KM - self.OPTIMAL_DISTANCE_KM)
        return max(0.0, score)
    
    def _score_from_hcc(self, hcc: float) -> float:
        """品质因子2: 高云覆盖率"""
        if 0.4 <= hcc <= 0.8: return 1.0
        elif hcc > 0.8: return 0.7
        elif 0.1 <= hcc < 0.4: return 0.6
        else: return 0.1

    def _score_from_mcc(self, mcc: float) -> float:
        """品质因子3: 中云覆盖率"""
        if 0.2 <= mcc <= 0.5: return 1.0
        elif 0.5 < mcc <= 0.8: return 0.7
        elif mcc > 0.8: return 0.3
        else: return 0.2

    def _score_from_lcc(self, lcc: float) -> float:
        """惩罚因子1: 低云遮挡"""
        if lcc <= 0.1: return 1.0
        elif 0.1 < lcc <= 0.3: return 0.6
        elif 0.3 < lcc <= 0.5: return 0.1
        else: return 0.0

    def _score_from_aod550(self, aod: float) -> float:
        """惩罚因子2: 大气透明度"""
        if aod < 0.3: return 1.0
        elif aod < 0.6: return 0.5
        else: return 0.0

    # ==========================================================
    # --- 矢量化评分函数（与上方标量版分支语义一一对应，含 NaN 处理） ---
    # ==========================================================

    @staticmethod
    def _score_boundary_array(distances: np.ndarray) -> np.ndarray:
        """品质因子1: 云边界距离（数组版）"""
        out = np.where(
            distances <= GlowIndexCalculator.OPTIMAL_DISTANCE_KM,
            distances / GlowIndexCalculator.OPTIMAL_DISTANCE_KM,
            1.0 - (distances - GlowIndexCalculator.OPTIMAL_DISTANCE_KM)
            / (GlowIndexCalculator.MAX_SEARCH_DISTANCE_KM - GlowIndexCalculator.OPTIMAL_DISTANCE_KM),
        )
        out = np.where(distances >= GlowIndexCalculator.MAX_SEARCH_DISTANCE_KM, 0.0, out)
        return np.maximum(out, 0.0)

    @staticmethod
    def _score_hcc_array(hcc: np.ndarray) -> np.ndarray:
        """品质因子2: 高云覆盖率（数组版）"""
        return np.select(
            [(hcc >= 0.4) & (hcc <= 0.8), hcc > 0.8, (hcc >= 0.1) & (hcc < 0.4)],
            [1.0, 0.7, 0.6],
            default=0.1,
        )

    @staticmethod
    def _score_mcc_array(mcc: np.ndarray) -> np.ndarray:
        """品质因子3: 中云覆盖率（数组版）"""
        return np.select(
            [(mcc >= 0.2) & (mcc <= 0.5), (mcc > 0.5) & (mcc <= 0.8), mcc > 0.8],
            [1.0, 0.7, 0.3],
            default=0.2,
        )

    @staticmethod
    def _score_lcc_array(lcc: np.ndarray) -> np.ndarray:
        """惩罚因子1: 低云遮挡（数组版）"""
        return np.select(
            [lcc <= 0.1, lcc <= 0.3, lcc <= 0.5],
            [1.0, 0.6, 0.1],
            default=0.0,
        )

    @staticmethod
    def _score_aod550_array(aod: np.ndarray) -> np.ndarray:
        """惩罚因子2: 大气透明度（数组版）"""
        return np.select(
            [aod < 0.3, aod < 0.6],
            [1.0, 0.5],
            default=0.0,
        )

    # ==========================================================
    # --- 核心计算逻辑 (已更新为新品质/惩罚模型) ---
    # ==========================================================

    def calculate_for_point(
        self,
        lat: float,
        lon: float,
        utc_time: datetime,
        factors: List[str] = None 
    ) -> Dict[str, float]:
        """
        为单个点计算最终的火烧云指数及其所有分项得分。
        新模型: 最终得分 = (品质分) * (惩罚分)
        """
        if factors is None: factors = self.ALL_FACTORS
        
        local_hcc = self._get_value_at_point('hcc', lat, lon)
        local_mcc = self._get_value_at_point('mcc', lat, lon)
        local_lcc = self._get_value_at_point('lcc', lat, lon)
        local_aod550 = self._get_value_at_point('aod550', lat, lon)

        # 提前退出条件：如果观测点上方几乎没有高云，则认为没有观赏价值
        if local_hcc < self.CLOUD_THRESHOLD:
            return {
                'final_score': 0.0, 'score_boundary': 0.0, 'score_hcc': 0.0,
                'score_mcc': self._score_from_mcc(local_mcc),
                'score_lcc': self._score_from_lcc(local_lcc),
                'score_aod550': self._score_from_aod550(local_aod550)
            }
        
        # 1. 计算所有分项得分
        sun_pos = self.astro_service.get_sun_position(lat, lon, utc_time)
        boundary_distance = self._find_cloud_boundary_distance(lat, lon, sun_pos['azimuth'])
        all_scores = {
            'score_boundary': self._score_from_boundary_distance(boundary_distance),
            'score_hcc': self._score_from_hcc(local_hcc),
            'score_mcc': self._score_from_mcc(local_mcc),
            'score_lcc': self._score_from_lcc(local_lcc),
            'score_aod550': self._score_from_aod550(local_aod550)
        }
        
        # 2. 计算“品质分” (加权平均)
        quality_factors = ['score_boundary', 'score_hcc', 'score_mcc']
        total_quality_weight = sum(self.weights.get(f, 0) for f in quality_factors if f in factors)
        weighted_quality_score_sum = sum(all_scores[f] * self.weights.get(f, 0) for f in quality_factors if f in factors)
        quality_score = weighted_quality_score_sum / total_quality_weight if total_quality_weight > 0 else 0.0

        # 3. 计算“惩罚分” (相乘)
        penalty_factors = ['score_aod550', 'score_lcc']
        penalty_score = np.prod([all_scores[f] for f in penalty_factors if f in factors]) if penalty_factors else 1.0

        # 4. 最终得分 = 品质分 * 惩罚分
        all_scores['final_score'] = quality_score * penalty_score
        return all_scores

    # ==========================================================
    # --- 辅助方法与并行计算 ---
    # ==========================================================
    
    def _get_value_at_point(self, var_name: str, lat: float, lon: float) -> float:
        """通用方法：从 weather_data 中插值获取指定变量的值。"""
        try:
            return self.weather_data[var_name].interp(
                latitude=lat, longitude=lon, method='linear', kwargs={"fill_value": 0}
            ).item()
        except Exception:
            return 0.0

    def _find_cloud_boundary_distance(self, start_lat: float, start_lon: float, sun_azimuth_deg: float) -> float:
        """沿太阳方位角方向搜索，直到找到云量几乎为零的第一个点。"""
        num_steps = int(self.MAX_SEARCH_DISTANCE_KM / self.SEARCH_STEP_KM)
        distances = np.linspace(self.SEARCH_STEP_KM, self.MAX_SEARCH_DISTANCE_KM, num_steps)
        
        ray_lats, ray_lons = self._calculate_destination_point_vectorized(start_lat, start_lon, sun_azimuth_deg, distances)
        try:
            hcc_on_ray = self.weather_data['hcc'].interp(
                latitude=xr.DataArray(ray_lats, dims="distance"),
                longitude=xr.DataArray(ray_lons, dims="distance"),
                method='linear', kwargs={"fill_value": 0}
            ).values
        except Exception:
            return self.SEARCH_STEP_KM

        true_boundary_indices = np.where(hcc_on_ray < self.CLOUD_ZERO_THRESHOLD)[0]
        return distances[true_boundary_indices[0]] if true_boundary_indices.size > 0 else self.MAX_SEARCH_DISTANCE_KM

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

    def _calculate_destination_points_batch(
        self,
        lat: np.ndarray,
        lon: np.ndarray,
        bearing_deg: np.ndarray,
        distance_km: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        矢量化前向公式（批量版）。
        lat/lon/bearing_deg 形状 (m,)，distance_km 形状 (n,)，返回形状 (m, n) 的坐标数组。
        """
        lat_rad = np.radians(lat)[:, None]
        lon_rad = np.radians(lon)[:, None]
        bearing_rad = np.radians(bearing_deg)[:, None]
        angular_distances = (distance_km / self.EARTH_RADIUS_KM)[None, :]
        dest_lat_rad = np.arcsin(
            np.sin(lat_rad) * np.cos(angular_distances) +
            np.cos(lat_rad) * np.sin(angular_distances) * np.cos(bearing_rad)
        )
        dest_lon_rad = lon_rad + np.arctan2(
            np.sin(bearing_rad) * np.sin(angular_distances) * np.cos(lat_rad),
            np.cos(angular_distances) - np.sin(lat_rad) * np.sin(dest_lat_rad)
        )
        return np.degrees(dest_lat_rad), np.degrees(dest_lon_rad)

    def _boundary_distances(
        self,
        pt_lats: np.ndarray,
        pt_lons: np.ndarray,
        azimuths: np.ndarray,
    ) -> np.ndarray:
        """沿太阳方位角方向搜索云边界距离（批量双线性插值，网格外取 0，与标量版一致）。"""
        num_steps = int(self.MAX_SEARCH_DISTANCE_KM / self.SEARCH_STEP_KM)
        distances = np.linspace(self.SEARCH_STEP_KM, self.MAX_SEARCH_DISTANCE_KM, num_steps)

        ray_lats, ray_lons = self._calculate_destination_points_batch(
            pt_lats, pt_lons, azimuths, distances
        )

        hcc_da = self.weather_data['hcc']
        grid_lats = hcc_da.latitude.values
        grid_lons = hcc_da.longitude.values
        hcc_vals = hcc_da.values
        # RegularGridInterpolator 要求坐标递增
        if grid_lats[0] > grid_lats[-1]:
            grid_lats = grid_lats[::-1]
            hcc_vals = hcc_vals[::-1, :]

        interpolator = RegularGridInterpolator(
            (grid_lats, grid_lons), hcc_vals,
            method='linear', bounds_error=False, fill_value=0.0,
        )
        query_points = np.stack([ray_lats.ravel(), ray_lons.ravel()], axis=-1)
        hcc_on_ray = interpolator(query_points).reshape(ray_lats.shape)

        below_threshold = hcc_on_ray < self.CLOUD_ZERO_THRESHOLD
        has_boundary = below_threshold.any(axis=1)
        first_idx = np.where(has_boundary, np.argmax(below_threshold, axis=1), 0)
        return np.where(has_boundary, distances[first_idx], self.MAX_SEARCH_DISTANCE_KM)

    def calculate_for_grid(
        self,
        utc_time: datetime,
        active_mask: xr.DataArray,
        factors: List[str] = None
    ) -> xr.Dataset:
        """
        [矢量化版] 为网格中的活动区域计算火烧云指数。
        整个网格用 numpy 批量计算，无进程间通信开销。
        """
        if factors is None: factors = self.ALL_FACTORS
        logging.info(f"开始为网格活动区域矢量化计算指数，使用因子: {factors}")

        results_ds = xr.Dataset({
            score_name: xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32)
            for score_name in ['final_score'] + self.ALL_FACTORS
        })

        ii, jj = np.nonzero(active_mask.values)
        if ii.size == 0:
            logging.warning("活动区域为空，无需计算。")
            results_ds.attrs['factors_used'] = str(factors)
            return results_ds

        grid_lats = self.weather_data.latitude.values
        grid_lons = self.weather_data.longitude.values
        hcc = self.weather_data['hcc'].values
        mcc = self.weather_data['mcc'].values
        lcc = self.weather_data['lcc'].values
        aod = self.weather_data['aod550'].values

        # 活动点均为网格节点，直接取值等价于标量版在节点处的 interp
        local_hcc = hcc[ii, jj]
        local_mcc = mcc[ii, jj]
        local_lcc = lcc[ii, jj]
        local_aod = aod[ii, jj]

        score_boundary = np.zeros(ii.size)
        score_hcc = np.zeros(ii.size)
        score_mcc = self._score_mcc_array(local_mcc)
        score_lcc = self._score_lcc_array(local_lcc)
        score_aod = self._score_aod550_array(local_aod)

        # 与标量版一致：仅当本地高云量达到阈值时才计算太阳方位并搜索云边界
        # （NaN 与阈值比较为 False，会走完整计算路径，行为与标量版相同）
        need_search = ~(local_hcc < self.CLOUD_THRESHOLD)
        if need_search.any():
            s_lats = grid_lats[ii[need_search]]
            s_lons = grid_lons[jj[need_search]]
            azimuths = self.astro_service.get_sun_azimuth_batch(s_lats, s_lons, utc_time)
            score_boundary[need_search] = self._score_boundary_array(
                self._boundary_distances(s_lats, s_lons, azimuths)
            )
            score_hcc[need_search] = self._score_hcc_array(local_hcc[need_search])

        scores_map = {
            'score_boundary': score_boundary,
            'score_hcc': score_hcc,
            'score_mcc': score_mcc,
            'score_lcc': score_lcc,
            'score_aod550': score_aod,
        }

        # 品质分（加权平均）
        quality_factors = ['score_boundary', 'score_hcc', 'score_mcc']
        total_quality_weight = sum(self.weights.get(f, 0) for f in quality_factors if f in factors)
        if total_quality_weight > 0:
            quality_sum = np.zeros(ii.size)
            for f in quality_factors:
                if f in factors:
                    quality_sum += self.weights.get(f, 0) * scores_map[f]
            quality_score = quality_sum / total_quality_weight
        else:
            quality_score = np.zeros(ii.size)

        # 惩罚分（相乘）
        penalty_factors = ['score_aod550', 'score_lcc']
        penalty_score = np.ones(ii.size)
        for f in penalty_factors:
            if f in factors:
                penalty_score = penalty_score * scores_map[f]

        final_score = quality_score * penalty_score
        # 标量版对高云量不足阈值的点直接返回 0 分
        final_score[~need_search] = 0.0

        results_map = {'final_score': final_score, **scores_map}
        for name, arr in results_map.items():
            results_ds[name].values[ii, jj] = arr

        results_ds.attrs['factors_used'] = str(factors)
        logging.info("网格矢量化计算完成。")
        return results_ds