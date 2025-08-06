import logging
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("MapDataSetup")

# --- 配置 ---
# 这个 GitHub 仓库包含了中国省、市、县级的 Shapefile 文件
DATA_URL = "https://github.com/dongli/china-shapefiles/archive/refs/heads/master.zip"

# 确定项目根目录 (此脚本位于 tools/ 下，所以根目录是上一级目录)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 定义最终存放地图数据的目录
TARGET_DIR = PROJECT_ROOT / "map_data"


def setup_map_data():
    """
    自动下载并设置中国地图 shapefile 数据。
    该脚本是幂等的：如果数据已存在，再次运行不会产生副作用。
    """
    logger.info("===== 开始下载和设置地图数据 =====")

    # 1. 确保目标目录存在
    TARGET_DIR.mkdir(exist_ok=True)
    logger.info(f"地图数据将被安装到: {TARGET_DIR.resolve()}")

    # 检查是否已存在必要文件，如果存在则跳过，实现幂等性
    if any(TARGET_DIR.glob("*.shp")):
        logger.info("✅ 检测到已存在 Shapefile 文件，设置完成。跳过下载。")
        logger.info("===== 地图数据设置完成！ =====")
        return

    # 2. 使用临时目录进行下载和解压，保持项目目录干净
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        zip_path = tmp_path / "china-shapefiles.zip"

        # 3. 下载ZIP文件
        try:
            logger.info(f"正在从 {DATA_URL} 下载数据...")
            urllib.request.urlretrieve(DATA_URL, zip_path)
            logger.info(f"数据已成功下载到临时文件: {zip_path}")
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return

        # 4. 解压ZIP文件
        extract_path = tmp_path / "extracted_data"
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_path)
            logger.info(f"文件已成功解压到临时目录: {extract_path}")
        except Exception as e:
            logger.error(f"解压失败: {e}")
            return

        # 5. 找到源 shapefiles 目录
        # 解压后的顶层目录名通常是 "china-shapefiles-master"
        source_shapefiles_dir = next(extract_path.glob("china-shapefiles-*/shapefiles"), None)
        if not source_shapefiles_dir or not source_shapefiles_dir.exists():
            logger.error("在解压目录中未找到预期的 'shapefiles' 文件夹。")
            logger.error(f"请检查解压后的结构: {list(extract_path.glob('*/*'))}")
            return

        # 6. 将所有文件从源目录移动到最终目标目录
        logger.info(f"正在从 {source_shapefiles_dir} 移动文件到 {TARGET_DIR}...")
        files_moved = 0
        for file_path in source_shapefiles_dir.glob("*"):
            if file_path.is_file():
                destination_path = TARGET_DIR / file_path.name
                shutil.move(str(file_path), str(destination_path))
                logger.debug(f"  > 已移动: {file_path.name}")
                files_moved += 1
        
        if files_moved > 0:
            logger.info(f"✅ 成功移动 {files_moved} 个地图文件。")
        else:
            logger.warning("在源目录中没有找到可移动的文件。")

    logger.info("===== 地图数据设置完成！ =====")


if __name__ == "__main__":
    setup_map_data()