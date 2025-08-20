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
logger = logging.getLogger("MapDataSetup")

# --- 新配置 ---
# 新的数据源仓库
DATA_URL = "https://github.com/Supeset/China-GeoData/archive/refs/heads/master.zip"
ZIP_FILENAME = "china-geodata.zip"

# 定义最终存放地图数据的目录
TARGET_DIR = config.MAP_DATA_DIR


def setup_map_data():
    """
    自动下载并设置中国地图 shapefile 和城市数据。
    该脚本是幂等的：如果所需文件已存在，再次运行不会产生副作用。
    """
    logger.info("===== 开始下载和设置地图数据 (新数据源) =====")

    # 1. 确保目标目录存在
    TARGET_DIR.mkdir(exist_ok=True)
    logger.info(f"地图数据将被安装到: {TARGET_DIR.resolve()}")

    # 2. 检查是否已存在所有必要文件，实现幂等性
    # 我们需要 shapefile 和 城市CSV文件
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
        zip_path = tmp_path / ZIP_FILENAME

        # 4. 下载ZIP文件
        try:
            logger.info(f"正在从 {DATA_URL} 下载数据...")
            urllib.request.urlretrieve(DATA_URL, zip_path)
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

        # 6. 找到解压后的根目录和源数据目录
        # 解压后的顶层目录名通常是 "China-GeoData-master"
        repo_root_dir = next(extract_path.glob("China-GeoData-*"), None)
        if not repo_root_dir or not repo_root_dir.is_dir():
            logger.error("在解压目录中未找到预期的 'China-GeoData-*' 文件夹。")
            return

        source_shp_dir = repo_root_dir / "shp"
        source_csv_dir = repo_root_dir / "csv"

        if not source_shp_dir.exists() or not source_csv_dir.exists():
            logger.error(f"在 {repo_root_dir} 中未找到 'shp' 或 'csv' 文件夹。")
            return

        files_moved = 0
        
        # 7. 移动 `shp` 目录下的所有文件
        logger.info(f"正在从 {source_shp_dir} 移动 Shapefile 文件...")
        for file_path in source_shp_dir.glob("*"):
            if file_path.is_file():
                destination_path = TARGET_DIR / file_path.name
                shutil.move(str(file_path), str(destination_path))
                logger.debug(f"  > 已移动: {file_path.name}")
                files_moved += 1
        
        # 8. 移动 `csv` 目录下的 `china_cities.csv` 文件
        logger.info(f"正在从 {source_csv_dir} 移动城市数据文件...")
        cities_csv_source = source_csv_dir / "china_cities.csv"
        if cities_csv_source.exists():
            destination_path = TARGET_DIR / cities_csv_source.name
            shutil.move(str(cities_csv_source), str(destination_path))
            logger.debug(f"  > 已移动: {cities_csv_source.name}")
            files_moved += 1
        else:
            logger.warning(f"在 {source_csv_dir} 中未找到 'china_cities.csv' 文件。")

        if files_moved > 0:
            logger.info(f"✅ 成功移动 {files_moved} 个地图和数据文件。")
        else:
            logger.warning("在源目录中没有找到可移动的文件。")

    logger.info("===== 地图数据设置完成！ =====")


if __name__ == "__main__":
    setup_map_data()