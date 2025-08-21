# tools/setup_map_data.py

import logging
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# 确保能正确导入项目配置
try:
    from chromasky_toolkit import config
except ImportError:
    # 如果作为独立脚本运行，可能需要调整 Python 路径
    import sys
    # 将 src 目录添加到路径中
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
    from chromasky_toolkit import config

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("DataSetup")

# --- 地图数据配置 ---
MAP_DATA_URL = "https://ghfast.top/https://github.com/Supeset/China-GeoData/archive/refs/heads/master.zip"
MAP_ZIP_FILENAME = "china-geodata.zip"

# --- 字体数据配置 ---
FONT_BASE_URL = "https://ghfast.top/https://github.com/lxgw/LxgwWenKai/raw/main/fonts/TTF/"
FONT_FILENAMES = [
    "LXGWWenKai-Light.ttf",
    "LXGWWenKai-Medium.ttf",
    "LXGWWenKai-Regular.ttf",
    "LXGWWenKaiMono-Light.ttf",
    "LXGWWenKaiMono-Medium.ttf",
    "LXGWWenKaiMono-Regular.ttf"
]
FONT_TARGET_DIR = config.FONT_DIR


def setup_font_data():
    """
    自动下载并设置绘图所需的“霞鹜文楷”字体。
    该脚本是幂等的：如果所需字体文件已存在，再次运行不会产生副作用。
    """
    logger.info("===== 开始下载和设置字体文件 =====")

    # 1. 确保目标目录存在
    FONT_TARGET_DIR.mkdir(exist_ok=True)
    logger.info(f"字体文件将被安装到: {FONT_TARGET_DIR.resolve()}")

    # 2. 检查是否已存在所有必要文件，实现幂等性
    if all((FONT_TARGET_DIR / f).exists() for f in FONT_FILENAMES):
        logger.info("✅ 检测到所有必需的字体文件均已存在。设置完成，跳过下载。")
        logger.info("===== 字体文件设置完成！ =====")
        return

    # 3. 循环下载所有字体文件
    files_downloaded = 0
    for filename in FONT_FILENAMES:
        target_path = FONT_TARGET_DIR / filename
        if target_path.exists():
            logger.info(f"  - 字体 '{filename}' 已存在，跳过。")
            continue

        download_url = FONT_BASE_URL + filename
        try:
            logger.info(f"  - 正在从 {download_url} 下载字体...")
            urllib.request.urlretrieve(download_url, target_path)
            logger.info(f"    > 字体已成功保存到: {target_path}")
            files_downloaded += 1
        except Exception as e:
            logger.error(f"    > 下载字体 '{filename}' 失败: {e}")

    if files_downloaded > 0:
        logger.info(f"✅ 成功下载 {files_downloaded} 个新的字体文件。")
    else:
        logger.warning("本次运行没有下载任何新的字体文件。")

    logger.info("===== 字体文件设置完成！ =====")


def setup_map_data():
    """
    自动下载并设置中国地图 shapefile 和城市数据。
    该脚本是幂等的：如果所需文件已存在，再次运行不会产生副作用。
    """
    logger.info("===== 开始下载和设置地图数据 =====")
    TARGET_DIR = config.MAP_DATA_DIR

    # 1. 确保目标目录存在
    TARGET_DIR.mkdir(exist_ok=True)
    logger.info(f"地图数据将被安装到: {TARGET_DIR.resolve()}")

    # 2. 检查是否已存在所有必要文件
    required_files = [
        config.CHINA_SHP_PATH,
        config.NINE_DASH_LINE_SHP_PATH,
        config.CITIES_CSV_PATH
    ]
    if all(f.exists() for f in required_files):
        logger.info("✅ 检测到所有必需的 Shapefile 和城市数据文件均已存在。设置完成，跳过下载。")
        logger.info("===== 地图数据设置完成！ =====")
        return

    # 3. 使用临时目录进行下载和解压
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        zip_path = tmp_path / MAP_ZIP_FILENAME

        # 4. 下载ZIP文件
        try:
            logger.info(f"正在从 {MAP_DATA_URL} 下载数据...")
            urllib.request.urlretrieve(MAP_DATA_URL, zip_path)
            logger.info(f"数据已成功下载到临时文件: {zip_path}")
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return

        # 5. 解压ZIP文件
        extract_path = tmp_path / "extracted_data"
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_path)
            logger.info(f"文件已成功解压到临时目录: {extract_path}")
        except Exception as e:
            logger.error(f"解压失败: {e}")
            return

        # 6. 找到并移动所需文件
        repo_root_dir = next(extract_path.glob("China-GeoData-*"), None)
        if not repo_root_dir or not repo_root_dir.is_dir():
            logger.error("在解压目录中未找到预期的 'China-GeoData-*' 文件夹。")
            return

        source_shp_dir = repo_root_dir / "shp"
        source_csv_dir = repo_root_dir / "csv"
        
        files_moved = 0
        if source_shp_dir.exists():
            for file_path in source_shp_dir.glob("*"):
                shutil.move(str(file_path), str(TARGET_DIR / file_path.name))
                files_moved += 1
        
        cities_csv_source = source_csv_dir / "china_cities.csv"
        if cities_csv_source.exists():
            shutil.move(str(cities_csv_source), str(TARGET_DIR / cities_csv_source.name))
            files_moved += 1

        if files_moved > 0:
            logger.info(f"✅ 成功移动 {files_moved} 个地图和数据文件。")

    logger.info("===== 地图数据设置完成！ =====")


if __name__ == "__main__":
    setup_map_data()
    setup_font_data()