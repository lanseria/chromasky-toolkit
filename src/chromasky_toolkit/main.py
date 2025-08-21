# src/chromasky_toolkit/main.py

import argparse
import logging

# --- 设置基础日志 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ChromaSkyToolkit")

def run_full_workflow():
    """
    执行完整的 "获取 -> 计算 -> 绘制" 工作流。
    这个函数现在是可复用的，可以被其他模块调用。
    """
    logger.info("=" * 25 + " 1. 数据获取 " + "=" * 25)
    from . import data_acquisition
    data_acquisition.run_acquisition()

    logger.info("=" * 25 + " 2. 指数计算 " + "=" * 25)
    from . import processing
    processing.run_calculation()

    logger.info("=" * 25 + " 3. 地图绘制 " + "=" * 25)
    from . import mapping
    mapping.run_drawing()

    logger.info("=" * 25 + " 4. 图片格式转换 (WebP) " + "=" * 25)
    from . import image_converter
    image_converter.run_conversion()


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
        '--visualize-inputs',
        action='store_true',
        help="仅绘制预处理后的输入数据图 (高/中/低云, AOD)，用于调试。"
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
    # --- 新增参数 ---
    parser.add_argument(
        '--convert-webp',
        action='store_true',
        help="将 `outputs/maps` 中的 PNG 图片转换为 WebP 格式，并存入 `outputs/maps_webp`。"
    )

    args = parser.parse_args()
    
    run_acquire = args.acquire_only
    run_visualize = args.visualize_inputs
    run_calculate = args.calculate_only
    run_draw = args.draw_only
    run_convert = args.convert_webp # 新增

    # 如果没有指定任何 --xxx-only 或 --visualize-inputs/--convert-webp 参数，则执行完整流程
    if not any([run_acquire, run_visualize, run_calculate, run_draw, run_convert]):
        logger.info("未指定特定步骤，将执行完整流程: 获取 -> 计算 -> 绘制")
        run_acquire, run_calculate, run_draw = True, True, True
    else:
        # 如果指定了 --visualize-inputs 或 --convert-webp，则它们是独立操作
        if run_visualize or run_convert:
            run_acquire, run_calculate, run_draw = False, False, False

    logger.info("=" * 60)
    logger.info("====== 开始执行 ChromaSky Toolkit 流程 ======")
    logger.info("=" * 60)

    if run_acquire:
        try:
            from . import data_acquisition
            data_acquisition.run_acquisition()
        except Exception as e:
            logger.error(f"❌ 在数据获取阶段发生严重错误: {e}", exc_info=True)
            if not any([args.calculate_only, args.draw_only]): return

    if run_visualize:
        logger.info("\n" + "=" * 25 + " 绘制输入数据图 " + "=" * 25)
        try:
            from . import input_visualizer
            input_visualizer.run_input_visualization()
        except Exception as e:
            logger.error(f"❌ 在绘制输入数据图阶段发生严重错误: {e}", exc_info=True)
    
    if run_calculate:
        logger.info("\n" + "=" * 25 + " 指数计算 " + "=" * 25)
        try:
            from . import processing
            processing.run_calculation()
        except Exception as e:
            logger.error(f"❌ 在指数计算阶段发生严重错误: {e}", exc_info=True)
            if not any([args.acquire_only, args.draw_only]): return

    if run_draw:
        logger.info("\n" + "=" * 25 + " 地图绘制 " + "=" * 25)
        try:
            from . import mapping
            mapping.run_drawing()
        except Exception as e:
            logger.error(f"❌ 在地图绘制阶段发生严重错误: {e}", exc_info=True)

    # --- 新增的转换流程 ---
    if run_convert:
        logger.info("\n" + "=" * 25 + " 格式转换 (WebP) " + "=" * 25)
        try:
            from . import image_converter
            image_converter.run_conversion()
        except Exception as e:
            logger.error(f"❌ 在图片格式转换阶段发生严重错误: {e}", exc_info=True)


    logger.info("\n" + "=" * 60)
    logger.info("====== ChromaSky Toolkit 流程执行完毕！ ======")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()