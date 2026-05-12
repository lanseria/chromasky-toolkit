# XYZ 瓦片路径规则

## 概述

ChromaSky Toolkit 自动将综合火烧云指数叠加层切割为标准 XYZ 瓦片，可直接用于 MapLibre GL JS、Mapbox GL JS 等前端地图库。

瓦片仅包含指数叠加层（RGBA PNG，透明背景），需叠加在底图之上使用。

## 路径格式

```
{base}/{z}/{x}/{y}/{YYYYMMDD}-{event}.png
```

| 字段 | 说明 | 示例 |
|------|------|------|
| `base` | 瓦片根目录，由 `config.TILE_OUTPUT_DIR` 控制 | `./chroma-sky-tiles` |
| `z` | 缩放级别 (3 - 8) | `5` |
| `x` | X 瓦片坐标 | `22` |
| `y` | Y 瓦片坐标 | `13` |
| `YYYYMMDD` | 预报日期 | `20260512` |
| `event` | 事件类型 | `sunrise` 或 `sunset` |

### 示例路径

```
chroma-sky-tiles/5/22/13/20260512-sunset.png
chroma-sky-tiles/6/44/26/20260513-sunrise.png
```

## 瓦片规格

| 属性 | 值 |
|------|-----|
| 投影 | Web Mercator (EPSG:3857) |
| 切片方案 | XYZ (Google/OSM 标准) |
| 瓦片尺寸 | 256 × 256 像素 |
| 格式 | PNG (RGBA) |
| 缩放级别 | 3 - 8 |
| 透明度 | 无数据区域完全透明 (alpha = 0) |
| 覆盖范围 | 东经 70° - 135°，北纬 0° - 54° |

## 颜色映射

指数值从低到高对应颜色：

| 指数范围 | 颜色 | 含义 |
|----------|------|------|
| 0.0 | `#3b82f6` 蓝色 | 极低概率 |
| 0.5 | `#fde047` 黄色 | 中等概率 |
| 0.7 | `#f97316` 橙色 | 较高概率 |
| 0.85 | `#ef4444` 红色 | 高概率 |
| 1.0 | `#ec4899` 粉色 | 极高概率 |

## 前端接入示例

### MapLibre GL JS

```javascript
const date = '20260512';
const event = 'sunset'; // 'sunrise' 或 'sunset'
const tilesBase = 'http://your-server:8002/tiles'; // 替换为实际地址

const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: {
      'chromasky-tiles': {
        type: 'raster',
        tiles: [`${tilesBase}/{z}/{x}/{y}/${date}-${event}.png`],
        tileSize: 256,
        minzoom: 3,
        maxzoom: 8,
      },
    },
    layers: [
      {
        id: 'chromasky-layer',
        type: 'raster',
        source: 'chromasky-tiles',
        paint: {
          'raster-opacity': 0.7, // 调整叠加透明度
        },
      },
    ],
  },
  center: [105, 35],
  zoom: 4,
});
```

### Mapbox GL JS

```javascript
const date = '20260512';
const event = 'sunset';
const tilesBase = 'http://your-server:8002/tiles'; // 替换为实际地址

const map = new mapboxgl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: {
      'mapbox-streets': {
        type: 'vector',
        url: 'mapbox://mapbox.mapbox-streets-v8',
      },
      'chromasky-tiles': {
        type: 'raster',
        tiles: [`${tilesBase}/{z}/{x}/{y}/${date}-${event}.png`],
        tileSize: 256,
        minzoom: 3,
        maxzoom: 8,
      },
    },
    layers: [
      { id: 'streets', type: 'line', source: 'mapbox-streets', 'source-layer': 'road' },
      {
        id: 'chromasky-layer',
        type: 'raster',
        source: 'chromasky-tiles',
        paint: {
          'raster-opacity': 0.7,
        },
      },
    ],
  },
  center: [105, 35],
  zoom: 4,
});
```

## Docker 部署

瓦片目录通过 Docker 卷映射到宿主机，可在 `.env` 中配置路径：

```env
# .env
TILES_HOST_PATH=/data/tiles
```

映射后，宿主机路径 `/data/tiles` 即为瓦片根目录。可用 Nginx 等静态文件服务器直接对外提供瓦片：

```nginx
server {
    listen 80;
    server_name tiles.example.com;

    location /tiles/ {
        alias /data/tiles/;
        add_header Access-Control-Allow-Origin *;
        expires 6h;
    }
}
```

对应的 MapLibre tile URL 为：`https://tiles.example.com/tiles/{z}/{x}/{y}/20260512-sunset.png`

## 数据更新策略

| 场景 | 行为 |
|------|------|
| 同日 sunrise 瓦片 | 新生成时覆盖旧文件 |
| 同日 sunset 瓦片 | 新生成时覆盖旧文件 |
| 不同日期 | 独立存储，互不影响 |

定时任务每日自动更新：
- 0:00 UTC — 生成当日 sunrise + sunset
- 12:00 UTC — 更新当日 sunset（最新预报）+ 次日 sunrise

## 配置项

相关配置位于 `src/chromasky_toolkit/config.py`：

```python
TILE_OUTPUT_DIR: Path = PROJECT_ROOT.parent / "chroma-sky-tiles"  # 瓦片输出根目录
TILE_ZOOM_MIN: int = 3      # 最小缩放级别
TILE_ZOOM_MAX: int = 8      # 最大缩放级别
TILE_SIZE: int = 256         # 瓦片尺寸（像素）
```
