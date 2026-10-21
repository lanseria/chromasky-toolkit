"""地图存储策略测试。

覆盖两部分：
1. ``image_converter.plan_conversion`` 的 pending / stale / up-to-date 判定，
   以及陈旧 WebP 清理后空目录的裁剪。
2. ``mapping.run_drawing`` 只生成综合图、不再创建/写入 ``individual`` 分时图。

所有测试均使用 tmp_path 构造的数据，不依赖真实 ``outputs`` 目录。
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from src.chromasky_toolkit import config, image_converter, mapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: bytes = b"x", mtime: float | None = None) -> Path:
    """写入一个最小文件；可选设置固定 mtime 以便判定增量转换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class _FakeDatasetContext:
    """模拟 ``xr.open_dataset`` 的上下文管理器，避免读写真实 NetCDF。"""

    def __init__(self, dataset: xr.Dataset):
        self._dataset = dataset

    def __enter__(self) -> xr.Dataset:
        return self._dataset

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _score_grid(value: float) -> xr.DataArray:
    """构造一个最小可合并的 final_score 网格。"""
    return xr.DataArray(
        np.full((2, 3), value, dtype=np.float32),
        dims=("latitude", "longitude"),
        coords={"latitude": [20.0, 25.0], "longitude": [100.0, 105.0, 110.0]},
        name="final_score",
    )


def _redirect_outputs(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """把绘制/日志相关路径重定向到 tmp_path，避免污染真实 outputs。"""
    outputs = tmp_path / "outputs"
    calc_dir = outputs / "calculations"
    maps_dir = outputs / "maps"
    monkeypatch.setattr(config, "CALCULATION_OUTPUTS_DIR", calc_dir)
    monkeypatch.setattr(config, "MAP_OUTPUTS_DIR", maps_dir)
    monkeypatch.setattr(config, "LOG_BASE_PATH", outputs)
    return calc_dir, maps_dir


# ---------------------------------------------------------------------------
# plan_conversion
# ---------------------------------------------------------------------------

def test_plan_conversion_source_missing_returns_empty(tmp_path):
    """源目录不存在时不做任何「陈旧」推断，返回空计划。"""
    plan = image_converter.plan_conversion(tmp_path / "maps", tmp_path / "maps_webp")

    assert plan.pending == []
    assert plan.stale == []
    assert plan.up_to_date == []


def test_plan_conversion_empty_dirs_returns_empty(tmp_path):
    """源/目标目录均为空时，三类文件都应为空。"""
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps_webp").mkdir()

    plan = image_converter.plan_conversion(tmp_path / "maps", tmp_path / "maps_webp")

    assert plan.pending == []
    assert plan.stale == []
    assert plan.up_to_date == []


def test_plan_conversion_classifies_pending_up_to_date_and_stale(tmp_path):
    """正确区分待转换、已最新、陈旧三类文件（含子目录）。"""
    source = tmp_path / "maps"
    target = tmp_path / "maps_webp"

    # 目标缺失 -> pending
    png_missing_target = _write(source / "composite" / "missing.png", mtime=1_600_000_000)
    # 目标比源旧 -> pending
    png_older_target = _write(source / "composite" / "older.png", mtime=1_600_000_000)
    _write(target / "composite" / "older.webp", mtime=1_599_999_000)
    # 目标与源同时刻（或更新）-> up_to_date
    png_up_to_date = _write(source / "composite" / "same.png", mtime=1_600_000_000)
    _write(target / "composite" / "same.webp", mtime=1_600_000_000)
    # 源 PNG 不存在 -> stale
    stale_webp = _write(target / "composite" / "gone.webp", mtime=1_600_000_000)
    # 深层目录中的陈旧 WebP 也应被识别
    nested_stale_webp = _write(
        target / "individual" / "2026-05-11" / "glow_index_old.webp", mtime=1_600_000_000
    )

    plan = image_converter.plan_conversion(source, target)

    assert sorted(plan.pending) == sorted([png_missing_target, png_older_target])
    assert plan.up_to_date == [png_up_to_date]
    assert sorted(plan.stale) == sorted([stale_webp, nested_stale_webp])


def test_plan_conversion_target_exists_with_newer_source_is_pending(tmp_path):
    """目标 WebP 存在但源 PNG 更新（重新绘制）时，应重新转换。"""
    source = tmp_path / "maps"
    target = tmp_path / "maps_webp"
    png = _write(source / "composite" / "a.png", mtime=1_600_000_100)
    _write(target / "composite" / "a.webp", mtime=1_600_000_000)

    plan = image_converter.plan_conversion(source, target)

    assert plan.pending == [png]
    assert plan.up_to_date == []
    assert plan.stale == []


# ---------------------------------------------------------------------------
# 陈旧 WebP 清理与空目录裁剪（不涉及 ProcessPoolExecutor）
# ---------------------------------------------------------------------------

def test_run_conversion_removes_stale_webp_and_empty_dirs(tmp_path, monkeypatch):
    """无待转换 PNG 时，run_conversion 应清理陈旧 WebP 并裁掉空目录。"""
    source = tmp_path / "maps"
    source.mkdir()
    target = tmp_path / "maps_webp"
    stale = _write(target / "individual" / "2026-05-11" / "glow_index_old.webp", mtime=1_600_000_000)
    # 综合图有自己的源 PNG，属于「已是最新」，必须保留且不触发并行转换
    _write(source / "composite" / "kept.png", mtime=1_600_000_000)
    kept = _write(target / "composite" / "kept.webp", mtime=1_600_000_000)

    monkeypatch.setattr(config, "MAP_OUTPUTS_DIR", source)
    monkeypatch.setattr(config, "MAP_WEBP_OUTPUTS_DIR", target)

    image_converter.run_conversion()

    assert not stale.exists()
    assert not (target / "individual").exists()
    assert kept.exists()


def test_prune_empty_dirs_keeps_non_empty_dirs(tmp_path):
    """_prune_empty_dirs 只删除空目录，保留仍有文件的目录。"""
    target = tmp_path / "maps_webp"
    (target / "individual" / "2026-05-11").mkdir(parents=True)
    kept = _write(target / "composite" / "kept.webp")

    removed = image_converter._prune_empty_dirs(target)

    assert removed == 2  # 2026-05-11 与 individual
    assert not (target / "individual").exists()
    assert kept.exists()


# ---------------------------------------------------------------------------
# mapping.run_drawing 只生成综合图
# ---------------------------------------------------------------------------

def test_run_drawing_generates_only_composite(tmp_path, monkeypatch, caplog):
    """run_drawing 只为每个事件组生成一张综合图，不再创建 individual 目录。"""
    caplog.set_level(logging.INFO)
    calc_dir, maps_dir = _redirect_outputs(tmp_path, monkeypatch)

    date_str = "2026-05-12"
    event_times = ["1900", "2000", "2100", "2200"]
    events = {
        f"{date_str}_sunset_{time_str}": datetime(2026, 5, 12, 11, 0, tzinfo=timezone.utc)
        for time_str in event_times
    }
    # 1900 / 2000 有有效结果；2100 是全零占位；2200 缺少结果文件
    result_values = {"1900": 10.0, "2000": 20.0, "2100": 0.0}
    for time_str in result_values:
        _write(calc_dir / date_str / f"glow_index_result_{time_str}.nc", b"fake-netcdf")

    def fake_open_dataset(path: Path):
        time_str = Path(path).stem.rsplit("_", 1)[-1]
        return _FakeDatasetContext(
            xr.Dataset({"final_score": _score_grid(result_values[time_str])})
        )

    monkeypatch.setattr(mapping.xr, "open_dataset", fake_open_dataset)
    monkeypatch.setattr(mapping, "expand_all_future_events", lambda: events)

    generated: list[tuple[Path, str, xr.DataArray]] = []

    def fake_generate_map_from_grid(score_grid, title, output_path):
        output_path.write_bytes(b"fake-png")
        generated.append((Path(output_path), title, score_grid))
        return b"fake-png-bytes"

    monkeypatch.setattr(mapping, "generate_map_from_grid", fake_generate_map_from_grid)

    mapping.run_drawing()

    # 只调用一次绘图，且落在 composite 目录
    assert len(generated) == 1
    output_path, title, score_grid = generated[0]
    expected_path = maps_dir / "composite" / f"glow_index_composite_{date_str}_sunset.png"
    assert output_path == expected_path
    assert "individual" not in output_path.parts
    assert not (maps_dir / "individual").exists()
    assert sorted(maps_dir.rglob("*.png")) == [expected_path]

    # 综合图仍是「时间维度取 max」，标题时间段取实际可用时段 min–max
    assert float(score_grid.max()) == pytest.approx(20.0)
    assert "综合最佳" in title
    assert "19:00 - 20:00" in title

    # 日志明确分时图已停用，并汇总缺失时段
    assert "分时图已停用" in caplog.text
    assert "2200" in caplog.text


def test_run_drawing_skips_composite_when_all_results_missing(tmp_path, monkeypatch, caplog):
    """整组缺少计算结果时不绘图，并给出一次汇总提示。"""
    caplog.set_level(logging.INFO)
    _calc_dir, maps_dir = _redirect_outputs(tmp_path, monkeypatch)

    events = {
        "2026-05-12_sunset_1900": datetime(2026, 5, 12, 11, 0, tzinfo=timezone.utc),
        "2026-05-12_sunset_2000": datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(mapping, "expand_all_future_events", lambda: events)

    generated = []
    monkeypatch.setattr(
        mapping, "generate_map_from_grid", lambda **kwargs: generated.append(kwargs)
    )

    mapping.run_drawing()

    assert generated == []
    assert not (maps_dir / "composite").exists()
    assert "缺少全部 2 个时间点" in caplog.text
