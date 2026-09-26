# src/chromasky_toolkit/config.py

import os
from pathlib import Path
from typing import Dict, List, Literal
from datetime import datetime
from dotenv import load_dotenv


# --- 1. 项目根目录 ---
# 这个是所有路径的基础，必须放在最前面
# Path(__file__) -> 当前文件路径 (config.py)
# .resolve() -> 获取绝对路径
# .parent.parent -> 从 src/chromasky_toolkit/ 向上跳两级到项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# --- 新增: 定义一个用于日志输出的顶级项目路径 ---
# PROJECT_ROOT 指向 /app/src, 而这个指向 /app
LOG_BASE_PATH: Path = PROJECT_ROOT.parent


# --- 2. 加载环境变量 ---
# 优先加载项目根目录的 .env（与 docker-compose 的 env_file、.env.example 文档一致），
# 回退到 src/ 下的 .env（兼容旧布局）；进程环境中已存在的变量优先，不会被覆盖
_root_env_path = PROJECT_ROOT.parent / '.env'
_src_env_path = PROJECT_ROOT / '.env'
dotenv_path = _root_env_path if _root_env_path.exists() else _src_env_path
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
    # 第一次加载时打印信息，方便调试
    # print(f"✅ Config: .env 文件已从 {dotenv_path} 加载")
else:
    print(f"⚠️ Config: 未找到 .env 文件于 {_root_env_path} 或 {_src_env_path}")

# --- 3. API 和密钥配置 ---
# 从环境变量中获取 CDS 配置
CDS_API_KEY: str | None = os.getenv("CDS_API_KEY")
CDS_API_URL: str = "https://ads.atmosphere.copernicus.eu/api" # CAMS API URL



# --- 4. 数据处理与下载配置 ---
# 地理范围三级结构，逐级向外扩展，所有边界均支持环境变量(.env)精细覆盖:
#
#   DISPLAY_AREA     展示范围: 地图图幅与 XYZ 瓦片的覆盖范围（最终用户可见区域）
#   CALCULATION_AREA 计算范围: 火烧云指数实际计算的格点范围。
#                    默认 = 展示范围四周外扩 CALC_MARGIN_DEGREES，
#                    以抵消高斯平滑在数据边缘的收缩，保证图幅边缘渲染完整。
#   DOWNLOAD_AREA    下载范围: 向服务器下载数据的范围 = 计算范围四周外扩
#                    DOWNLOAD_BUFFER_DEGREES。缓冲区对于精确计算边界区域的
#                    云边界距离至关重要。
#
# 默认值依据 map_data 中的国界数据实测边界确定:
#   中国陆地及南海诸岛: 西 73.5°E / 南 3.8°N / 东 135.1°E / 北 53.6°N
#   九段线最南端约 3.4°N


def _env_float(name: str, default: float) -> float:
    """从环境变量读取浮点数边界值，未设置或非法时返回默认值。"""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"⚠️ Config: 环境变量 {name}={raw!r} 不是合法数字，已忽略并使用默认值 {default}。")
        return default


def _validate_area(area: Dict[str, float], name: str) -> None:
    """校验区域字典的南北/东西关系，配置错误时立即报错，避免生成残缺地图。"""
    if not area["north"] > area["south"]:
        raise ValueError(f"Config: {name} 的 north({area['north']}) 必须大于 south({area['south']})")
    if not area["east"] > area["west"]:
        raise ValueError(f"Config: {name} 的 east({area['east']}) 必须大于 west({area['west']})")


# 4.1 展示范围（地图图幅）：默认完整覆盖整个中国大陆及南海诸岛（含九段线）
DISPLAY_AREA: Dict[str, float] = {
    "north": _env_float("DISPLAY_NORTH", 54.0),
    "south": _env_float("DISPLAY_SOUTH", 2.0),
    "west": _env_float("DISPLAY_WEST", 72.0),
    "east": _env_float("DISPLAY_EAST", 136.0),
}
_validate_area(DISPLAY_AREA, "DISPLAY_AREA")

# 4.2 计算范围：默认在展示范围基础上四周外扩（渲染边缘缓冲）
# 如需仅关注某个区域（如只算华南），可通过 CALC_* 环境变量单独收缩，
# 但注意收缩后图幅对应区域将没有指数数据
CALC_MARGIN_DEGREES: float = max(0.0, _env_float("CALC_MARGIN_DEGREES", 1.0))
CALCULATION_AREA: Dict[str, float] = {
    "north": _env_float("CALC_NORTH", DISPLAY_AREA["north"] + CALC_MARGIN_DEGREES),
    "south": _env_float("CALC_SOUTH", DISPLAY_AREA["south"] - CALC_MARGIN_DEGREES),
    "west": _env_float("CALC_WEST", DISPLAY_AREA["west"] - CALC_MARGIN_DEGREES),
    "east": _env_float("CALC_EAST", DISPLAY_AREA["east"] + CALC_MARGIN_DEGREES),
}
_validate_area(CALCULATION_AREA, "CALCULATION_AREA")

# 4.3 下载范围（在计算范围基础上，向四周各扩展缓冲区）
DOWNLOAD_BUFFER_DEGREES: float = _env_float("DOWNLOAD_BUFFER_DEGREES", 15.0)
DOWNLOAD_AREA: Dict[str, float] = {
    "north": CALCULATION_AREA["north"] + DOWNLOAD_BUFFER_DEGREES,
    "south": CALCULATION_AREA["south"] - DOWNLOAD_BUFFER_DEGREES,
    "west": CALCULATION_AREA["west"] - DOWNLOAD_BUFFER_DEGREES,
    "east": CALCULATION_AREA["east"] + DOWNLOAD_BUFFER_DEGREES,
}
# 对下载范围进行边界检查，确保纬度在[-90, 90]和经度在[-180, 180]的有效范围内
DOWNLOAD_AREA["north"] = min(DOWNLOAD_AREA["north"], 90.0)
DOWNLOAD_AREA["south"] = max(DOWNLOAD_AREA["south"], -90.0)
DOWNLOAD_AREA["west"] = max(DOWNLOAD_AREA["west"], -180.0)
DOWNLOAD_AREA["east"] = min(DOWNLOAD_AREA["east"], 180.0)
_validate_area(DOWNLOAD_AREA, "DOWNLOAD_AREA")


def _format_area(area: Dict[str, float]) -> str:
    return f"西{area['west']:.1f}°E 东{area['east']:.1f}°E, 南{area['south']:.1f}°N 北{area['north']:.1f}°N"


print(
    "✅ Config: 地理范围已加载:\n"
    f"  展示范围(DISPLAY): {_format_area(DISPLAY_AREA)}\n"
    f"  计算范围(CALCULATION): {_format_area(CALCULATION_AREA)}\n"
    f"  下载范围(DOWNLOAD): {_format_area(DOWNLOAD_AREA)}\n"
    "  (可通过环境变量 DISPLAY_*/CALC_*/CALC_MARGIN_DEGREES/DOWNLOAD_BUFFER_DEGREES 覆盖)"
)

# 本地时区
LOCAL_TZ: str = "Asia/Shanghai"

# --- 5. 时间配置 (根据季节动态调整) ---

# 5.1 为不同季节预设时间列表
# 北半球季节定义: 冬季 (12, 1, 2月), 夏季 (6, 7, 8月), 春秋季 (其他月份)
_SUNRISE_TIMES_WINTER: List[str] = ["06:00", "07:00", "08:00", "09:00"]
_SUNSET_TIMES_WINTER:  List[str] = ["17:00", "18:00", "19:00", "20:00"]

_SUNRISE_TIMES_SUMMER: List[str] = ["04:00", "05:00", "06:00", "07:00"]
_SUNSET_TIMES_SUMMER:  List[str] = ["19:00", "20:00", "21:00", "22:00"]

_SUNRISE_TIMES_EQUINOX: List[str] = ["05:00", "06:00", "07:00", "08:00"]
_SUNSET_TIMES_EQUINOX:  List[str] = ["18:00", "19:00", "20:00", "21:00"]


# 5.2 根据当前月份自动选择时间配置
current_month = datetime.now().month

if current_month in [11, 12, 1, 2]:
    season = "冬季"
    SUNRISE_EVENT_TIMES: List[str] = _SUNRISE_TIMES_WINTER
    SUNSET_EVENT_TIMES: List[str] = _SUNSET_TIMES_WINTER
elif current_month in [5, 6, 7, 8]:
    season = "夏季"
    SUNRISE_EVENT_TIMES: List[str] = _SUNRISE_TIMES_SUMMER
    SUNSET_EVENT_TIMES: List[str] = _SUNSET_TIMES_SUMMER
else:
    season = "春秋季"
    SUNRISE_EVENT_TIMES: List[str] = _SUNRISE_TIMES_EQUINOX
    SUNSET_EVENT_TIMES: List[str] = _SUNSET_TIMES_EQUINOX

# 在加载配置时打印信息，方便调试
print(f"✅ Config: 当前为 {season}, 已自动选择对应的日出/日落时间段。")

# --- 未来事件处理意图配置 ---
# 定义您想处理的未来事件列表。
# 可用选项: 'today_sunrise', 'today_sunset', 'tomorrow_sunrise', 'tomorrow_sunset'
FUTURE_TARGET_EVENT_INTENTIONS: List[Literal['today_sunrise', 'today_sunset', 'tomorrow_sunrise', 'tomorrow_sunset']] = [
    "today_sunset",
    "tomorrow_sunrise",
]

# --- 6. 项目核心文件路径配置 ---
# 这是一个非常好的实践，将所有路径常量化

# 6.1 顶级数据目录
DATA_DIR: Path = PROJECT_ROOT.parent / "data"          # 原来是 PROJECT_ROOT / "data"
MAP_DATA_DIR: Path = PROJECT_ROOT.parent / "map_data"    # 原来是 PROJECT_ROOT / "map_data"
OUTPUTS_DIR: Path = PROJECT_ROOT.parent / "outputs"      # 原来是 PROJECT_ROOT / "outputs"
FONT_DIR: Path = PROJECT_ROOT.parent / "fonts"         # 原来是 PROJECT_ROOT / "fonts"

# 6.2 data 目录下的子目录
RAW_DATA_DIR: Path = DATA_DIR / "raw"
PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"
# 为不同数据源定义更具体的路径
ERA5_DATA_DIR: Path = RAW_DATA_DIR / "era5"
GFS_DATA_DIR: Path = RAW_DATA_DIR / "gfs"
CAMS_AOD_DATA_DIR: Path = RAW_DATA_DIR / "cams_aod" # CAMS AOD 数据目录

# 6.3 map_data 目录下的具体文件 (示例)
# 这样在代码中就可以直接使用 config.CHINA_SHP_PATH
CHINA_SHP_PATH: Path = MAP_DATA_DIR / "china.shp"
NINE_DASH_LINE_SHP_PATH: Path = MAP_DATA_DIR / "china_nine_dotted_line.shp"
CITIES_CSV_PATH: Path = MAP_DATA_DIR / "china_cities.csv"

# 6.4 outputs 目录下的子目录
MAP_OUTPUTS_DIR: Path = OUTPUTS_DIR / "maps"
MAP_WEBP_OUTPUTS_DIR: Path = OUTPUTS_DIR / "maps_webp"
FIGURE_OUTPUTS_DIR: Path = OUTPUTS_DIR / "figures"
CALCULATION_OUTPUTS_DIR: Path = OUTPUTS_DIR / "calculations" # 用于存放计算结果

# --- 7. 绘图样式配置 (可选，但推荐) ---
# 将颜色、字体等也放入配置，方便统一修改风格
MAP_FONT_NAME: str = "LXGW WenKai" # 我们要使用的字体名称
MAP_FONT_FILENAME: str = "LXGWWenKai-Regular.ttf" # 字体对应的文件名
CHROMA_SKY_COLORS: List[str] = ["#3b82f6", "#fde047", "#f97316", "#ef4444", "#ec4899"]
CHROMA_SKY_COLOR_NODES: List[float] = [0.0, 0.5, 0.7, 0.85, 1.0]

# --- 8. GFS 预报数据配置 ---
GFS_BASE_URL: str = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
GFS_VARS_LIST: List[str] =  ['hcc', 'mcc', 'lcc']

# --- 9. CAMS AOD 预报数据配置 ---
CAMS_DATASET_NAME: str = 'cams-global-atmospheric-composition-forecasts'
CAMS_VARS_MAP: Dict[str, str] = {
    'aod550': 'total_aerosol_optical_depth_550nm',
}

# --- 10. 计算参数配置 ---
# 定义在天文事件（日出/日落）前后多长时间的窗口内进行计算
EVENT_WINDOW_MINUTES: int = 30

# 并行工作进程数，默认使用一半 CPU 核心（生产环境友好）
# 开发环境可在 .env 中设为 cpu_count() 的值以顶满性能
NUM_WORKERS: int = int(os.getenv("NUM_WORKERS", max(1, (os.cpu_count() or 1) // 2)))

# --- 11. XYZ 瓦片配置 ---
TILE_OUTPUT_DIR: Path = PROJECT_ROOT.parent / "chroma-sky-tiles"
TILE_MANIFEST_PATH: Path = TILE_OUTPUT_DIR / "tiles_manifest.json"
TILE_ZOOM_MIN: int = 3
TILE_ZOOM_MAX: int = 8
TILE_SIZE: int = 256