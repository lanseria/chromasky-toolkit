# src/chromasky_toolkit/main.py

import argparse
import logging

from . import data_acquisition
# from . import processing  # 暂时注释，因为还未实现
# from . import mapping     # 暂时注释，因为还未实现

# --- 设置基础日志 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ChromaSkyToolkit")

def run_pipeline(source: str, target_date: str, data_type: str = 'past'):
    """
    运行完整的数据处理和地图生成流程。
    """
    logger.info("====== 开始执行 ChromaSky Toolkit 流程 ======")

    # 1. 获取数据
    logger.info(f"步骤 1: 获取原始数据...")
    raw_data_path = data_acquisition.fetch_weather_data(
        source=source, 
        data_type=data_type, 
        target_date_str=target_date
    )

    if not raw_data_path:
        logger.error("数据获取失败，流程终止。")
        return

    logger.info(f"✅ 数据获取成功，文件位于: {raw_data_path}")

    # 2. 处理数据并计算指数 (待实现)
    logger.info("步骤 2: 处理数据并计算火烧云指数... (待实现)")
    # processed_data = processing.calculate_glow_index(raw_data_path)
    # if not processed_data:
    #     logger.error("数据处理失败，流程终止。")
    #     return

    # 3. 生成地图 (待实现)
    logger.info("步骤 3: 生成火烧云指数地图... (待实现)")
    # map_path = mapping.create_index_map(processed_data, "outputs/maps/...")
    # if not map_path:
    #     logger.error("地图生成失败。")
    # else:
    #     logger.info(f"✅ 地图已保存至: {map_path}")

    logger.info("====== 流程执行完毕！ ======")

if __name__ == "__main__":
    # --- 设置命令行参数解析 ---
    parser = argparse.ArgumentParser(
        description="ChromaSky Toolkit: 一个获取、处理并生成火烧云指数地图的工具。"
    )
    
    parser.add_argument(
        "date", 
        type=str, 
        help="目标日期，格式为 YYYYMMDD (例如: 20231001)。"
    )
    
    parser.add_argument(
        "--source", 
        type=str, 
        default="ecmwf", 
        choices=["ecmwf", "gfs"],
        help="数据源 (默认: ecmwf)。"
    )

    parser.add_argument(
        "--type", 
        dest='data_type', # 使用 dest 避免与内置的 type 关键字冲突
        type=str, 
        default="past", 
        choices=["past", "future"],
        help="数据类型，是历史数据还是预报数据 (默认: past)。"
    )

    args = parser.parse_args()

    # --- 启动流程 ---
    run_pipeline(source=args.source, target_date=args.date, data_type=args.data_type)