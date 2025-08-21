# src/chromasky_toolkit/config.py

import os
from pathlib import Path
from typing import Dict, List, Literal # <-- 确保导入 Literal
from dotenv import load_dotenv


# --- 1. 项目根目录 ---
# 这个是所有路径的基础，必须放在最前面
# Path(__file__) -> 当前文件路径 (config.py)
# .resolve() -> 获取绝对路径
# .parent.parent -> 从 src/chromasky_toolkit/ 向上跳两级到项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- 2. 加载环境变量 ---
dotenv_path = PROJECT_ROOT / '.env'
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path)
    # 第一次加载时打印信息，方便调试
    # print(f"✅ Config: .env 文件已从 {dotenv_path} 加载")
else:
    print(f"⚠️ Config: 未找到 .env 文件于 {dotenv_path}")

# --- 3. API 和密钥配置 ---
# 从环境变量中获取 CDS 配置
CDS_API_KEY: str | None = os.getenv("CDS_API_KEY")
CDS_API_URL: str = "https://ads.atmosphere.copernicus.eu/api" # CAMS API URL



# --- 4. 数据处理与下载配置 ---
# 定义两个地理范围:
# 1. DISPLAY_AREA: 最终在地图上展示的区域。
# 2. DOWNLOAD_AREA: 实际从服务器下载数据的区域，比展示区域更大，以确保边界计算的准确性。

# 展示范围 (覆盖中国大部分地区)
DISPLAY_AREA: Dict[str, float] = {
    "north": 54.00,
    "south": 0.00,
    "west": 70.00,
    "east": 135.00,
}

# 计算范围 (用户定义的核心关注区域)
CALCULATION_AREA: Dict[str, float] = {
    "north": 42.00,
    "south": 16.00,
    "west": 104.00,
    "east": 130.00,
}

# 下载范围 (在展示范围基础上，向四周各扩展15度作为缓冲区)
# 这个缓冲区对于精确计算边界区域的云边界距离至关重要
DOWNLOAD_AREA: Dict[str, float] = {
    "north": DISPLAY_AREA["north"] + 15.0, # 扩展到 69.0
    "south": DISPLAY_AREA["south"] - 15.0, # 扩展到 -15.0
    "west": DISPLAY_AREA["west"] - 15.0,   # 扩展到 55.0
    "east": DISPLAY_AREA["east"] + 15.0,   # 扩展到 150.0
}
# 对下载范围进行边界检查，确保纬度在[-90, 90]和经度在[-180, 180]或[0, 360]的有效范围内
DOWNLOAD_AREA["north"] = min(DOWNLOAD_AREA["north"], 90.0)
DOWNLOAD_AREA["south"] = max(DOWNLOAD_AREA["south"], -90.0)

# 本地时区
LOCAL_TZ: str = "Asia/Shanghai"

# --- 5. 时间配置 ---
# 关注的日出/日落时间段 (本地时间, 24小时制)
SUNRISE_EVENT_TIMES: List[str] = ["04:00", "05:00", "06:00", "07:00", "08:00"]
# SUNRISE_EVENT_TIMES: List[str] = ["05:00"]
SUNSET_EVENT_TIMES: List[str] = ["18:00", "19:00", "20:00", "21:00"]
# SUNSET_EVENT_TIMES: List[str] = ["19:00"]

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
DATA_DIR: Path = PROJECT_ROOT / "data"
MAP_DATA_DIR: Path = PROJECT_ROOT / "map_data"
OUTPUTS_DIR: Path = PROJECT_ROOT / "outputs"

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
FIGURE_OUTPUTS_DIR: Path = OUTPUTS_DIR / "figures"
CALCULATION_OUTPUTS_DIR: Path = OUTPUTS_DIR / "calculations" # 用于存放计算结果
# 6.5 outputs 目录下的子目录
FONT_DIR: Path = PROJECT_ROOT / "fonts"  # 存放下载的字体文件
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