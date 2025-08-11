# src/chromasky_toolkit/main.py

import argparse
import logging

from . import data_acquisition
from . import processing
from . import mapping

# --- 设置基础日志 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ChromaSkyToolkit")

def main():
    """
    主函数，解析命令行参数并执行相应流程。
    """
    parser = argparse.ArgumentParser(
        description="ChromaSky Toolkit: 获取、处理并生成火烧云指数地图的工具。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # --- 定义流程控制参数 ---
    parser.add_argument(
        '--acquire-only',
        action='store_true',
        help="仅执行数据获取和预处理(下载 GFS/AOD 并分析成 .nc 文件)。"
    )
    parser.add_argument(
        '--calculate-only',
        action='store_true',
        help="仅执行火烧云指数计算 (需要已获取的数据)。"
    )
    parser.add_argument(
        '--draw-only',
        action='store_true',
        help="仅执行地图绘制 (需要已计算的指数结果)。"
    )

    args = parser.parse_args()
    
    run_acquire = args.acquire_only
    run_calculate = args.calculate_only
    run_draw = args.draw_only

    if not any([run_acquire, run_calculate, run_draw]):
        logger.info("未指定特定步骤，将执行完整流程: 获取 -> 计算 -> 绘制")
        run_acquire, run_calculate, run_draw = True, True, True

    logger.info("=" * 60)
    logger.info("====== 开始执行 ChromaSky Toolkit 流程 ======")
    logger.info("=" * 60)

    if run_acquire:
        try:
            data_acquisition.run_acquisition()
        except Exception as e:
            logger.error(f"❌ 在数据获取阶段发生严重错误: {e}", exc_info=True)
            if not any([args.calculate_only, args.draw_only]): return

    # --- 2. 指数计算 (Calculation) ---
    if run_calculate:
        logger.info("=" * 25 + " 指数计算 " + "=" * 25)
        # 替换占位符为实际调用
        try:
            processing.run_calculation()
        except Exception as e:
            logger.error(f"❌ 在指数计算阶段发生严重错误: {e}", exc_info=True)
            # 如果是完整流程，在关键步骤失败后应终止
            if not any([args.acquire_only, args.draw_only]): return

    # --- 3. 地图绘制 (Drawing) ---
    if run_draw:
        logger.info("=" * 25 + " 地图绘制 " + "=" * 25)
        # 替换占位符为实际调用
        try:
            mapping.run_drawing()
        except Exception as e:
            logger.error(f"❌ 在地图绘制阶段发生严重错误: {e}", exc_info=True)


    logger.info("\n" + "=" * 60)
    logger.info("====== ChromaSky Toolkit 流程执行完毕！ ======")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()