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
    
    # --- 可调参数 ---
    CLOUD_THRESHOLD = 0.1
    MAX_SEARCH_DISTANCE_KM = 500.0
    SEARCH_STEP_KM = 10.0
    OPTIMAL_DISTANCE_KM = 400.0
    EARTH_RADIUS_KM = 6371.0
    CLOUD_ZERO_THRESHOLD = 0.1

    # 定义所有可用的评分因子名称
    ALL_FACTORS = ['score_boundary', 'score_hcc', 'score_mcc', 'score_lcc']
    
    # 权重现在只用于“品质因子”的加权平均
    DEFAULT_WEIGHTS = {
        'score_boundary': 0.9,  # 云边界距离是最重要的品质因子
        'score_hcc':      0.1   # 高云形态是次要的品质因子
    }
    # (注意: mcc 和 lcc 的权重不再需要，因为它们将作为乘法项)

    def __init__(self, weather_data: xr.Dataset, weights: Dict[str, float] = None):
        """初始化计算器，可以传入自定义的品质因子权重。"""
        required_vars = ['hcc', 'mcc', 'lcc']
        if not all(var in weather_data for var in required_vars):
            raise KeyError(f"weather_data 中必须包含以下变量: {required_vars}")
            
        self.weather_data = weather_data
        self.astro_service = AstronomyService()
        
        if weights:
            self.weights = self.DEFAULT_WEIGHTS.copy()
            self.weights.update(weights)
        else:
            self.weights = self.DEFAULT_WEIGHTS.copy()
        logging.info("GlowIndexCalculator 初始化成功，使用品质因子权重: %s", self.weights)
    
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
    
    # --- 因子 2: 高云覆盖率评分 (新版分段逻辑) ---
    def _score_from_hcc(self, hcc: float) -> float:
        """
        根据高云覆盖率 (hcc, 0-1) 进行分段评分。
        - 40-80% (0.4-0.8): 1.0分 (最理想)
        - 80-100% (0.8-1.0): 0.7分 (云量略多)
        - 10-40% (0.1-0.4): 0.6分 (云量略少)
        - 0-10% (0.0-0.1): 0.1分 (云量太少，效果不佳)
        """
        if 0.4 <= hcc <= 0.8:
            return 1.0
        elif hcc > 0.8:
            return 0.7
        elif 0.1 <= hcc < 0.4:
            return 0.6
        else: # hcc < 0.1
            return 0.1

    # --- 因子 3: 中云覆盖率评分 (新版分段逻辑) ---
    def _score_from_mcc(self, mcc: float) -> float:
        """
        根据中云覆盖率 (mcc, 0-1) 进行分段评分。
        - 20-50% (0.2-0.5): 1.0分 (最理想，提供层次感)
        - 50-80% (0.5-0.8): 0.7分 (略多，可能遮挡高云)
        - 80-100% (0.8-1.0): 0.3分 (太多，严重遮挡)
        - 0-20% (0.0-0.2): 0.2分 (太少，缺乏层次)
        """
        if 0.2 <= mcc <= 0.5:
            return 1.0
        elif 0.5 < mcc <= 0.8:
            return 0.7
        elif mcc > 0.8:
            return 0.3
        else: # mcc < 0.2
            return 0.2

    # --- 因子 4: 低云覆盖率评分 (新版分段逻辑) ---
    def _score_from_lcc(self, lcc: float) -> float:
        """
        根据低云覆盖率 (lcc, 0-1) 进行分段评分。
        - 0-10% (0.0-0.1): 1.0分 (最理想，不遮挡视线)
        - 10-30% (0.1-0.3): 0.6分 (有一定遮挡)
        - 30-50% (0.3-0.5): 0.1分 (严重遮挡)
        - > 50% (> 0.5): 0.0分 (完全遮挡)
        """
        if lcc <= 0.1:
            return 1.0
        elif 0.1 < lcc <= 0.3:
            return 0.6
        elif 0.3 < lcc <= 0.5:
            return 0.1
        else: # lcc > 0.5
            return 0.0

    # ==========================================================
    # --- 核心计算逻辑 (已更新为混合模型) ---
    # ==========================================================
    def calculate_for_point(
        self,
        lat: float,
        lon: float,
        utc_time: datetime,
        factors: List[str] = None # 默认值改为 None
    ) -> Dict[str, float]:
        """
        为单个点计算最终的火烧云指数及其所有分项得分。
        *** 新版本: 使用混合模型 (品质因子加权平均 * 基础因子乘积)。***
        """
        if factors is None:
            factors = self.ALL_FACTORS
        
        for factor in factors:
            if factor not in self.ALL_FACTORS:
                raise ValueError(f"无效的因子: '{factor}'. 可用因子为: {self.ALL_FACTORS}")

        local_hcc = self._get_value_at_point('hcc', lat, lon)
        if local_hcc < self.CLOUD_THRESHOLD:
            local_mcc = self._get_value_at_point('mcc', lat, lon)
            local_lcc = self._get_value_at_point('lcc', lat, lon)
            return {
                'final_score': 0.0, 'score_boundary': 0.0, 'score_hcc': 0.0,
                'score_mcc': self._score_from_mcc(local_mcc),
                'score_lcc': self._score_from_lcc(local_lcc)
            }

        sun_pos = self.astro_service.get_sun_position(lat, lon, utc_time)
        boundary_distance = self._find_cloud_boundary_distance(lat, lon, sun_pos['azimuth'])
        local_mcc = self._get_value_at_point('mcc', lat, lon) # 确保即使不在前提条件中也计算
        local_lcc = self._get_value_at_point('lcc', lat, lon)
        
        all_scores = {
            'score_boundary': self._score_from_boundary_distance(boundary_distance),
            'score_hcc': self._score_from_hcc(local_hcc),
            'score_mcc': self._score_from_mcc(local_mcc),
            'score_lcc': self._score_from_lcc(local_lcc)
        }

        # --- 混合模型计算 ---
        
        # a. 计算“品质”得分 (对 score_boundary 和 score_hcc 进行加权平均)
        quality_factors = ['score_boundary', 'score_hcc']
        total_quality_weight = 0
        weighted_quality_score_sum = 0
        for factor_name in quality_factors:
            if factor_name in factors and factor_name in self.weights:
                score = all_scores[factor_name]
                weight = self.weights[factor_name]
                weighted_quality_score_sum += score * weight
                total_quality_weight += weight
                
        quality_score = weighted_quality_score_sum / total_quality_weight if total_quality_weight > 0 else 0.0

        # b. 计算“基础/通行证”得分 (将 score_mcc 和 score_lcc 相乘)
        base_factors = ['score_mcc', 'score_lcc']
        base_score = 1.0
        for factor_name in base_factors:
            if factor_name in factors:
                base_score *= all_scores[factor_name]

        # c. 最终得分 = 品质分 * 基础分
        final_score = quality_score * base_score
        
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

    
    def _calculate_for_single_index(
        self, 
        ij_tuple: Tuple[int, int], 
        utc_time: datetime, 
        factors: List[str]
    ) -> Tuple[int, int, Dict[str, float]]:
        """
        这是一个为并行计算设计的工作单元。
        它接受一个索引元组 (i, j)，执行单点计算，并返回索引和结果。
        """
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
        """
        [并行版] 为网格中的活动区域计算火烧云指数。
        """
        if factors is None:
            factors = self.ALL_FACTORS
        logging.info(f"开始为网格活动区域并行计算指数，使用因子: {factors}")
        
        results_ds = xr.Dataset({
            'final_score': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
            'score_boundary': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
            'score_hcc': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
            'score_mcc': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
            'score_lcc': xr.full_like(self.weather_data['hcc'], 0.0, dtype=np.float32),
        })
        
        # 将要计算的索引转换为Python元组列表
        active_indices = [tuple(idx) for idx in np.argwhere(active_mask.values)]
        
        if not active_indices:
            logging.warning("活动区域为空，无需计算。")
            return results_ds
        
        # 设置并行工作进程数，默认为系统CPU核心数
        num_workers = os.cpu_count()
        logging.info(f"将使用 {num_workers} 个工作进程进行并行计算。")

        # 使用 functools.partial 预先填充不变的参数
        task_function = partial(self._calculate_for_single_index, utc_time=utc_time, factors=factors)

        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # 提交所有任务
            futures = [executor.submit(task_function, ij_tuple) for ij_tuple in active_indices]
            
            # 使用 tqdm 和 as_completed 来实时更新进度条
            progress_desc = f"Calculating Glow Index ({len(factors)} factors)"
            with tqdm(total=len(futures), desc=progress_desc) as pbar:
                for future in as_completed(futures):
                    try:
                        i, j, scores = future.result()
                        # 将计算结果填充回 Dataset
                        for score_name, value in scores.items():
                            if score_name in results_ds:
                                results_ds[score_name][i, j] = value
                    except Exception as e:
                        logging.error(f"一个并行任务失败: {e}", exc_info=False)
                    finally:
                        pbar.update(1) # 保证每次都更新进度条
        
        results_ds.attrs['factors_used'] = str(factors)
        results_ds.attrs['parallel_computation'] = 'True'
        
        logging.info("多因子网格并行计算完成。")
        return results_ds