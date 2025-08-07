# ChromaSky Toolkit

一个用于获取气象数据、处理数据并生成火烧云（晚霞）指数地图的 Python 工具包。

## 功能
- 从指定数据源获取气象数据。
- 计算火烧云指数。
- 生成可视化的地理热力图或标记图。

## 安装与使用

1. 克隆仓库
2. 创建并激活虚拟环境
   ```bash
   uv venv
   source .venv/bin/activate


计算火烧云指数

除了根据下面的计算
    def calculate_for_point(self, lat: float, lon: float, utc_time: datetime) -> float:
        """为单个点计算最终的火烧云指数。"""
        local_hcc = self._get_hcc_at_point(lat, lon)
        if local_hcc < self.CLOUD_THRESHOLD:
            return 0.0
        sun_pos = self.astro_service.get_sun_position(lat, lon, utc_time)
        boundary_distance = self._find_cloud_boundary_distance(lat, lon, sun_pos['azimuth'])
        return self._score_from_distance(boundary_distance)

        现在添加几个因子
        1. 高云在 50%最合适（可调），然后往两边递减
        2. 中云在 0%最合适，越高分数越低
        3. 低云在 0%最合适，越高分数越低
