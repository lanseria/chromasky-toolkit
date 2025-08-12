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
```

```
python -m src.chromasky_toolkit.main --acquire-only
python -m src.chromasky_toolkit.main --visualize-inputs
python -m src.chromasky_toolkit.main --calculate-only
python -m src.chromasky_toolkit.main --draw-only
python -m src.chromasky_toolkit.main
```


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
        1. 高云在 40-80%最合适1.0分，然后50-80% 0.7分，10-40% 0.6分，0-10% 0.1分
        2. 中云在 20-50%最合适1.0分，50-80% 0.7分 80-100% 0.3分 0-20% 0.2分
        3. 低云在 0-10%最合适1.0分，10-30% 0.6分，大于50% 0分


示例评分逻辑（0-100分制）：
高层云覆盖率 (High Cloud Cover) - 权重：0.4 (最高)
0-10%: 10分
10-40%: 60分
40-80%: 100分 (最佳范围)
80-100%: 70分
中层云覆盖率 (Mid Cloud Cover) - 权重：0.25
0-20%: 20分
20-50%: 100分 (最佳范围)
50-80%: 70分
80-100%: 30分
低层云覆盖率 (Low Cloud Cover) - 权重：-0.5 (惩罚项)
这个分数应该是负的，或者用100减去它。低云越多，指数越低。
0-10%: 100分 (几乎没有遮挡)
10-30%: 60分
30-50%: 20分
50%: 0分 (基本没戏)
相对湿度 (Relative Humidity) - 权重：0.1
< 70%: 100分 (空气通透)
70-85%: 70分
85%: 40分 (可能雾蒙蒙)
降水概率 (Precipitation Probability) - 权重：-0.2 (惩罚项)
0%: 100分
1-10%: 80分
10-30%: 40分
30%: 0分 (下雨天基本看不到)