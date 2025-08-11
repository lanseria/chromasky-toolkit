# src/chromasky_toolkit/glow_index.py

import logging
import math
import numpy as np
from datetime import datetime
from typing import Tuple, Dict, List
import xarray as xr
from tqdm.auto import tqdm
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import partial

from .astronomy import AstronomyService

class GlowIndexCalculator:
    """
    根据多种气象因子，使用混合评分模型计算火烧云指数。
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
    
    # 定义品质因子的默认权重
    DEFAULT_WEIGHTS = {
        'score_boundary': 0.8,  # 云边界距离是最重要的品质因子
        'score_hcc':      0.1,  # 高云形态是次要的品质因子
        'score_aod550':   0.1   # 大气透明度(AOD)作为新的品质因子
    }

    def __init__(self, weather_data: xr.Dataset, weights: Dict[str, float] = None):
        """
        初始化计算器。

        Args:
            weather_data (xr.Dataset): 包含所有必需气象变量的 xarray 数据集。
                                       必须包含: 'hcc', 'mcc', 'lcc', 'aod550'。
            weights (Dict[str, float], optional): 自定义的品质因子权重。
        """
        required_vars = ['hcc', 'mcc', 'lcc', 'aod550']
        if not all(var in weather_data for var in required_vars):
            missing_vars = [var for var in required_vars if var not in weather_data]
            raise KeyError(f"weather_data 中必须包含以下变量，但缺失了: {missing_vars}")
            
        self.weather_data = weather_data
        self.astro_service = AstronomyService()
        
        # 设置权重
        if weights:
            self.weights = self.DEFAULT_WEIGHTS.copy()
            self.weights.update(weights)
        else:
            self.weights = self.DEFAULT_WEIGHTS.copy()
        
        self._normalize_weights()
        logging.info("GlowIndexCalculator 初始化成功，使用品质因子权重: %s", self.weights)
    
    def _normalize_weights(self):
        """确保品质因子的权重之和为1，便于理解和调试。"""
        quality_factor_names = [k for k in self.weights if k.startswith('score_')]
        total_weight = sum(self.weights.get(f, 0) for f in quality_factor_names)
        if total_weight > 0 and not math.isclose(total_weight, 1.0):
             logging.warning(f"品质因子权重之和不为1 (当前为: {total_weight:.2f})，已自动归一化。")
             for key in quality_factor_names:
                self.weights[key] /= total_weight
    
    # ==========================================================
    # --- 评分函数 ---
    # ==========================================================

    def _score_from_boundary_distance(self, distance_km: float) -> float:
        """因子1: 根据云边界的距离，使用三角形函数计算得分。"""
        if distance_km >= self.MAX_SEARCH_DISTANCE_KM:
            return 0.0
        if distance_km <= self.OPTIMAL_DISTANCE_KM:
            return distance_km / self.OPTIMAL_DISTANCE_KM
        else:
            score = 1.0 - (distance_km - self.OPTIMAL_DISTANCE_KM) / (self.MAX_SEARCH_DISTANCE_KM - self.OPTIMAL_DISTANCE_KM)
            return max(0.0, score)
    
    def _score_from_hcc(self, hcc: float) -> float:
        """因子2: 根据高云覆盖率 (hcc) 进行分段评分。"""
        if 0.4 <= hcc <= 0.8: return 1.0
        elif hcc > 0.8: return 0.7
        elif 0.1 <= hcc < 0.4: return 0.6
        else: return 0.1

    def _score_from_mcc(self, mcc: float) -> float:
        """因子3: 根据中云覆盖率 (mcc) 进行分段评分。"""
        if 0.2 <= mcc <= 0.5: return 1.0
        elif 0.5 < mcc <= 0.8: return 0.7
        elif mcc > 0.8: return 0.3
        else: return 0.2

    def _score_from_lcc(self, lcc: float) -> float:
        """因子4: 根据低云覆盖率 (lcc) 进行分段评分。"""
        if lcc <= 0.1: return 1.0
        elif 0.1 < lcc <= 0.3: return 0.6
        elif 0.3 < lcc <= 0.5: return 0.1
        else: return 0.0

    def _score_from_aod550(self, aod: float) -> float:
        """因子5: 根据AOD550 (大气透明度) 进行分段评分。"""
        if aod < 0.3: return 1.0
        elif aod < 0.6: return 0.5
        else: return 0.0

    # ==========================================================
    # --- 核心计算逻辑 ---
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
        模型: 最终得分 = (品质因子加权平均) * (基础因子乘积)
        """
        if factors is None: factors = self.ALL_FACTORS
        
        # 获取所有相关气象数据
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

        # 计算所有分项得分
        sun_pos = self.astro_service.get_sun_position(lat, lon, utc_time)
        boundary_distance = self._find_cloud_boundary_distance(lat, lon, sun_pos['azimuth'])
        all_scores = {
            'score_boundary': self._score_from_boundary_distance(boundary_distance),
            'score_hcc': self._score_from_hcc(local_hcc),
            'score_mcc': self._score_from_mcc(local_mcc),
            'score_lcc': self._score_from_lcc(local_lcc),
            'score_aod550': self._score_from_aod550(local_aod550)
        }
        
        # a. 计算“品质”得分 (加权平均)
        quality_factors = ['score_boundary', 'score_hcc', 'score_aod550']
        total_quality_weight = sum(self.weights.get(f, 0) for f in quality_factors if f in factors)
        weighted_quality_score_sum = sum(all_scores[f] * self.weights.get(f, 0) for f in quality_factors if f in factors)
        quality_score = weighted_quality_score_sum / total_quality_weight if total_quality_weight > 0 else 0.0

        # b. 计算“基础/通行证”得分 (相乘)
        base_factors = ['score_mcc', 'score_lcc']
        base_score = np.prod([all_scores[f] for f in base_factors if f in factors]) if base_factors else 1.0

        # c. 最终得分 = 品质分 * 基础分
        all_scores['final_score'] = quality_score * base_score
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

    def _calculate_for_single_index(
        self, 
        ij_tuple: Tuple[int, int], 
        utc_time: datetime, 
        factors: List[str]
    ) -> Tuple[int, int, Dict[str, float]]:
        """为并行计算设计的工作单元。"""
        i, j = ij_tuple
        lat = self.weather_data.latitude.values[i]
        lon = self.weather_data.longitude.values[j]
        scores = self.calculate_for_point(lat, lon, utc_time, factors=factors)
        return i, j, scores

    def calculate_for_grid(
        self,
        utc_time: datetime,
        active_mask: xr.DataArray,
        factors: List[str] = None
    ) -> xr.Dataset:
        """[并行版] 为网格中的活动区域计算火烧云指数。"""
        if factors is None: factors = self.ALL_FACTORS
        logging.info(f"开始为网格活动区域并行计算指数，使用因子: {factors}")
        
        results_ds = xr.Dataset({
            score_name: xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32)
            for score_name in ['final_score'] + self.ALL_FACTORS
        })
        
        active_indices = [tuple(idx) for idx in np.argwhere(active_mask.values)]
        if not active_indices:
            logging.warning("活动区域为空，无需计算。")
            return results_ds
        
        num_workers = os.cpu_count()
        logging.info(f"将使用 {num_workers} 个工作进程进行并行计算。")

        task_function = partial(self._calculate_for_single_index, utc_time=utc_time, factors=factors)

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(task_function, ij_tuple) for ij_tuple in active_indices]
            
            progress_desc = f"Calculating Glow Index ({len(factors)} factors)"
            with tqdm(total=len(futures), desc=progress_desc) as pbar:
                for future in as_completed(futures):
                    try:
                        i, j, scores = future.result()
                        for score_name, value in scores.items():
                            if score_name in results_ds:
                                results_ds[score_name][i, j] = value
                    except Exception as e:
                        logging.error(f"一个并行任务失败: {e}", exc_info=False)
                    finally:
                        pbar.update(1)
        
        results_ds.attrs['factors_used'] = str(factors)
        results_ds.attrs['parallel_computation'] = 'True'
        
        logging.info("多因子网格并行计算完成。")
        return results_ds