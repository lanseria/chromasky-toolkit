#!/usr/bin/env python
"""清理历史遗留的分时指数图与陈旧 WebP。

分时指数图已停用：`outputs/maps/individual/**` 与 `outputs/maps_webp/individual/**`
不再生成、不再转换、也不再展示。本脚本用于清理旧版本留下的历史残留。

清理范围：
    1. 目录 `outputs/maps/individual`（分时图 PNG）
    2. 目录 `outputs/maps_webp/individual`（分时图 WebP）
    3. `outputs/maps_webp` 中「源 PNG 已不存在」的陈旧 `.webp`（不含上面两个目录，
       它们会被整目录删除）

安全约定：
    - 默认 dry-run：只打印将删除的内容，不删除任何文件；加 `--yes` 才会真正删除。
    - 所有待删除路径都会 resolve() 后校验必须位于 `outputs/` 之下，防止误删。
    - 不会触碰 `outputs/maps/composite`、`outputs/maps_webp/composite`、
      `outputs/calculations` 与 `chroma-sky-tiles`。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# Windows 重定向/管道输出时默认编码可能是 GBK，而 config 导入时会打印 emoji；
# 这里统一按 UTF-8 输出（替换无法编码的字符），避免脚本因 UnicodeEncodeError 退出。
# 交互式控制台（TTY）保持原编码，Windows 下 Python 控制台本就使用 Unicode API。
for _stream in (sys.stdout, sys.stderr):
    try:
        if not _stream.isatty():
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - 特殊流不支持时忽略
        pass

try:
    from chromasky_toolkit import config
except ImportError:
    # 作为独立脚本运行时，把 src 加入搜索路径
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from chromasky_toolkit import config


def _human_size(num_bytes: int) -> str:
    """把字节数格式化为便于阅读的大小。"""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _resolve_under_outputs(path: Path, outputs_root: Path) -> Path:
    """resolve 路径并校验其严格位于 outputs 目录内，否则抛出 ValueError。"""
    resolved = path.resolve()
    root = outputs_root.resolve()
    # 必须位于 outputs 之下（且不能就是 outputs 本身）
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"拒绝操作 outputs 目录之外的路径: {resolved}")
    return resolved


def _display(path: Path, outputs_root: Path) -> str:
    """相对 outputs 目录展示路径。"""
    try:
        return str(path.relative_to(outputs_root.resolve()))
    except ValueError:
        return str(path)


@dataclass
class CleanupPlan:
    """一次清理的扫描计划（纯数据，无副作用）。"""

    outputs_root: Path
    legacy_dirs: list[Path]
    stale_webp: list[Path]

    @property
    def is_empty(self) -> bool:
        return not self.legacy_dirs and not self.stale_webp


def build_plan(outputs_root: Path) -> CleanupPlan:
    """扫描 outputs 目录，构建「历史分时图目录 + 陈旧 WebP」清理计划。

    Args:
        outputs_root: outputs 目录根（通常为 config.OUTPUTS_DIR）。

    Returns:
        CleanupPlan: 待删除的目录与文件列表（均已 resolve 并校验在 outputs 之下）。
    """
    outputs_root = outputs_root.resolve()
    maps_dir = outputs_root / "maps"
    webp_dir = outputs_root / "maps_webp"

    # 1. 历史分时图目录（不存在则忽略）
    legacy_dirs: list[Path] = []
    for candidate in (maps_dir / "individual", webp_dir / "individual"):
        safe_path = _resolve_under_outputs(candidate, outputs_root)
        if safe_path.is_dir():
            legacy_dirs.append(safe_path)

    # 2. 陈旧 WebP：目标目录中存在、但对应源 PNG 已不存在
    stale_webp: list[Path] = []
    legacy_webp_dir = _resolve_under_outputs(webp_dir / "individual", outputs_root)
    if webp_dir.is_dir():
        for webp_path in sorted(p for p in webp_dir.rglob("*.webp") if p.is_file()):
            # 整个 legacy individual 目录将被删除，其中文件无需重复计入
            if webp_path.is_relative_to(legacy_webp_dir):
                continue
            source_png = maps_dir / webp_path.relative_to(webp_dir).with_suffix(".png")
            if not source_png.is_file():
                stale_webp.append(_resolve_under_outputs(webp_path, outputs_root))

    return CleanupPlan(outputs_root=outputs_root, legacy_dirs=legacy_dirs, stale_webp=stale_webp)


def _dir_stats(directory: Path) -> tuple[int, int]:
    """返回目录内（递归）文件数量与总字节数。"""
    files = [p for p in directory.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def print_plan(plan: CleanupPlan, dry_run: bool) -> None:
    """打印清理计划。"""
    if dry_run:
        print("====== 历史地图清理（DRY-RUN，仅预览，不会删除任何文件） ======")
    else:
        print("====== 历史地图清理（已确认 --yes，将真正删除） ======")
    print(f"outputs 目录: {plan.outputs_root}")

    print("\n-- 历史分时图目录 --")
    if plan.legacy_dirs:
        for directory in plan.legacy_dirs:
            file_count, total_size = _dir_stats(directory)
            action = "将删除" if dry_run else "待删除"
            print(f"[{action}] {_display(directory, plan.outputs_root)}"
                  f"（{file_count} 个文件，{_human_size(total_size)}）")
    else:
        print("[无需删除] 未发现历史分时图目录（maps/individual、maps_webp/individual）")

    print("\n-- 陈旧 WebP（源 PNG 已不存在） --")
    if plan.stale_webp:
        action = "将删除" if dry_run else "待删除"
        print(f"[{action}] {len(plan.stale_webp)} 个陈旧 WebP 文件：")
        for webp_path in plan.stale_webp:
            print(f"    - {_display(webp_path, plan.outputs_root)}")
    else:
        print("[无需删除] 未发现源 PNG 已不存在的陈旧 WebP")

    # 明确列出保留内容，便于确认不会误删综合图与计算中间数据
    print("\n-- 保留（不受影响） --")
    for label, candidate in (
        ("综合图 PNG", plan.outputs_root / "maps" / "composite"),
        ("综合图 WebP", plan.outputs_root / "maps_webp" / "composite"),
        ("指数计算中间数据", plan.outputs_root / "calculations"),
    ):
        if candidate.is_dir():
            file_count, total_size = _dir_stats(candidate)
            print(f"[保留] {_display(candidate, plan.outputs_root)}"
                  f"（{file_count} 个文件，{_human_size(total_size)}）")
        else:
            print(f"[保留] {_display(candidate, plan.outputs_root)}（不存在，忽略）")


def execute_plan(plan: CleanupPlan) -> tuple[int, int, int]:
    """真正执行删除计划。

    Returns:
        (删除的目录数, 删除的分时图文件数, 删除的陈旧 WebP 数)
    """
    deleted_dirs = 0
    deleted_files = 0

    # 删除前逐项再次 resolve 校验，确保待删路径仍在 outputs 之下
    for directory in plan.legacy_dirs:
        safe_dir = _resolve_under_outputs(directory, plan.outputs_root)
        file_count, _ = _dir_stats(safe_dir)
        shutil.rmtree(safe_dir)
        deleted_dirs += 1
        deleted_files += file_count
        print(f"  🗑️ 已删除目录: {_display(safe_dir, plan.outputs_root)}（{file_count} 个文件）")

    deleted_stale = 0
    for webp_path in plan.stale_webp:
        safe_path = _resolve_under_outputs(webp_path, plan.outputs_root)
        try:
            safe_path.unlink()
            deleted_stale += 1
        except FileNotFoundError:
            # 扫描到删除之间被其他进程删除，无需处理
            continue
        print(f"  🗑️ 已删除陈旧 WebP: {_display(safe_path, plan.outputs_root)}")

    return deleted_dirs, deleted_files, deleted_stale


def main(argv: list[str] | None = None) -> int:
    """命令行入口。默认 dry-run，加 --yes 才真正删除。"""
    parser = argparse.ArgumentParser(
        description=(
            "清理历史遗留的分时指数图目录（outputs/maps/individual、"
            "outputs/maps_webp/individual）以及源 PNG 已不存在的陈旧 WebP。\n"
            "默认 dry-run：只打印将删除的内容，不删除任何文件；"
            "确认无误后加 --yes 才会真正删除。"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行删除（默认不加则为 dry-run，仅预览）",
    )
    args = parser.parse_args(argv)

    outputs_root = config.OUTPUTS_DIR
    if not outputs_root.is_dir():
        print(f"❌ outputs 目录不存在: {outputs_root}，无需清理。")
        return 1

    plan = build_plan(outputs_root)
    print_plan(plan, dry_run=not args.yes)

    if not args.yes:
        print("\n提示：当前为 dry-run，未删除任何文件。确认无误后加 --yes 才会真正删除。")
        return 0

    if plan.is_empty:
        print("\n没有需要清理的内容，未做任何修改。")
        return 0

    print("\n-- 开始执行删除 --")
    deleted_dirs, deleted_files, deleted_stale = execute_plan(plan)
    print(
        f"\n✅ 清理完成：删除 {deleted_dirs} 个目录、{deleted_files} 个分时图文件、"
        f"{deleted_stale} 个陈旧 WebP。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
